#!/usr/bin/env python3
"""Match a repository against the offers dataset and print a markdown report.

Usage:
    python scripts/match.py /path/to/repo [--github owner/name]

Reads the working tree (no network), detects what the project uses and needs
via matching/rules.yaml, filters offers by their structured eligibility fields,
and prints recommendations with reasons. --github adds repo age/activity checks
via `gh api` if the gh CLI is available.
"""

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OFFERS_DIR = ROOT / "data" / "offers"
RULES_PATH = ROOT / "matching" / "rules.yaml"

SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", "target",
             ".venv", "venv", "__pycache__", ".next", "coverage", "third_party",
             "third-party", "deps"}
LANG_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".rs": "Rust", ".go": "Go", ".c": "C", ".h": "C",
    ".cc": "C++", ".cpp": "C++", ".hpp": "C++", ".rb": "Ruby", ".java": "Java",
    ".kt": "Kotlin", ".swift": "Swift", ".lua": "Lua", ".vim": "Vimscript",
    ".php": "PHP", ".cs": "C#", ".ex": "Elixir", ".zig": "Zig",
}
LICENSE_PATTERNS = [
    ("Apache-2.0", r"apache license"), ("MIT", r"\bmit license\b|permission is hereby granted, free of charge"),
    ("GPL", r"gnu general public license"), ("LGPL", r"gnu lesser general public"),
    ("AGPL", r"gnu affero"), ("MPL-2.0", r"mozilla public license"),
    ("BSD", r"redistribution and use in source and binary forms"),
    ("ISC", r"\bisc license\b"), ("Unlicense", r"unlicense"),
]


# --------------------------------------------------------------- fact gathering
def gather_facts(repo: Path, github: str | None) -> dict:
    files: set[str] = set()
    basenames: set[str] = set()
    dirs: set[str] = set()
    ext_counts: Counter = Counter()

    for path in repo.rglob("*"):
        rel = path.relative_to(repo)
        parts = rel.parts
        if any(p in SKIP_DIRS for p in parts):
            continue
        if path.is_dir():
            dirs.add(path.name.lower())
            continue
        rp = rel.as_posix()
        if len(files) < 60000:
            files.add(rp)
            basenames.add(path.name)
        ext_counts[path.suffix.lower()] += 1

    langs = Counter()
    for ext, n in ext_counts.items():
        if ext in LANG_BY_EXT:
            langs[LANG_BY_EXT[ext]] += n

    deps = gather_deps(repo)

    workflows = []
    wf_dir = repo / ".github" / "workflows"
    if wf_dir.is_dir():
        for f in wf_dir.glob("*.y*ml"):
            try:
                workflows.append(f.read_text(errors="replace"))
            except OSError:
                pass
    for extra in (".travis.yml", "appveyor.yml", ".circleci/config.yml", ".cirrus.yml"):
        p = repo / extra
        if p.is_file():
            workflows.append(p.read_text(errors="replace"))
    workflow_text = "\n".join(workflows).lower()

    readme_text = ""
    for name in ("README.md", "README.rst", "README", "readme.md"):
        p = repo / name
        if p.is_file():
            readme_text = p.read_text(errors="replace")[:80000].lower()
            break

    license_name = None
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "LICENCE"):
        p = repo / name
        if p.is_file():
            text = p.read_text(errors="replace")[:4000].lower()
            for lic, pat in LICENSE_PATTERNS:
                if re.search(pat, text):
                    license_name = lic
                    break
            break

    created_at = pushed_at = None
    if github:
        try:
            out = subprocess.run(
                ["gh", "api", f"repos/{github}", "-q", "{created: .created_at, pushed: .pushed_at}"],
                capture_output=True, text=True, timeout=30, check=True,
            ).stdout
            info = json.loads(out)
            created_at = info.get("created")
            pushed_at = info.get("pushed")
        except (subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError):
            pass

    flags: set[str] = set()
    pkg = repo / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(errors="replace"))
            # Heuristic for "this is an npm library, not just an app with a
            # package.json": has an entry point, isn't private, isn't Electron.
            if (not data.get("private")
                    and any(k in data for k in ("main", "module", "exports"))
                    and "electron" not in deps):
                flags.add("npm_published")
        except json.JSONDecodeError:
            pass

    return {
        "files": files, "basenames": basenames, "dirs": dirs,
        "langs": [l for l, _ in langs.most_common(4)],
        "deps": deps, "workflow_text": workflow_text, "readme_text": readme_text,
        "license": license_name, "created_at": created_at, "pushed_at": pushed_at,
        "flags": flags,
    }


def gather_deps(repo: Path) -> set[str]:
    deps: set[str] = set()
    pkg = repo / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(errors="replace"))
            for key in ("dependencies", "devDependencies", "optionalDependencies"):
                deps.update(k.lower() for k in (data.get(key) or {}))
        except json.JSONDecodeError:
            pass
    for req in list(repo.glob("requirements*.txt")) + list(repo.glob("requirements/*.txt")):
        for line in req.read_text(errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "-")):
                deps.add(re.split(r"[<>=\[~!;\s]", line)[0].lower())
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(errors="replace")
        for m in re.finditer(r'"([A-Za-z0-9_.-]+)\s*[<>=~!\[]', text):
            deps.add(m.group(1).lower())
    cargo = repo / "Cargo.toml"
    if cargo.is_file():
        text = cargo.read_text(errors="replace")
        in_deps = False
        for line in text.splitlines():
            if re.match(r"\[.*dependencies.*\]", line):
                in_deps = True
                continue
            if line.startswith("["):
                in_deps = False
            if in_deps:
                m = re.match(r"\s*([A-Za-z0-9_-]+)\s*=", line)
                if m:
                    deps.add(m.group(1).lower())
    gomod = repo / "go.mod"
    if gomod.is_file():
        for m in re.finditer(r"^\t?([\w./-]+) v", gomod.read_text(errors="replace"), re.M):
            deps.add(m.group(1).split("/")[-1].lower())
    gemfile = repo / "Gemfile"
    if gemfile.is_file():
        for m in re.finditer(r"""gem ["']([\w-]+)["']""", gemfile.read_text(errors="replace")):
            deps.add(m.group(1).lower())
    return deps


# --------------------------------------------------------------- rule evaluation
def signal_hit(sig: dict, facts: dict) -> str | None:
    """Return the matched thing (for {match} interpolation) or None."""
    kind = sig["kind"]
    if kind == "dep":
        for d in sig["any"]:
            if d.lower() in facts["deps"]:
                return d
    elif kind == "file":
        for pat in sig["any"]:
            if "/" in pat:
                if any(fnmatch.fnmatch(f, pat) for f in facts["files"]):
                    return pat
            elif pat in facts["basenames"]:
                return pat
    elif kind == "dir":
        for d in sig["any"]:
            if d.lower() in facts["dirs"]:
                return d
    elif kind == "workflow":
        m = re.search(sig["regex"], facts["workflow_text"], re.I)
        if m:
            return m.group(0).strip()[:60]
    elif kind == "readme":
        m = re.search(sig["regex"], facts["readme_text"], re.I)
        if m:
            return m.group(0).strip()[:60]
    elif kind == "lang":
        for l in sig["any"]:
            if l in facts["langs"]:
                return l
    elif kind == "flag":
        for f in sig["any"]:
            if f in facts["flags"]:
                return f
    return None


def eligibility_checks(offer: dict, facts: dict) -> tuple[list[str], bool]:
    """Return (human-readable checks, definitely_ineligible)."""
    checks, out = offer.get("eligibility") or {}, []
    ineligible = False
    if checks.get("osi_license_required"):
        lic = facts["license"]
        if lic:
            out.append(f"requires OSI license — detected {lic} ✓")
        else:
            out.append("requires OSI license — could not detect yours, verify")
    age_req = checks.get("min_project_age_months")
    if age_req and facts["created_at"]:
        created = datetime.fromisoformat(facts["created_at"].replace("Z", "+00:00"))
        months = (datetime.now(timezone.utc) - created).days // 30
        if months >= age_req:
            out.append(f"requires ≥{age_req} months of history — {months} months ✓")
        else:
            out.append(f"requires ≥{age_req} months of history — only {months} ✗")
            ineligible = True
    if checks.get("non_commercial_only"):
        out.append("non-commercial projects only")
    if checks.get("active_development_required") and facts["pushed_at"]:
        pushed = datetime.fromisoformat(facts["pushed_at"].replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - pushed).days
        out.append(f"requires active development — last push {days}d ago "
                   + ("✓" if days < 90 else "✗"))
        if days >= 90:
            ineligible = True
    return out, ineligible


# --------------------------------------------------------------- matching
def run(repo: Path, github: str | None) -> str:
    facts = gather_facts(repo, github)
    rules = yaml.safe_load(RULES_PATH.read_text())

    offers = {}  # slug -> doc
    for path in sorted(OFFERS_DIR.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text())
        if not doc:
            continue
        doc["offers"] = [o for o in doc["offers"] if o.get("status") != "discontinued"]
        if doc["offers"]:
            offers[path.stem] = doc

    cat_of = {slug: set(d.get("categories") or []) for slug, d in offers.items()}

    # covered tools
    covered: dict[str, str] = {}  # slug -> tool name in use
    for rule in rules.get("covered", []):
        if signal_hit(rule, facts):
            targets = set(rule.get("companies") or [])
            if rule.get("category"):
                targets |= {s for s, cats in cat_of.items() if rule["category"] in cats}
            for slug in targets:
                covered[slug] = rule["tool"]

    # signals -> reasons per offer
    reasons: dict[str, list[str]] = {}
    for sig in rules["signals"]:
        match = signal_hit(sig, facts)
        if not match:
            continue
        reason = sig["reason"].replace("{match}", match)
        targets = set(sig.get("companies") or [])
        if sig.get("category"):
            targets |= {s for s, cats in cat_of.items() if sig["category"] in cats}
        for slug in targets:
            if slug in offers and reason not in reasons.setdefault(slug, []):
                reasons[slug].append(reason)

    # build report
    recommended, already, ineligible_hits = [], [], []
    for slug, rsn in sorted(reasons.items(), key=lambda kv: -len(kv[1])):
        doc = offers[slug]
        for o in doc["offers"]:
            # Personal-tool offers belong in the maintainer section even when
            # a project signal matched the company.
            if (o.get("eligibility") or {}).get("applies_to") in ("maintainer", "contributors"):
                continue
            checks, bad = eligibility_checks(o, facts)
            entry = {"company": doc["company"], "product": o["product"],
                     "url": o["offer_url"], "what": o["what_you_get"],
                     "reasons": rsn, "checks": checks}
            if slug in covered and covered[slug] != doc["company"]:
                entry["tool"] = covered[slug]
                already.append(entry)
            elif bad:
                ineligible_hits.append(entry)
            else:
                recommended.append(entry)

    maintainer_offers = []
    for slug, doc in offers.items():
        for o in doc["offers"]:
            applies = (o.get("eligibility") or {}).get("applies_to")
            if applies in ("maintainer", "contributors"):
                maintainer_offers.append(f"**{doc['company']}** — {o['product']}")

    lines = [f"# foropensource report: {repo.name}", ""]
    lines.append(f"**Languages:** {', '.join(facts['langs']) or 'n/a'}  ")
    lines.append(f"**License:** {facts['license'] or 'not detected'}  ")
    if facts["created_at"]:
        lines.append(f"**Created:** {facts['created_at'][:10]}, last push {facts['pushed_at'][:10]}  ")
    lines.append(f"**Signals:** {len(reasons)} offers matched by "
                 f"{sum(len(r) for r in reasons.values())} signals")
    lines.append("")

    lines.append(f"## Recommended ({len(recommended)})\n")
    # Offers that matched for identical reasons are alternatives — group them.
    by_reasons: dict[tuple, list] = {}
    for e in recommended:
        by_reasons.setdefault(tuple(e["reasons"]), []).append(e)
    for rsn, group in by_reasons.items():
        if len(group) >= 4:
            lines.append(f"### Alternatives — pick one ({len(group)} offers)")
            for r in rsn:
                lines.append(f"- why: {r}")
            for e in group:
                lines.append(f"- **{e['company']}** — {e['product']}: {e['url']}")
            lines.append("")
        else:
            for e in group:
                lines.append(f"### {e['company']} — {e['product']}")
                for r in e["reasons"]:
                    lines.append(f"- why: {r}")
                for c in e["checks"]:
                    lines.append(f"- eligibility: {c}")
                lines.append(f"- what you get: {e['what']}")
                lines.append(f"- apply: {e['url']}")
                lines.append("")

    if already:
        lines.append("## Already covered\n")
        for e in already:
            lines.append(f"- {e['company']} — {e['product']} "
                         f"(you appear to use **{e['tool']}** for this)")
        lines.append("")

    if ineligible_hits:
        lines.append("## Matched but not (yet) eligible\n")
        for e in ineligible_hits:
            lines.append(f"- {e['company']} — {e['product']}: {'; '.join(e['checks'])}")
        lines.append("")

    if maintainer_offers:
        lines.append(f"## For maintainers and contributors ({len(maintainer_offers)})\n")
        lines.append("Personal-tool offers that most active OSS maintainers qualify for:\n")
        for m in sorted(maintainer_offers):
            lines.append(f"- {m}")
        lines.append("")

    n_total = sum(len(d["offers"]) for d in offers.values())
    lines.append(f"---\n{n_total} active offers in the dataset; the rest are at "
                 f"https://foropensource.com")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", type=Path)
    ap.add_argument("--github", help="owner/name for age/activity checks via gh api")
    args = ap.parse_args()
    if not args.repo.is_dir():
        print(f"not a directory: {args.repo}", file=sys.stderr)
        return 1
    print(run(args.repo.resolve(), args.github))
    return 0


if __name__ == "__main__":
    sys.exit(main())
