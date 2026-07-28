#!/usr/bin/env python3
"""Build the static site from data/offers/ into _site/.

Pages:
  /                       directory of all offers + client-side repo matcher
  /company/<slug>/        one page per company (SEO: "{company} open source")
  /category/<slug>/       one page per category
  /sponsors/              league table from data/exports/company-sponsorships.csv
Companies whose offers are all discontinued get a "graveyard" page with
alternatives instead of a directory entry.

Plus offers.json, offers.csv, rules.json (for the matcher), llms.txt,
llms-full.txt, sitemap.xml, robots.txt, 404.html, and og.png (copied
from assets/).
"""

import csv
import html
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OFFERS_DIR = ROOT / "data" / "offers"
RULES_PATH = ROOT / "matching" / "rules.yaml"
SPONSORSHIPS_CSV = ROOT / "data" / "exports" / "company-sponsorships.csv"
OUT_DIR = ROOT / "_site"

REPO_URL = "https://github.com/natwar86/foropensource"
SITE_URL = "https://foropensource.com"
GA_MEASUREMENT_ID = "G-WL62869LEP"

CATEGORY_LABELS = {
    "ci-cd": "CI/CD",
    "ide-tools": "IDEs and dev tools",
    "ai-ml": "AI and ML",
    "cdn": "CDN",
    "error-tracking": "error tracking",
    "project-management": "project management",
    "licensing-compliance": "license compliance",
    "other": "more tools",
}


def esc(value) -> str:
    return html.escape(str(value), quote=True)


# Google truncates SERP titles around 60 chars and snippets around 155-160.
# Lengths are measured on the raw text, which is what Google renders — the
# HTML-escaped form is longer (an apostrophe becomes &#x27;) but that is not
# what gets counted.
TITLE_LIMIT = 60
DESC_LIMIT = 158


def short_name(company: str) -> str:
    """Drop a trailing parenthetical: titles want the brand, not the gloss.

    "Qlty Software (Code Climate)" -> "Qlty Software"
    """
    return re.sub(r"\s*\([^)]*\)\s*$", "", company).strip() or company


def possessive(name: str) -> str:
    """"Azure Pipelines'" not "Azure Pipelines's"."""
    return f"{name}'" if name.rstrip().endswith(("s", "S")) else f"{name}'s"


def fit_title(*candidates: str) -> str:
    """First candidate that fits the SERP width; else trim the last one.

    Callers pass richest-first, so a short brand keeps the full phrasing and a
    long one degrades to the bare keyword rather than being cut mid-word.
    """
    for candidate in candidates:
        if len(candidate) <= TITLE_LIMIT:
            return candidate
    return clamp(candidates[-1], TITLE_LIMIT)


def clamp(text: str, limit: int) -> str:
    """Trim to a word boundary; SERP truncation cuts mid-word and looks broken."""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    cut = text[:limit - 1]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,;:—-") + "…"


def cat_label(slug: str) -> str:
    return CATEGORY_LABELS.get(slug, slug.replace("-", " "))


def n_companies(n: int) -> str:
    return f"{n} company" if n == 1 else f"{n} companies"


def eligibility_line(elig: dict) -> str:
    bits = []
    applies_to = elig.get("applies_to")
    if applies_to:
        bits.append(f"for the {applies_to}" if applies_to != "contributors" else "for contributors")
    if elig.get("osi_license_required"):
        bits.append("OSI license required")
    if elig.get("non_commercial_only"):
        bits.append("non-commercial only")
    if elig.get("public_repo_required"):
        bits.append("public repo required")
    age = elig.get("min_project_age_months")
    if age:
        bits.append(f"project at least {age} months old")
    notes = elig.get("notes")
    if notes:
        bits.append(notes)
    return "; ".join(bits)


STALE_DAYS = 45  # an active offer not re-verified in this many days shows "stale"


def _domain_path(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url or "").rstrip("/")


def offer_status(offer: dict) -> str:
    st = (offer.get("status") or "active").lower()
    if st == "discontinued":
        return "discontinued"
    lv = offer.get("last_verified")
    if lv:
        try:
            y, m, d = map(int, lv.split("-"))
            if (date.today() - date(y, m, d)).days > STALE_DAYS:
                return "stale"
        except Exception:
            pass
    return "active"


def doc_status(doc: dict) -> str:
    sts = [offer_status(o) for o in doc["offers"]]
    if any(s == "active" for s in sts):
        return "active"
    if any(s == "stale" for s in sts):
        return "stale"
    return "discontinued"


def requirement_tokens(elig: dict) -> list[str]:
    """Structured eligibility fields -> short requirement labels (repo-checkable)."""
    out = []
    if elig.get("osi_license_required"):
        out.append("OSI-approved license")
    m = elig.get("min_project_age_months")
    if m:
        out.append(f"project ≥ {m * 30} days" if m < 2 else f"project ≥ {m} months")
    if elig.get("active_development_required"):
        out.append("actively developed")
    if elig.get("public_repo_required"):
        out.append("public repository")
    if elig.get("non_commercial_only"):
        out.append("non-commercial / non-profit")
    return out


def applies_pair(elig: dict) -> tuple[str, str]:
    a = (elig.get("applies_to") or "").lower()
    return {
        "project": ("the project", "not individual maintainers"),
        "maintainer": ("an individual maintainer", ""),
        "contributors": ("contributors", ""),
        "both": ("project or maintainer", ""),
    }.get(a, (a or "—", ""))


def summarize(text: str, n: int = 104) -> str:
    text = " ".join((text or "").split())
    first = text.split(". ")[0]
    if len(first) > n:
        first = first[:n].rsplit(" ", 1)[0] + "…"
    elif len(first) < len(text) and not first.endswith("…"):
        first += "…"
    return first


def render_spec(offer: dict, discontinued: bool = False) -> str:
    """The standardized field grid for one offer — same fields, same order."""
    elig = offer.get("eligibility") or {}
    dp = _domain_path(offer.get("offer_url", ""))
    anchor = ""
    va = offer.get("verify_anchor")
    if va:
        anchor = f' &mdash; matched anchor <span class="anchor">&ldquo;{esc(va[0])}&rdquo;</span>'
    rows: list[tuple[str, str]] = []
    if discontinued:
        rows.append(("What it was", f'<div class="v prose">{esc(offer.get("what_you_get", ""))}</div>'))
        rows.append(("How to apply", f'<div class="v">{esc(offer.get("how_to_apply", ""))}</div>'))
        rows.append(("Provenance", f'<div class="v"><span class="prov">Checked '
                     f'<b>{esc(offer.get("last_verified", ""))}</b>: program page gone or offer '
                     f'withdrawn. Retained for the record.</span></div>'))
    else:
        al, an = applies_pair(elig)
        toks = requirement_tokens(elig)
        if toks:
            chips = "".join(
                f'<span class="req"><i class="mk"></i><span class="req-t">{esc(t)}</span></span>'
                for t in toks
            )
            reqs = (f'<div class="reqs">{chips}</div>'
                    '<div class="reqs-note">run a repo match above to see which you meet &rarr;</div>')
        else:
            reqs = '<span class="req-none">no stated requirements</span>'
        applies = (f'<span class="applies">{esc(al)}'
                   + (f' <span class="b">&mdash; {esc(an)}</span>' if an else "") + "</span>")
        rows.append(("What you get", f'<div class="v prose">{esc(offer.get("what_you_get", ""))}</div>'))
        rows.append(("Applies to", f'<div class="v">{applies}</div>'))
        rows.append(("Requirements", f'<div class="v">{reqs}</div>'))
        rows.append(("How to apply", f'<div class="v">{esc(offer.get("how_to_apply", ""))}</div>'))
        rows.append(("Provenance", f'<div class="v"><span class="prov">Confirmed against '
                     f'<b>{esc(dp)}</b> on <b>{esc(offer.get("last_verified", ""))}</b>{anchor}.</span></div>'))
    body = "".join(f'<div class="r"><div class="k">{esc(k)}</div>{v}</div>' for k, v in rows)
    return f'<div class="spec">{body}</div>'


def _offer_blocks(doc: dict, discontinued: bool) -> str:
    multi = len(doc["offers"]) > 1
    out = []
    for i, off in enumerate(doc["offers"]):
        label = (f'<div class="offer-label">Offer {i + 1} &mdash; {esc(off.get("product", ""))}</div>'
                 if multi else "")
        out.append(label + render_spec(off, discontinued))
    return "".join(out)


def render_row(doc: dict, with_check: bool = True) -> str:
    """A compressed directory row that expands to the full datasheet in place."""
    off0 = doc["offers"][0]
    st = doc_status(doc)
    st = st if st in ("active", "stale") else "active"
    sc = {"active": "a", "stale": "s"}[st]
    cats = doc.get("categories") or []
    cat_tags = "".join(
        f'<a class="tag" href="/category/{esc(c)}/">{esc(cat_label(c))}</a>' for c in cats
    )
    blob = " ".join([doc["company"]] + cats
                    + [o.get("product", "") + " " + o.get("what_you_get", "") for o in doc["offers"]]).lower()
    ver = max((o.get("last_verified", "") for o in doc["offers"]), default="")
    verword = "re-check due" if st == "stale" else "verified"
    url = off0.get("offer_url", "#")
    check_btn = ('<button class="check-one">&#9889; Check my repo against this</button>'
                 if with_check else '<a class="prog" href="/#check">Check your repo &rarr;</a>')
    footer = (
        f'<a class="prog" href="{esc(url)}" target="_blank" rel="noopener nofollow" '
        f'data-track="offer_click" data-company="{esc(doc["company"])}" '
        f'data-product="{esc(off0.get("product", ""))}">Open program page &nearr;</a>'
        f'{check_btn}'
    )
    detail = f'<div class="detail">{_offer_blocks(doc, False)}<div class="rec-ft">{footer}</div></div>'
    return f'''<div class="rowwrap" data-slug="{esc(doc["slug"])}" data-cats="{esc(" ".join(cats))}" data-status="{st}" data-search="{esc(blob)}">
  <div class="row" tabindex="0">
    <span class="ix">{esc(doc.get("fos_id", ""))}</span>
    <span class="co"><a class="name" href="/company/{esc(doc["slug"])}/">{esc(doc["company"])}</a><span class="rtags">{cat_tags}</span></span>
    <span class="sum">{esc(summarize(off0.get("what_you_get", "")))}</span>
    <span class="rstatus"><span class="status {sc}"><i class="dot {sc}"></i>{st.upper()}</span></span>
    <span class="rver">{esc(verword)} {esc(ver)}</span>
    <span class="chev">&rsaquo;</span>
  </div>
  {detail}
</div>'''


def render_record(doc: dict, discontinued: bool = False) -> str:
    """A single standalone record (for company / graveyard pages)."""
    company = doc["company"]
    cats = doc.get("categories") or []
    cat_tags = "".join(
        f'<a class="tag" href="/category/{esc(c)}/">{esc(cat_label(c))}</a>' for c in cats
    )
    ver = max((o.get("last_verified", "") for o in doc["offers"]), default="")
    n = len(doc["offers"])
    prod = doc["offers"][0].get("product", "")
    prodline = f'<div class="prod">{esc(prod)}</div>' if n == 1 else f'<div class="prod">{n} offers</div>'
    if discontinued:
        cls, sc, slabel = " obsolete", "d", "DISCONTINUED"
        verline = f'confirmed gone <b>{esc(ver)}</b>'
        banner = ('<div class="obs-banner"><b>In the graveyard.</b> Kept on the record so you '
                  'don&rsquo;t waste an application &mdash; the dedicated program is gone.</div>')
        name_html = esc(company)
        footer = '<span class="no-apply">no application path &mdash; alternatives below</span>'
    else:
        s = doc_status(doc)
        s = s if s in ("active", "stale") else "active"
        sc, slabel = {"active": "a", "stale": "s"}[s], s.upper()
        verline = f'{"re-check due" if s == "stale" else "verified"} <b>{esc(ver)}</b>'
        banner, cls = "", ""
        name_html = (f'<a href="{esc(doc["website"])}" target="_blank" rel="noopener nofollow" '
                     f'data-track="company_click" data-company="{esc(company)}">{esc(company)}</a>')
        url = doc["offers"][0].get("offer_url", "#")
        footer = (f'<a class="prog" href="{esc(url)}" target="_blank" rel="noopener nofollow" '
                  f'data-track="offer_click" data-company="{esc(company)}" data-product="{esc(prod)}">'
                  f'Open program page &nearr;</a>'
                  f'<a class="prog" href="/#check">Check your repo &rarr;</a>')
    return f'''<article class="rec{cls}">
  <div class="rec-hd">
    <span class="id">{esc(doc.get("fos_id", ""))}</span>
    <span class="right"><span class="status {sc}"><i class="dot {sc}"></i>{slabel}</span> <span class="verified">{verline}</span></span>
  </div>
  {banner}
  <div class="rec-id">
    <div><h2>{name_html}</h2>{prodline}</div>
    <div class="tags">{cat_tags}</div>
  </div>
  {_offer_blocks(doc, discontinued)}
  <div class="rec-ft">{footer}</div>
</article>'''


CSS = """
:root{
  --paper:#f2f1ea; --card:#fff; --ink:#1a1a15; --ink-2:#3a3a32; --muted:#6c6b61; --faint:#9d9b8f;
  --line:#e7e5db; --line-strong:#d8d6ca;
  --active:#137244; --active-bg:#e6f1ea; --active-brd:#bfe0cd;
  --stale:#8a6410; --stale-bg:#f4ecd1; --stale-brd:#e2d29a;
  --dead:#9f382f; --dead-bg:#f1e1de; --dead-brd:#e3c4bf;
  --link:#2a55b8; --met:#137244; --unknown:#8a6410;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
  --sans:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}
a{color:inherit}
.wrap{max-width:1080px;margin:0 auto;padding:0 24px}

/* masthead */
.mast{border-bottom:1px solid var(--line-strong);background:var(--paper);position:sticky;top:0;z-index:30}
.mast .in{display:flex;align-items:center;justify-content:space-between;height:56px;gap:12px}
.bm{font-family:var(--mono);font-size:.9rem;font-weight:600;letter-spacing:-.01em;white-space:nowrap;text-decoration:none}
.bm .sub{color:var(--muted);font-weight:400}
.mnav{display:flex;gap:20px;font-family:var(--mono);font-size:.78rem;color:var(--muted)}
.mnav a{text-decoration:none}
.mnav a:hover{color:var(--ink)}
.mnav a.on{color:var(--ink);border-bottom:2px solid var(--ink);padding-bottom:2px}

/* hero */
.hero{max-width:680px;padding:55px 0 50px}
.hero h1{font-size:clamp(2rem,4vw,2.9rem);font-weight:700;letter-spacing:-.025em;line-height:1.1}
.hero h1 em{font-style:normal;background:linear-gradient(transparent 60%,#cbe8d6 60%);padding:0 .04em}
.hero .tagline{font-size:1.12rem;color:var(--muted);margin-top:18px;line-height:1.55;max-width:52ch}
.hero-match{display:flex;gap:10px;margin-top:30px;max-width:540px}
.hero-match input{flex:1;padding:15px 17px;font-family:var(--mono);font-size:.95rem;border:1px solid var(--line-strong);
  border-radius:8px;background:var(--card);color:var(--ink)}
.hero-match input:focus{outline:none;border-color:var(--ink);box-shadow:0 0 0 3px rgba(0,0,0,.05)}
.hero-match input::placeholder{color:var(--faint)}
.hero-match button{padding:0 22px;font-family:var(--sans);font-weight:600;font-size:.95rem;border:none;border-radius:8px;
  background:var(--ink);color:var(--card);cursor:pointer;white-space:nowrap}
.hero-match button:hover{background:#000}
.hero-match button:disabled{opacity:.55;cursor:wait}
.browse{display:inline-block;margin-top:20px;font-family:var(--mono);font-size:.82rem;color:var(--muted);text-decoration:none}
.browse:hover{color:var(--ink)}
#match-status{font-family:var(--mono);font-size:.82rem;color:var(--muted);margin-top:14px;min-height:1em}

/* page heading (category / sponsors / 404) */
.crumbs{font-family:var(--mono);font-size:.78rem;color:var(--muted);padding:26px 0 0}
.crumbs a{color:var(--link);text-decoration:none}
.crumbs a:hover{text-decoration:underline}
.pagehead{padding:20px 0 8px;max-width:64ch}
.pagehead h1{font-size:clamp(1.7rem,3.4vw,2.4rem);font-weight:700;letter-spacing:-.02em;line-height:1.12}
.pagehead .sub{font-size:1.05rem;color:var(--muted);margin-top:14px;line-height:1.5}
.pagehead .sub a{color:var(--link);text-decoration:none}
.pagehead .sub a:hover{text-decoration:underline}
.catlinks a{color:var(--link);text-decoration:none}.catlinks a:hover{text-decoration:underline}
.note{border-left:3px solid var(--stale-brd);background:#faf7ee;padding:12px 16px;margin:18px 0;
  color:var(--ink-2);font-size:.92rem;border-radius:0 4px 4px 0}
.note strong{color:var(--ink)}
.pnote{color:var(--muted);font-size:.9rem;margin:22px 0}
.pnote a{color:var(--link);text-decoration:none}.pnote a:hover{text-decoration:underline}

/* directory header + filter */
#directory{scroll-margin-top:70px}
.dir-top{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;
  border-top:1px solid var(--line-strong);padding-top:30px}
.dir-top h2{font-size:1.4rem;font-weight:700;letter-spacing:-.01em}
.searchbar{flex:1;min-width:220px;max-width:360px;padding:10px 14px;font-family:var(--mono);font-size:.86rem;
  border:1px solid var(--line-strong);border-radius:6px;background:var(--card);color:var(--ink)}
.searchbar:focus{outline:none;border-color:var(--ink)}
.chips{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:18px}
.chips.collapsed .chip.extra{display:none}
.chip{font-family:var(--mono);font-size:.75rem;padding:.36rem .72rem;border:1px solid var(--line-strong);border-radius:999px;
  background:var(--card);color:var(--muted);cursor:pointer;transition:.12s}
.chip:hover{color:var(--ink);border-color:var(--faint)}
.chip.on{background:var(--ink);border-color:var(--ink);color:var(--card)}
.chip .c{opacity:.55;margin-left:.3rem}
.morechips{font-family:var(--mono);font-size:.74rem;color:var(--link);background:none;border:none;cursor:pointer;padding:.36rem .4rem}
.morechips:hover{text-decoration:underline}
.count{font-family:var(--mono);font-size:.76rem;color:var(--muted);margin:20px 0 4px}
.count b{color:var(--ink);font-weight:600}
.count .elig{color:var(--active)}

/* index rows */
.idx{border:1px solid var(--line-strong);border-radius:5px;overflow:hidden;background:var(--card);margin-top:8px}
.colhead,.row{display:grid;grid-template-columns:86px minmax(150px,1.1fr) 2fr 120px 150px 20px;gap:14px;align-items:center}
.colhead{padding:9px 16px;border-bottom:1px solid var(--line-strong);font-family:var(--mono);font-size:.66rem;
  letter-spacing:.09em;text-transform:uppercase;color:var(--faint);background:#faf9f5}
.colhead span{white-space:nowrap}
.rowwrap{border-bottom:1px solid var(--line)}
.rowwrap:last-child{border-bottom:none}
.row{padding:12px 16px;cursor:pointer;transition:.1s}
.row:hover{background:#faf9f5}
.row:focus{outline:none;background:#f6f4ee}
.ix{font-family:var(--mono);font-size:.74rem;color:var(--faint)}
.co .name{font-weight:600;font-size:1rem}
.co .rtags{display:block;margin-top:2px}
.rtags .tag{font-family:var(--mono);font-size:.64rem;color:var(--muted);border:1px solid var(--line-strong);
  border-radius:2px;padding:1px 5px;margin-right:3px;white-space:nowrap;text-decoration:none;display:inline-block}
.rtags .tag:hover{color:var(--ink)}
.sum{color:var(--ink-2);font-size:.9rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rstatus{justify-self:start}
.rver{font-family:var(--mono);font-size:.72rem;color:var(--muted);white-space:nowrap}
.chev{font-family:var(--mono);color:var(--faint);text-align:center;transition:.15s}
.rowwrap.open .chev{transform:rotate(90deg);color:var(--ink)}
.rowwrap.open .row{background:#f6f4ee}
.detail{display:none;border-top:1px solid var(--line-strong);background:#fcfbf8}
.rowwrap.open .detail{display:block}
.eligbadge{display:none}
body.checked .rowwrap[data-elig=yes] .eligbadge{display:inline-flex;align-items:center;gap:5px;
  font-family:var(--mono);font-size:.66rem;color:var(--active);background:var(--active-bg);border:1px solid var(--active-brd);
  border-radius:3px;padding:1px 6px;margin-left:8px}
.empty{display:none;text-align:center;padding:60px 0;color:var(--muted);font-family:var(--mono);font-size:.85rem}

/* status + dots */
.status{display:inline-flex;align-items:center;gap:5px;font-family:var(--mono);font-size:.7rem;font-weight:500;
  padding:2px 8px;border-radius:3px;border:1px solid}
.status.a{color:var(--active);background:var(--active-bg);border-color:var(--active-brd)}
.status.s{color:var(--stale);background:var(--stale-bg);border-color:var(--stale-brd)}
.status.d{color:var(--dead);background:var(--dead-bg);border-color:var(--dead-brd)}
.dot{width:6px;height:6px;border-radius:50%;display:inline-block}
.dot.a{background:var(--active)}.dot.s{background:var(--stale)}.dot.d{background:var(--dead)}

/* record (standalone, for company/graveyard pages) + shared spec grid */
.rec{background:var(--card);border:1px solid var(--line-strong);border-radius:5px;margin-top:18px;overflow:hidden}
.rec.obsolete{background:#faf7f5}
.rec-hd{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 18px;
  border-bottom:1px solid var(--line);background:#fcfbf8}
.rec-hd .id{font-family:var(--mono);font-size:.78rem;color:var(--muted)}
.rec-hd .right{display:flex;align-items:center;gap:16px;font-family:var(--mono);font-size:.75rem}
.verified{color:var(--muted)}.verified b{color:var(--active);font-weight:500}
.rec-id{padding:16px 18px 4px;display:flex;justify-content:space-between;align-items:flex-start;gap:16px}
.rec-id h2{font-size:1.35rem;font-weight:700;letter-spacing:-.01em;line-height:1.1}
.rec-id h2 a{color:inherit;text-decoration:none}.rec-id h2 a:hover{color:var(--link)}
.rec-id .prod{font-family:var(--mono);font-size:.8rem;color:var(--muted);margin-top:4px}
.rec-id .tags{display:flex;gap:5px;flex-wrap:wrap;justify-content:flex-end;max-width:45%;margin:0}
.rec-id .tags .tag{font-family:var(--mono);font-size:.68rem;color:var(--ink-2);border:1px solid var(--line-strong);
  border-radius:3px;padding:2px 7px;white-space:nowrap;text-decoration:none}
.rec-id .tags .tag:hover{border-color:var(--faint)}
.obs-banner{font-family:var(--mono);font-size:.76rem;color:var(--dead);background:var(--dead-bg);
  border-top:1px solid var(--dead-brd);border-bottom:1px solid var(--dead-brd);padding:8px 18px}
.obs-banner b{font-weight:600}
.rec.obsolete .rec-id h2{color:var(--ink-2)}
.offer-label{font-family:var(--mono);font-size:.72rem;color:var(--muted);padding:12px 18px 0;text-transform:uppercase;letter-spacing:.06em}
.spec .r{display:grid;grid-template-columns:150px 1fr;gap:18px;padding:12px 18px;border-top:1px solid var(--line)}
.spec .k{font-family:var(--mono);font-size:.7rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);padding-top:2px}
.spec .v{color:var(--ink-2);font-size:.9rem;line-height:1.55}
.spec .v.prose{color:var(--ink)}
.spec .v code{font-family:var(--mono);font-size:.85em}
.applies{font-family:var(--mono);font-size:.82rem;color:var(--ink)}.applies .b{color:var(--muted)}
.reqs{display:flex;flex-wrap:wrap;gap:6px}
.req{display:inline-flex;align-items:center;gap:6px;font-family:var(--mono);font-size:.73rem;border:1px solid var(--line-strong);
  border-radius:3px;padding:3px 8px;color:var(--ink-2);background:#fbfaf7}
.req .mk{width:6px;height:6px;border-radius:1px;background:var(--faint)}
.req-none{font-family:var(--mono);font-size:.75rem;color:var(--faint)}
.reqs-note{font-family:var(--mono);font-size:.68rem;color:var(--faint);margin-top:7px}
body.checked .req[data-verdict=met]{border-color:var(--active-brd);background:var(--active-bg);color:var(--met)}
body.checked .req[data-verdict=met] .mk{background:var(--met)}
body.checked .req[data-verdict=met] .req-t::after{content:" \\2713";font-weight:600}
body.checked .req[data-verdict=unknown]{border-color:var(--stale-brd);background:var(--stale-bg);color:var(--unknown)}
body.checked .req[data-verdict=unknown] .mk{background:var(--unknown)}
body.checked .reqs-note{display:none}
.prov{font-family:var(--mono);font-size:.76rem;color:var(--muted);line-height:1.6}
.prov b{color:var(--ink-2);font-weight:500}
.prov .anchor{color:var(--ink-2);background:#f4f3ee;border:1px solid var(--line);border-radius:2px;padding:1px 5px}
.rec-ft{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:13px 18px;
  border-top:1px solid var(--line-strong);background:#faf9f5;flex-wrap:wrap}
.rec-ft .prog{font-family:var(--mono);font-size:.79rem;color:var(--link);text-decoration:none}
.rec-ft .prog:hover{text-decoration:underline}
.no-apply{font-family:var(--mono);font-size:.75rem;color:var(--faint)}

/* matcher report */
#match-report{margin-top:22px;max-width:760px}
#match-report .facts{font-family:var(--mono);font-size:.82rem;color:var(--ink-2);margin:0 0 10px}
#match-report .facts strong{color:var(--ink)}
#match-report h3{font-size:1rem;font-weight:700;margin:22px 0 8px}
#match-report .report-offer{border:1px solid var(--line-strong);border-radius:5px;background:var(--card);padding:14px 16px;margin-bottom:8px}
#match-report .report-offer p{margin:0 0 3px}
#match-report .report-offer a{color:var(--link);text-decoration:none}
#match-report .report-offer a:hover{text-decoration:underline}
#match-report .why{font-family:var(--mono);font-size:.76rem;color:var(--muted);margin:2px 0}
#match-report ul{margin:6px 0 0;padding-left:18px;font-size:.88rem}
#match-report li{margin:2px 0}
#match-report li a{color:var(--link);text-decoration:none}
#match-clear{font-family:var(--mono);background:none;border:1px solid var(--line-strong);color:var(--muted);
  border-radius:4px;padding:2px 8px;font-size:.72rem;cursor:pointer;margin-left:8px}
#match-clear:hover{border-color:var(--ink);color:var(--ink)}

/* sponsors */
.sp{border:1px solid var(--line-strong);background:var(--card);border-radius:5px;padding:12px 16px;margin-bottom:8px}
.sp summary{cursor:pointer;font-weight:600}
.sp summary a{color:inherit;text-decoration:none}.sp summary a:hover{color:var(--link)}
.sp summary .n{color:var(--muted);font-weight:400;font-size:.85rem;font-family:var(--mono)}
.sp ul{margin:10px 0 2px;padding-left:18px}
.sp li{font-size:.9rem;margin:3px 0}
.sp li a{color:var(--link);text-decoration:none}.sp li a:hover{text-decoration:underline}

/* footer */
.site-foot{border-top:1px solid var(--line-strong);margin-top:56px;padding:34px 0 60px;
  font-family:var(--mono);font-size:.78rem;color:var(--muted)}
.site-foot .fg{display:flex;justify-content:space-between;flex-wrap:wrap;gap:18px}
.site-foot a{color:var(--ink);text-decoration:none}
.site-foot a:hover{color:var(--link)}

@media(max-width:820px){
  .colhead{display:none}
  .row{grid-template-columns:1fr auto;grid-template-areas:"co status" "sum sum" "ver chev";gap:6px 10px}
  .ix{display:none}.co{grid-area:co}.sum{grid-area:sum;white-space:normal}
  .rstatus{grid-area:status;justify-self:end}.rver{grid-area:ver}.chev{grid-area:chev;justify-self:end}
  .mnav{display:none}.spec .r{grid-template-columns:1fr;gap:4px}
  .rec-id{flex-direction:column}.rec-id .tags{justify-content:flex-start;max-width:100%}
}
"""

INDEX_JS = """
(function () {
  const rows = [...document.querySelectorAll('.rowwrap')];
  const search = document.getElementById('search');
  const chips = [...document.querySelectorAll('.chip')];
  const count = document.getElementById('count');
  const empty = document.getElementById('empty');
  let cat = '';

  document.querySelectorAll('.row').forEach(r => {
    const w = r.closest('.rowwrap');
    r.addEventListener('click', e => { if (e.target.closest('a')) return; w.classList.toggle('open'); });
    r.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); w.classList.toggle('open'); }
    });
  });

  function apply() {
    const q = search ? search.value.trim().toLowerCase() : '';
    let shown = 0, elig = 0;
    for (const w of rows) {
      const okCat = !cat || w.dataset.cats.split(' ').includes(cat);
      const okQ = !q || w.dataset.search.includes(q);
      const vis = okCat && okQ;
      w.style.display = vis ? '' : 'none';
      if (vis) { shown++; if (w.dataset.elig === 'yes') elig++; }
    }
    if (empty) empty.style.display = shown ? 'none' : 'block';
    let base = '<b>' + shown + '</b> of ' + rows.length + ' records';
    if (document.body.classList.contains('checked'))
      base += ' &middot; <span class="elig">' + elig + ' your repo likely qualifies for</span>';
    if (count) count.innerHTML = base;
  }
  window.fosApply = apply;

  if (search) {
    search.addEventListener('input', apply);
    const q = new URLSearchParams(location.search).get('q');
    if (q) search.value = q;
  }
  chips.forEach(c => c.addEventListener('click', () => {
    chips.forEach(x => x.classList.remove('on'));
    c.classList.add('on'); cat = c.dataset.cat; apply();
  }));
  const more = document.getElementById('more'), chipbox = document.getElementById('chips');
  if (more) more.addEventListener('click', () => {
    const col = chipbox.classList.toggle('collapsed');
    more.textContent = col ? 'show all categories \\u2192' : 'show fewer \\u2190';
  });
  apply();
})();
"""

TRACK_JS = """
document.addEventListener('click', (e) => {
  const a = e.target.closest('a[data-track]');
  if (!a || typeof gtag !== 'function') return;
  gtag('event', a.dataset.track, {
    company: a.dataset.company,
    product: a.dataset.product || undefined,
    link_url: a.href,
  });
});
"""

# Client-side port of scripts/match.py. Reads rules.json + offers.json, gathers
# repo facts from the GitHub public API (no auth; ~60 req/h per visitor IP).
MATCHER_JS = r"""
(function () {
  const input = document.getElementById('repo-input');
  const btn = document.getElementById('match-btn');
  const status = document.getElementById('match-status');
  const report = document.getElementById('match-report');
  const directory = document.getElementById('directory');
  if (!input) return;

  let RULES = null, OFFERS = null;

  function parseRepo(text) {
    text = text.trim().replace(/\.git$/, '').replace(/\/+$/, '');
    let m = text.match(/github\.com\/([^\/\s]+)\/([^\/\s#?]+)/i);
    if (m) return m[1] + '/' + m[2];
    m = text.match(/^([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)$/);
    return m ? m[1] + '/' + m[2] : null;
  }

  async function gh(path) {
    const resp = await fetch('https://api.github.com' + path, {
      headers: { Accept: 'application/vnd.github+json' },
    });
    if (resp.status === 403 || resp.status === 429) throw new Error('rate');
    if (resp.status === 404) throw new Error('notfound');
    if (!resp.ok) throw new Error('api');
    return resp.json();
  }

  async function raw(repo, branch, path) {
    try {
      const resp = await fetch(
        'https://raw.githubusercontent.com/' + repo + '/' + branch + '/' + path);
      return resp.ok ? resp.text() : '';
    } catch (e) { return ''; }
  }

  function globToRe(pat) {
    return new RegExp('^' + pat.replace(/[.+^${}()|[\]\\]/g, '\\$&')
      .replace(/\*/g, '[^/]*').replace(/\?/g, '.') + '$');
  }

  function depsFromManifests(texts) {
    const deps = new Set();
    if (texts['package.json']) {
      try {
        const p = JSON.parse(texts['package.json']);
        for (const k of ['dependencies', 'devDependencies', 'optionalDependencies'])
          for (const d of Object.keys(p[k] || {})) deps.add(d.toLowerCase());
      } catch (e) {}
    }
    for (const f of ['requirements.txt', 'requirements-dev.txt']) {
      for (const line of (texts[f] || '').split('\n')) {
        const t = line.trim();
        if (t && !t.startsWith('#') && !t.startsWith('-'))
          deps.add(t.split(/[<>=\[~!;\s]/)[0].toLowerCase());
      }
    }
    if (texts['pyproject.toml'])
      for (const m of texts['pyproject.toml'].matchAll(/"([A-Za-z0-9_.-]+)\s*[<>=~!\[]/g))
        deps.add(m[1].toLowerCase());
    if (texts['Cargo.toml']) {
      let inDeps = false;
      for (const line of texts['Cargo.toml'].split('\n')) {
        if (/^\[.*dependencies.*\]/.test(line)) { inDeps = true; continue; }
        if (line.startsWith('[')) inDeps = false;
        if (inDeps) { const m = line.match(/^\s*([A-Za-z0-9_-]+)\s*=/); if (m) deps.add(m[1].toLowerCase()); }
      }
    }
    if (texts['go.mod'])
      for (const m of texts['go.mod'].matchAll(/^\t?([\w.\/-]+) v/gm))
        deps.add(m[1].split('/').pop().toLowerCase());
    if (texts['Gemfile'])
      for (const m of texts['Gemfile'].matchAll(/gem ["']([\w-]+)["']/g))
        deps.add(m[1].toLowerCase());
    return deps;
  }

  async function gatherFacts(repo) {
    status.textContent = 'Fetching repository info…';
    const meta = await gh('/repos/' + repo);
    const branch = meta.default_branch || 'main';
    status.textContent = 'Reading file tree…';
    const [langsResp, tree] = await Promise.all([
      gh('/repos/' + repo + '/languages').catch(() => ({})),
      gh('/repos/' + repo + '/git/trees/' + encodeURIComponent(branch) + '?recursive=1')
        .catch(() => ({ tree: [] })),
    ]);

    const files = [], basenames = new Set(), dirs = new Set();
    const skip = /(^|\/)(node_modules|vendor|dist|build|target|\.venv|venv|__pycache__|\.next|coverage|third[_-]party|deps)(\/|$)/;
    for (const e of tree.tree || []) {
      if (skip.test(e.path)) continue;
      if (e.type === 'tree') { dirs.add(e.path.split('/').pop().toLowerCase()); continue; }
      files.push(e.path);
      basenames.add(e.path.split('/').pop());
    }

    status.textContent = 'Reading manifests and CI config…';
    const manifestNames = ['package.json', 'pyproject.toml', 'Cargo.toml', 'go.mod',
      'Gemfile', 'requirements.txt', 'requirements-dev.txt'];
    const wanted = manifestNames.filter(n => basenames.has(n) && files.includes(n));
    const wfFiles = files.filter(f =>
      (f.startsWith('.github/workflows/') && /\.ya?ml$/.test(f)) ||
      ['.travis.yml', 'appveyor.yml', '.circleci/config.yml', '.cirrus.yml'].includes(f)
    ).slice(0, 12);

    const texts = {};
    await Promise.all(wanted.map(async n => { texts[n] = await raw(repo, branch, n); }));
    const wfTexts = await Promise.all(wfFiles.map(f => raw(repo, branch, f)));

    const langs = Object.entries(langsResp).sort((a, b) => b[1] - a[1])
      .slice(0, 4).map(e => e[0]);

    const flags = new Set();
    if (texts['package.json']) {
      try {
        const p = JSON.parse(texts['package.json']);
        const deps = new Set(Object.keys(Object.assign({}, p.dependencies, p.devDependencies)).map(d => d.toLowerCase()));
        if (!p.private && ['main', 'module', 'exports'].some(k => k in p) && !deps.has('electron'))
          flags.add('npm_published');
      } catch (e) {}
    }

    const spdx = meta.license && meta.license.spdx_id;
    return {
      name: meta.full_name,
      files, basenames, dirs, langs,
      deps: depsFromManifests(texts),
      workflowText: wfTexts.join('\n').toLowerCase(),
      license: (spdx && spdx !== 'NOASSERTION') ? spdx : null,
      createdAt: meta.created_at, pushedAt: meta.pushed_at,
      flags,
      truncated: !!tree.truncated,
    };
  }

  function signalHit(sig, facts) {
    if (sig.kind === 'dep') {
      for (const d of sig.any) if (facts.deps.has(d.toLowerCase())) return d;
    } else if (sig.kind === 'file') {
      for (const pat of sig.any) {
        if (pat.includes('/') || pat.includes('*')) {
          const re = globToRe(pat);
          const hit = facts.files.find(f => re.test(f));
          if (hit) return pat;
        } else if (facts.basenames.has(pat)) return pat;
      }
    } else if (sig.kind === 'dir') {
      for (const d of sig.any) if (facts.dirs.has(d.toLowerCase())) return d;
    } else if (sig.kind === 'workflow') {
      const m = facts.workflowText.match(new RegExp(sig.regex, 'i'));
      if (m) return m[0].trim().slice(0, 60);
    } else if (sig.kind === 'lang') {
      for (const l of sig.any) if (facts.langs.includes(l)) return l;
    } else if (sig.kind === 'flag') {
      for (const f of sig.any) if (facts.flags.has(f)) return f;
    }
    return null;
  }

  function eligibility(offer, facts) {
    const checks = [], e = offer.eligibility || {};
    let bad = false;
    if (e.osi_license_required) {
      checks.push(facts.license
        ? 'requires OSI license — detected ' + facts.license + ' ✓'
        : 'requires OSI license — none detected on GitHub, verify');
      }
    if (e.min_project_age_months && facts.createdAt) {
      const months = Math.floor((Date.now() - new Date(facts.createdAt)) / 2592000000);
      const ok = months >= e.min_project_age_months;
      checks.push('requires ≥' + e.min_project_age_months + ' months of history — ' +
        months + ' months ' + (ok ? '✓' : '✗'));
      if (!ok) bad = true;
    }
    if (e.non_commercial_only) checks.push('non-commercial projects only');
    if (e.active_development_required && facts.pushedAt) {
      const days = Math.floor((Date.now() - new Date(facts.pushedAt)) / 86400000);
      checks.push('requires active development — last push ' + days + 'd ago ' +
        (days < 90 ? '✓' : '✗'));
      if (days >= 90) bad = true;
    }
    return { checks, bad };
  }

  function h(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function offerLink(slug, company, product, url) {
    return '<a href="' + h(url) + '" target="_blank" rel="noopener nofollow" ' +
      'data-track="offer_click" data-company="' + h(company) + '" data-product="' + h(product) + '">' +
      h(product) + '</a>';
  }

  function runRules(facts) {
    const catOf = {};
    for (const doc of OFFERS) catOf[doc.slug] = doc.categories || [];
    const bySlug = {};
    for (const doc of OFFERS) bySlug[doc.slug] = doc;

    const covered = {};
    for (const rule of RULES.covered || []) {
      if (!signalHit(rule, facts)) continue;
      const targets = new Set(rule.companies || []);
      if (rule.category)
        for (const s in catOf) if (catOf[s].includes(rule.category)) targets.add(s);
      for (const s of targets) covered[s] = rule.tool;
    }

    const reasons = {};
    for (const sig of RULES.signals) {
      const match = signalHit(sig, facts);
      if (!match) continue;
      const reason = sig.reason.replace('{match}', match);
      const targets = new Set(sig.companies || []);
      if (sig.category)
        for (const s in catOf) if (catOf[s].includes(sig.category)) targets.add(s);
      for (const s of targets) {
        if (!bySlug[s]) continue;
        (reasons[s] = reasons[s] || []).includes(reason) || reasons[s].push(reason);
      }
    }

    const recommended = [], already = [], ineligible = [];
    const order = Object.keys(reasons).sort((a, b) => reasons[b].length - reasons[a].length);
    for (const slug of order) {
      const doc = bySlug[slug];
      for (const o of doc.offers) {
        if (o.status === 'discontinued') continue;
        const applies = (o.eligibility || {}).applies_to;
        if (applies === 'maintainer' || applies === 'contributors') continue;
        const { checks, bad } = eligibility(o, facts);
        const entry = { slug, company: doc.company, product: o.product,
          url: o.offer_url, what: o.what_you_get, reasons: reasons[slug], checks };
        if (covered[slug] && covered[slug] !== doc.company) {
          entry.tool = covered[slug]; already.push(entry);
        } else if (bad) ineligible.push(entry);
        else recommended.push(entry);
      }
    }
    return { recommended, already, ineligible };
  }

  function classifyTokens(facts) {
    const now = Date.now();
    document.querySelectorAll('.rowwrap .req').forEach(req => {
      const t = ((req.querySelector('.req-t') || req).textContent || '').toLowerCase();
      let v = 'unknown';
      if (t.includes('license')) v = facts.license ? 'met' : 'unknown';
      else if (t.includes('active')) v = (facts.pushedAt && (now - new Date(facts.pushedAt)) / 86400000 < 90) ? 'met' : 'unknown';
      else if (t.includes('day') || t.includes('month')) {
        const m = t.match(/(\d+)\s*(day|month)/);
        let ok = true;
        if (m && facts.createdAt) {
          const days = m[2][0] === 'm' ? (+m[1]) * 30 : (+m[1]);
          ok = (now - new Date(facts.createdAt)) / 86400000 >= days;
        }
        v = ok ? 'met' : 'unknown';
      } else if (t.includes('public')) v = 'met';
      req.dataset.verdict = v;
    });
  }

  function annotateRows(res) {
    const rec = new Set(res.recommended.map(e => e.slug));
    document.querySelectorAll('.rowwrap').forEach(w => {
      const name = w.querySelector('.co .name');
      if (rec.has(w.dataset.slug)) {
        w.dataset.elig = 'yes';
        if (name && !w.querySelector('.eligbadge')) {
          const b = document.createElement('span');
          b.className = 'eligbadge'; b.textContent = '✓ eligible';
          name.after(b);
        }
      } else { delete w.dataset.elig; }
    });
  }

  function resetAnnotations() {
    document.body.classList.remove('checked');
    document.querySelectorAll('.rowwrap').forEach(w => { delete w.dataset.elig; });
    document.querySelectorAll('.eligbadge').forEach(b => b.remove());
    document.querySelectorAll('.rowwrap .req').forEach(r => r.removeAttribute('data-verdict'));
    if (window.fosApply) window.fosApply();
  }

  function render(facts, res) {
    classifyTokens(facts);
    annotateRows(res);
    document.body.classList.add('checked');
    if (window.fosApply) window.fosApply();

    let out = '<p class="facts"><strong>' + h(facts.name) + '</strong> — ' +
      (facts.langs.join(', ') || 'n/a') + ' &middot; license: ' + (facts.license || 'not detected') +
      ' &middot; <strong>' + res.recommended.length + '</strong> offers matched ' +
      '<button id="match-clear">clear</button></p>';
    if (facts.truncated)
      out += '<p class="facts">note: repo tree was truncated; some signals may be missed</p>';

    out += '<h3>Recommended for this repo (' + res.recommended.length + ')</h3>';
    if (!res.recommended.length)
      out += '<p class="why">No signal-based matches — browse the full directory below; ' +
        'generic offers (IDEs, password managers, code signing) apply to most projects.</p>';

    const groups = new Map();
    for (const e of res.recommended) {
      const k = e.reasons.join('|');
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(e);
    }
    for (const [k, group] of groups) {
      if (group.length >= 4) {
        out += '<div class="report-offer"><p><strong>Alternatives — pick one (' +
          group.length + ')</strong></p>';
        for (const r of group[0].reasons) out += '<p class="why">why: ' + h(r) + '</p>';
        out += '<ul>' + group.map(e => '<li>' +
          offerLink(e.slug, e.company, e.product, e.url) +
          ' <a href="/company/' + h(e.slug) + '/">details</a></li>').join('') + '</ul></div>';
      } else {
        for (const e of group) {
          out += '<div class="report-offer"><p><strong>' + h(e.company) + '</strong> — ' +
            offerLink(e.slug, e.company, e.product, e.url) + '</p>';
          for (const r of e.reasons) out += '<p class="why">why: ' + h(r) + '</p>';
          for (const c of e.checks) out += '<p class="why">eligibility: ' + h(c) + '</p>';
          out += '<p class="why">' + h(e.what) + '</p></div>';
        }
      }
    }

    if (res.already.length) {
      out += '<h3>Already covered</h3><ul>' + res.already.map(e =>
        '<li>' + h(e.company) + ' — ' + h(e.product) +
        ' (you appear to use <strong>' + h(e.tool) + '</strong>)</li>').join('') + '</ul>';
    }
    if (res.ineligible.length) {
      out += '<h3>Matched but not (yet) eligible</h3><ul>' + res.ineligible.map(e =>
        '<li>' + h(e.company) + ' — ' + h(e.product) + ': ' +
        h(e.checks.join('; ')) + '</li>').join('') + '</ul>';
    }
    out += '<p class="facts">Requirement tokens in the directory below are now marked for ' +
      'this repo (✓ met / ? unknown). Eligible offers show a ✓ badge.</p>';
    report.innerHTML = out;
    document.getElementById('match-clear').addEventListener('click', () => {
      report.innerHTML = ''; status.textContent = ''; resetAnnotations();
      history.replaceState(null, '', location.pathname);
    });
  }

  async function match(repoText) {
    const repo = parseRepo(repoText);
    if (!repo) { status.textContent = 'Enter a GitHub repo URL or owner/name.'; return; }
    btn.disabled = true;
    report.innerHTML = '';
    try {
      if (!RULES) {
        status.textContent = 'Loading rules…';
        [RULES, OFFERS] = await Promise.all([
          fetch('/rules.json').then(r => r.json()),
          fetch('/offers.json').then(r => r.json()),
        ]);
      }
      const facts = await gatherFacts(repo);
      const res = runRules(facts);
      status.textContent = '';
      render(facts, res);
      history.replaceState(null, '', '#match=' + repo);
      if (typeof gtag === 'function')
        gtag('event', 'match_run', { repo: repo, matched: res.recommended.length });
    } catch (err) {
      status.textContent = err.message === 'notfound'
        ? 'Repository not found (is it public?).'
        : err.message === 'rate'
        ? 'GitHub API rate limit reached for your IP — try again in a few minutes.'
        : 'Could not analyze that repository. Try again?';
    } finally {
      btn.disabled = false;
    }
  }

  btn.addEventListener('click', () => match(input.value));
  input.addEventListener('keydown', e => { if (e.key === 'Enter') match(input.value); });
  document.querySelectorAll('.check-one').forEach(b => b.addEventListener('click', () => {
    const c = document.getElementById('check');
    if (c) c.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (input.value.trim()) match(input.value);
    else { status.textContent = 'Paste your repo above, then run the match.'; input.focus(); }
  }));
  const m = location.hash.match(/^#match=(.+)$/);
  if (m) { input.value = decodeURIComponent(m[1]); match(input.value); }
})();
"""


def json_ld_script(data: dict) -> str:
    return ('<script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False)
            + "</script>\n")


def breadcrumbs_json_ld(*crumbs: tuple[str, str]) -> str:
    """crumbs: (name, path) pairs, root first."""
    return json_ld_script({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": name,
             "item": f"{SITE_URL}{path}"}
            for i, (name, path) in enumerate(crumbs, 1)
        ],
    })


def page(*, title: str, description: str, canonical_path: str, body: str,
         extra_head: str = "", scripts: str = "") -> str:
    """Shared page shell: head with GA + SEO tags, body, tracking JS."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{SITE_URL}{canonical_path}">
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>&#127873;</text></svg>">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{SITE_URL}{canonical_path}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="foropensource">
<meta property="og:image" content="{SITE_URL}/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="foropensource — free products and services for open source">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{SITE_URL}/og.png">
<script async src="https://www.googletagmanager.com/gtag/js?id={GA_MEASUREMENT_ID}"></script>
<script>
window.dataLayer = window.dataLayer || [];
function gtag(){{dataLayer.push(arguments);}}
gtag('js', new Date());
gtag('config', '{GA_MEASUREMENT_ID}');
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
{extra_head}<style>{CSS}</style>
</head>
<body>
{MASTHEAD}
{body}
<footer class="site-foot"><div class="wrap fg">
  <span>foropensource — offers data <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a> · community-maintained · re-verified weekly</span>
  <span><a href="{REPO_URL}">GitHub</a> &middot; <a href="{REPO_URL}/issues/new?template=suggest-offer.yml">Suggest an offer</a> &middot; <a href="/offers.json">offers.json</a></span>
</div></footer>
<script>{TRACK_JS}</script>
{scripts}
</body>
</html>
"""


MASTHEAD = """<div class="mast"><div class="wrap in">
  <a class="bm" href="/">foropensource<span class="sub"> &middot; the open-source offer registry</span></a>
  <nav class="mnav">
    <a href="/">Directory</a><a href="/#check">Match a repo</a>
    <a href="/sponsors/">Sponsors</a><a href="{repo}">GitHub</a>
  </nav>
</div></div>""".format(repo=REPO_URL)


def _chips_html(docs: list[dict], visible: int = 7) -> tuple[str, int]:
    """Category filter chips with counts; those past `visible` are marked .extra."""
    counts: dict[str, int] = defaultdict(int)
    for d in docs:
        for c in d.get("categories") or []:
            counts[c] += 1
    cats_sorted = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    chips = [f'<button class="chip on" data-cat="">all <span class="c">{len(docs)}</span></button>']
    for i, (c, n) in enumerate(cats_sorted):
        extra = " extra" if i >= visible else ""
        chips.append(f'<button class="chip{extra}" data-cat="{esc(c)}">'
                     f'{esc(cat_label(c))} <span class="c">{n}</span></button>')
    return "".join(chips), len(counts)


def build_index(docs: list[dict], n_offers: int, all_cats: list[str],
                last_verified: str) -> str:
    chips_html, _ = _chips_html(docs)
    rows_html = "\n".join(render_row(d) for d in docs)
    body = f"""<div class="wrap"><div class="hero" id="check">
  <h1>See what your open-source project can get &mdash; <em>free</em>.</h1>
  <p class="tagline">{len(docs)} companies offer free products, credits, and grants to open
  source. Paste your repo and we&rsquo;ll show you the ones it qualifies for. Every offer
  re-checked weekly.</p>
  <div class="hero-match">
    <input id="repo-input" type="text" placeholder="github.com/you/project" spellcheck="false">
    <button id="match-btn">See what it qualifies for &rarr;</button>
  </div>
  <p id="match-status"></p>
  <div id="match-report"></div>
  <a class="browse" href="#directory">or browse all {len(docs)} records &darr;</a>
</div></div>

<div class="wrap" id="directory">
  <div class="dir-top">
    <h2>The directory</h2>
    <input class="searchbar" id="search" type="search" placeholder="Search company, product, category&hellip;">
  </div>
  <div class="chips collapsed" id="chips">{chips_html}<button class="morechips" id="more">show all categories &rarr;</button></div>
  <div class="count" id="count"></div>
  <div class="idx">
    <div class="colhead"><span>ID</span><span>Company</span><span>What you get</span><span>Status</span><span>Verified</span><span></span></div>
    {rows_html}
  </div>
  <div class="empty" id="empty">No records match those filters.</div>
  <p class="pnote">Latest verification pass: {esc(last_verified)}. See also
  <a href="/sponsors/">which companies sponsor the most open source projects</a>.</p>
</div>"""

    json_ld = json_ld_script({
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "@id": f"{SITE_URL}/#website",
                "url": f"{SITE_URL}/",
                "name": "foropensource",
                "description": "Verified free-for-open-source offers, re-checked weekly.",
                "potentialAction": {
                    "@type": "SearchAction",
                    "target": {
                        "@type": "EntryPoint",
                        "urlTemplate": f"{SITE_URL}/?q={{search_term_string}}",
                    },
                    "query-input": "required name=search_term_string",
                },
            },
            {
                "@type": "Dataset",
                "name": "foropensource offers dataset",
                "description": f"Verified free-for-open-source offers from {len(docs)} "
                "companies: what you get, eligibility, how to apply, and when each "
                "offer was last verified. Re-checked weekly.",
                "url": f"{SITE_URL}/",
                "keywords": ["open source", "free for open source", "developer tools",
                             "sponsorship", "OSS"],
                "creator": {"@type": "Organization", "name": "foropensource",
                            "url": f"{SITE_URL}/"},
                "license": "https://creativecommons.org/licenses/by/4.0/",
                "isAccessibleForFree": True,
                "dateModified": last_verified,
                "distribution": [
                    {"@type": "DataDownload", "encodingFormat": "text/csv",
                     "contentUrl": f"{SITE_URL}/offers.csv"},
                    {"@type": "DataDownload", "encodingFormat": "application/json",
                     "contentUrl": f"{SITE_URL}/offers.json"},
                ],
            },
        ],
    })
    return page(
        title="foropensource — free products and services for open source",
        description=clamp(
            f"{len(docs)} companies with {n_offers} verified free offers for open "
            "source projects: CI, hosting, monitoring, security, testing and more. "
            "Paste your repo to see what it qualifies for.", DESC_LIMIT),
        canonical_path="/",
        body=body,
        extra_head=json_ld,
        scripts=f"<script>{INDEX_JS}</script>\n<script>{MATCHER_JS}</script>",
    )


def build_company_page(doc: dict) -> str:
    company = doc["company"]
    cats = doc.get("categories") or []
    products = [o["product"] for o in doc["offers"]]
    n = len(doc["offers"])
    offers_word = "free offer" if n == 1 else "free offers"
    cat_links = ", ".join(
        f'<a href="/category/{esc(c)}/">{esc(cat_label(c))}</a>' for c in cats
    )
    verified = max((o.get("last_verified", "") for o in doc["offers"]), default="")
    body = f"""<div class="wrap">
<p class="crumbs"><a href="/">Directory</a> &rsaquo; {esc(company)}</p>
{render_record(doc)}
<p class="pnote">Verified {esc(verified)}. Details changed?
<a href="{REPO_URL}/blob/main/data/offers/{esc(doc['slug'])}.yaml">Fix it on GitHub</a>.
Not sure you qualify? <a href="/#check">Match your repo</a> against all
{esc(doc['total_offers'])} offers{f", or browse {cat_links}" if cat_links else ""}.</p>
</div>"""
    return page(
        title=fit_title(
            f"{company} free for open source — what you get and how to apply",
            f"{short_name(company)} free for open source — how to apply",
            f"{short_name(company)} free for open source",
        ),
        # Ordered so the trim eats boilerplate, not the offer or the date.
        description=clamp(
            f"{possessive(short_name(company))} {offers_word} for open source: "
            f"{clamp('; '.join(products), 60)}. Verified {verified} — what you "
            f"get, who qualifies, and how to apply.", DESC_LIMIT),
        canonical_path=f"/company/{doc['slug']}/",
        body=body,
        extra_head=breadcrumbs_json_ld(
            ("All offers", "/"), (company, f"/company/{doc['slug']}/")
        ),
    )


def build_discontinued_page(doc: dict, active_docs: list[dict]) -> str:
    """Page for a company whose free-for-OSS offers have all been discontinued.

    These answer "is X still free for open source?" searches and point to
    live alternatives, so they stay in the sitemap but not in the directory.
    """
    company = doc["company"]
    cats = doc.get("categories") or []
    products = [o["product"] for o in doc["offers"]]
    verified = max((o.get("last_verified", "") for o in doc["offers"]), default="")

    alt_docs = [d for d in active_docs if set(d.get("categories") or []) & set(cats)]
    if alt_docs:
        items = "".join(render_row(d, with_check=False) for d in alt_docs[:8])
        cat_links = ", ".join(
            f'<a href="/category/{esc(c)}/">all free {esc(cat_label(c))} offers</a>'
            for c in cats
        )
        alt_html = f"""<div class="dir-top" style="border-top:none;padding-top:34px">
  <h2>Still-active alternatives</h2></div>
<div class="idx">{items}</div>
<p class="pnote">Browse {cat_links}, or <a href="/#check">match your repo</a> against every
current offer.</p>"""
    else:
        alt_html = ('<p class="pnote"><a href="/">Browse the directory</a> for current offers, '
                    'or <a href="/#check">match your repo</a>.</p>')

    body = f"""<div class="wrap">
<p class="crumbs"><a href="/">Directory</a> &rsaquo; {esc(company)}</p>
<div class="pagehead">
  <h1>Is {esc(company)} still free for open source? No.</h1>
  <div class="note">{esc(company)}&rsquo;s free-for-open-source
  {"offer has" if len(products) == 1 else "offers have"} been discontinued
  (last checked {esc(verified)}). The record below is kept for reference.</div>
</div>
{render_record(doc, discontinued=True)}
{alt_html}
<p class="pnote">Know of a new {esc(company)} offer for open source?
<a href="{REPO_URL}/blob/main/data/offers/{esc(doc['slug'])}.yaml">Update it on GitHub</a>.</p>
</div>"""
    return page(
        title=fit_title(
            f"Is {company} still free for open source? Discontinued — and alternatives",
            f"Is {company} still free for open source? Discontinued",
            f"Is {short_name(company)} still free for open source?",
        ),
        description=clamp(
            f"{possessive(short_name(company))} free offer for open source has "
            f"been discontinued, last checked {verified}. What it was, and the "
            f"current alternatives.", DESC_LIMIT),
        canonical_path=f"/company/{doc['slug']}/",
        body=body,
        extra_head=breadcrumbs_json_ld(
            ("All offers", "/"), (company, f"/company/{doc['slug']}/")
        ),
        scripts=f"<script>{INDEX_JS}</script>",
    )


def build_category_page(cat: str, docs: list[dict], total_companies: int) -> str:
    label = cat_label(cat)
    n_offers = sum(len(d["offers"]) for d in docs)
    names = ", ".join(d["company"] for d in docs[:6])
    rows = "\n".join(render_row(d, with_check=False) for d in docs)
    title_label = label if label == "CI/CD" or label[0].isupper() else label.capitalize()
    body = f"""<div class="wrap">
<p class="crumbs"><a href="/">Directory</a> &rsaquo; {esc(title_label)}</p>
<div class="pagehead">
  <h1>Free {esc(label)} for open source projects</h1>
  <p class="sub">{n_companies(len(docs))}, {n_offers} verified offers, re-checked weekly.
  Not sure which you qualify for? <a href="/#check">Match your repo</a>.</p>
</div>
<div class="dir-top" style="border-top:none;padding-top:8px">
  <h2>{esc(title_label)} &mdash; {len(docs)} companies</h2>
  <input class="searchbar" id="search" type="search" placeholder="Search within {esc(label)}&hellip;">
</div>
<div class="count" id="count"></div>
<div class="idx">
  <div class="colhead"><span>ID</span><span>Company</span><span>What you get</span><span>Status</span><span>Verified</span><span></span></div>
  {rows}
</div>
<div class="empty" id="empty">No records match.</div>
<p class="pnote"><a href="/">Browse all {total_companies} companies</a> in the directory.</p>
</div>"""
    return page(
        title=fit_title(
            f"Free {label} for open source projects — {n_offers} verified offers",
            f"Free {label} for open source — {n_offers} verified offers",
            f"Free {label} for open source",
        ),
        description=clamp(
            f"{n_offers} verified free {label} offers for open source projects, "
            f"from {names} and more. What you get and how to apply.", DESC_LIMIT),
        canonical_path=f"/category/{cat}/",
        body=body,
        extra_head=breadcrumbs_json_ld(
            ("All offers", "/"), (title_label, f"/category/{cat}/")
        ) + json_ld_script({
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": f"Free {label} for open source projects",
            "numberOfItems": len(docs),
            "itemListElement": [
                {"@type": "ListItem", "position": i, "name": d["company"],
                 "url": f"{SITE_URL}/company/{d['slug']}/"}
                for i, d in enumerate(docs, 1)
            ],
        }),
        scripts=f"<script>{INDEX_JS}</script>",
    )


def build_sponsors_page(docs: list[dict]) -> str:
    """League table from company-sponsorships.csv."""
    slug_by_name = {d["company"].lower(): d["slug"] for d in docs}
    counts: dict[str, list[dict]] = defaultdict(list)
    dollars: dict[str, float] = defaultdict(float)
    with SPONSORSHIPS_CSV.open() as f:
        for row in csv.DictReader(f):
            counts[row["company"]].append(row)
            if row["oc_total_donated_usd"]:
                try:
                    dollars[row["company"]] += float(row["oc_total_donated_usd"])
                except ValueError:
                    pass

    ranked = sorted(counts.items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))
    n_total = sum(len(v) for v in counts.values())

    entries = []
    for rank, (company, rows) in enumerate(ranked, 1):
        slug = slug_by_name.get(company.lower())
        name_html = (
            f'<a href="/company/{esc(slug)}/">{esc(company)}</a>' if slug else esc(company)
        )
        usd = f" &middot; ${dollars[company]:,.0f} via Open Collective" if dollars[company] else ""
        targets = "".join(
            f'<li><a href="{esc(r["target_url"])}" target="_blank" rel="noopener nofollow">'
            f"{esc(r['target_name'] or r['target'])}</a>"
            + (f" ({esc(r['matched_catalogue_project'])})" if r["matched_catalogue_project"]
               and r["matched_catalogue_project"] != (r["target_name"] or r["target"]) else "")
            + "</li>"
            for r in rows
        )
        entries.append(f"""<details class="sp" id="{esc(company.lower().replace(' ', '-'))}">
  <summary>#{rank} {name_html} <span class="n">&mdash; {len(rows)} sponsored{esc(usd)}</span></summary>
  <ul>{targets}</ul>
</details>""")

    body = f"""<div class="wrap">
<p class="crumbs"><a href="/">Directory</a> &rsaquo; Sponsors</p>
<div class="pagehead">
  <h1>Which companies sponsor the most open source projects?</h1>
  <p class="sub">{len(ranked)} companies with {n_total} publicly visible sponsorships of
  open source projects and maintainers, counted from GitHub Sponsors and Open
  Collective. Expand a company to see who they sponsor.</p>
</div>
<div class="note"><strong>What this measures:</strong> breadth, not dollars.
GitHub Sponsors hides amounts, so a company sponsoring five projects at $10,000
each ranks below one sponsoring fifty at $10. It also excludes support that
doesn&rsquo;t flow through these platforms: direct grants, foundation memberships,
employing maintainers, and free products
(<a href="/">tracked separately in the offers directory</a>).</div>
<div style="margin-top:20px">{''.join(entries)}</div>
<p class="pnote">Data: <a href="{REPO_URL}/blob/main/data/exports/company-sponsorships.csv">company-sponsorships.csv</a>
(CC BY 4.0). Missing a company&rsquo;s sponsorships? <a href="{REPO_URL}">Open a pull request</a>.</p>
</div>"""
    return page(
        title="Which companies sponsor the most open source projects?",
        description=clamp(
            f"League table of {len(ranked)} companies by publicly visible open "
            f"source sponsorships on GitHub Sponsors and Open Collective — "
            f"{n_total} sponsorships counted.", DESC_LIMIT),
        canonical_path="/sponsors/",
        body=body,
    )


def build_404() -> str:
    body = f"""<div class="wrap">
<div class="pagehead">
  <h1>Page not found</h1>
  <p class="sub">Company records live at <code>/company/&lt;name&gt;/</code> and categories
  at <code>/category/&lt;name&gt;/</code>. <a href="/">Browse the directory</a> or
  <a href="/#check">match your repo</a> to see what it qualifies for.</p>
</div>
</div>
<script>
gtag('event', 'page_not_found', {{
  missing_path: location.pathname + location.search,
  referrer: document.referrer || '(none)'
}});
</script>"""
    return page(
        title="Page not found — foropensource",
        description="Page not found.",
        canonical_path="/404.html",
        body=body,
        extra_head='<meta name="robots" content="noindex">\n',
    )


def write_offers_csv(all_docs: list[dict], out_path: Path) -> None:
    cols = ["company", "website", "categories", "product", "offer_url",
            "what_you_get", "eligibility", "how_to_apply", "status",
            "last_verified", "page_url"]
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for doc in all_docs:
            for o in doc.get("offers") or []:
                w.writerow([
                    doc["company"], doc.get("website", ""),
                    "|".join(doc.get("categories") or []),
                    o.get("product", ""), o.get("offer_url", ""),
                    o.get("what_you_get", "").strip(),
                    eligibility_line(o.get("eligibility") or {}),
                    o.get("how_to_apply", "").strip(),
                    o.get("status", "active"), o.get("last_verified", ""),
                    f"{SITE_URL}/company/{doc['slug']}/",
                ])


def build_llms_txt(docs: list[dict], dead_docs: list[dict], n_offers: int,
                   all_cats: list[str], last_verified: str) -> str:
    lines = [
        "# foropensource",
        "",
        f"> {len(docs)} companies with {n_offers} verified free offers for open "
        "source projects and maintainers: CI, hosting, monitoring, security, "
        "testing, IDEs, and more. Every offer is automatically re-verified weekly "
        f"(latest pass: {last_verified}). Data is CC BY 4.0.",
        "",
        f"Machine-readable data: [offers.csv]({SITE_URL}/offers.csv) and "
        f"[offers.json]({SITE_URL}/offers.json) (JSON includes discontinued "
        f"offers). Full offer text: [llms-full.txt]({SITE_URL}/llms-full.txt). "
        f"Source data (YAML): [{REPO_URL}]({REPO_URL}).",
        "",
        "## Categories",
        "",
    ]
    for c in all_cats:
        n = sum(1 for d in docs if c in (d.get("categories") or []))
        lines.append(f"- [Free {cat_label(c)} for open source]"
                     f"({SITE_URL}/category/{c}/): {n_companies(n)}")
    lines += ["", "## Companies", ""]
    for d in docs:
        products = "; ".join(o["product"] for o in d["offers"])
        lines.append(f"- [{d['company']}]({SITE_URL}/company/{d['slug']}/): {products}")
    if dead_docs:
        lines += ["", "## Discontinued offers", ""]
        for d in dead_docs:
            lines.append(f"- [{d['company']}]({SITE_URL}/company/{d['slug']}/): "
                         "discontinued; page lists current alternatives")
    lines += [
        "",
        "## Other pages",
        "",
        f"- [Which companies sponsor the most open source projects?]"
        f"({SITE_URL}/sponsors/): league table from GitHub Sponsors and "
        "Open Collective data",
        "",
    ]
    return "\n".join(lines)


def build_llms_full_txt(docs: list[dict], n_offers: int, last_verified: str) -> str:
    lines = [
        "# foropensource — all verified free-for-open-source offers",
        "",
        f"> {len(docs)} companies, {n_offers} offers. Latest verification pass: "
        f"{last_verified}. Data CC BY 4.0, source: {REPO_URL}",
        "",
    ]
    for d in docs:
        cats = ", ".join(cat_label(c) for c in (d.get("categories") or []))
        lines += [f"## {d['company']}", "",
                  f"Website: {d.get('website', '')}",
                  f"Categories: {cats}",
                  f"Details: {SITE_URL}/company/{d['slug']}/", ""]
        for o in d["offers"]:
            lines += [f"### {o['product']}", "",
                      f"What you get: {o.get('what_you_get', '').strip()}"]
            elig = eligibility_line(o.get("eligibility") or {})
            if elig:
                lines.append(f"Eligibility: {elig}")
            lines += [f"How to apply: {o.get('how_to_apply', '').strip()}",
                      f"Offer URL: {o.get('offer_url', '')}",
                      f"Last verified: {o.get('last_verified', '')}", ""]
    return "\n".join(lines)


def main() -> int:
    docs, dead_docs = [], []
    for path in sorted(OFFERS_DIR.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text())
        if not doc:
            continue
        doc["slug"] = path.stem
        # Discontinued offers stay in the dataset; companies with at least one
        # active offer render normally, all-discontinued companies get a
        # "graveyard" page with alternatives.
        active = [o for o in doc["offers"] if o.get("status") != "discontinued"]
        if active:
            doc = dict(doc, offers=active)
            docs.append(doc)
        else:
            dead_docs.append(doc)
    docs.sort(key=lambda d: d["company"].lower())
    dead_docs.sort(key=lambda d: d["company"].lower())

    # Stable registry IDs across active + graveyard, by company name.
    for i, d in enumerate(sorted(docs + dead_docs, key=lambda d: d["company"].lower()), 1):
        d["fos_id"] = f"FOS-{i:04d}"

    n_offers = sum(len(d["offers"]) for d in docs)
    for d in docs:
        d["total_offers"] = n_offers
    all_cats = sorted({c for d in docs for c in (d.get("categories") or [])})
    last_verified = max(
        (o.get("last_verified", "") for d in docs for o in d["offers"]), default=""
    )

    def doc_lastmod(d: dict) -> str:
        return max((o.get("last_verified", "") for o in d["offers"]),
                   default="") or last_verified

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "index.html").write_text(build_index(docs, n_offers, all_cats, last_verified))

    urls = [("/", last_verified)]
    for d in docs:
        out = OUT_DIR / "company" / d["slug"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "index.html").write_text(build_company_page(d))
        urls.append((f"/company/{d['slug']}/", doc_lastmod(d)))
    for d in dead_docs:
        out = OUT_DIR / "company" / d["slug"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "index.html").write_text(build_discontinued_page(d, docs))
        urls.append((f"/company/{d['slug']}/", doc_lastmod(d)))
    for cat in all_cats:
        cat_docs = [d for d in docs if cat in (d.get("categories") or [])]
        out = OUT_DIR / "category" / cat
        out.mkdir(parents=True, exist_ok=True)
        (out / "index.html").write_text(build_category_page(cat, cat_docs, len(docs)))
        urls.append((f"/category/{cat}/",
                     max(doc_lastmod(d) for d in cat_docs)))
    if SPONSORSHIPS_CSV.is_file():
        out = OUT_DIR / "sponsors"
        out.mkdir(parents=True, exist_ok=True)
        (out / "index.html").write_text(build_sponsors_page(docs))
        urls.append(("/sponsors/", last_verified))

    (OUT_DIR / "CNAME").write_text("foropensource.com\n")
    (OUT_DIR / "404.html").write_text(build_404())
    og_src = ROOT / "assets" / "og.png"
    if og_src.is_file():
        (OUT_DIR / "og.png").write_bytes(og_src.read_bytes())

    # Machine-readable exports. offers.json includes discontinued offers and slugs.
    all_docs = []
    for p in sorted(OFFERS_DIR.glob("*.yaml")):
        d = yaml.safe_load(p.read_text())
        if d:
            d["slug"] = p.stem
            all_docs.append(d)
    (OUT_DIR / "offers.json").write_text(json.dumps(all_docs, indent=1))
    write_offers_csv(all_docs, OUT_DIR / "offers.csv")
    (OUT_DIR / "llms.txt").write_text(
        build_llms_txt(docs, dead_docs, n_offers, all_cats, last_verified))
    (OUT_DIR / "llms-full.txt").write_text(
        build_llms_full_txt(docs, n_offers, last_verified))
    rules = yaml.safe_load(RULES_PATH.read_text())
    (OUT_DIR / "rules.json").write_text(json.dumps(rules, indent=1))
    (OUT_DIR / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n"
    )
    url_entries = "\n".join(
        f"  <url><loc>{SITE_URL}{u}</loc><lastmod>{mod}</lastmod></url>"
        for u, mod in urls
    )
    (OUT_DIR / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{url_entries}\n</urlset>\n"
    )
    print(f"Wrote _site: {len(docs)} companies ({len(dead_docs)} discontinued), "
          f"{n_offers} offers, {len(urls)} pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
