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
import sys
from collections import defaultdict
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


def render_offer(offer: dict, company: str) -> str:
    status = offer.get("status", "active")
    badge = ""
    if status != "active":
        badge = f' <span class="badge badge-{esc(status)}">{esc(status)}</span>'
    elig = eligibility_line(offer.get("eligibility") or {})
    parts = [
        '<div class="offer">',
        f'<p class="offer-title"><a href="{esc(offer["offer_url"])}" target="_blank" rel="noopener nofollow" '
        f'data-track="offer_click" data-company="{esc(company)}" data-product="{esc(offer["product"])}">'
        f'{esc(offer["product"])}</a>{badge}</p>',
        f'<p class="offer-what">{esc(offer["what_you_get"])}</p>',
    ]
    if elig:
        parts.append(f'<p class="offer-meta">Eligibility: {esc(elig)}</p>')
    parts.append(
        f'<p class="offer-meta">How to apply: {esc(offer["how_to_apply"])}</p>'
    )
    verified = offer.get("last_verified", "")
    if verified:
        parts.append(f'<p class="offer-verified">last verified {esc(verified)}</p>')
    parts.append("</div>")
    return "\n".join(parts)


def render_company_card(doc: dict, link_heading: bool = True) -> str:
    slug = doc["slug"]
    cats = doc.get("categories") or []
    tags = "".join(
        f'<a class="tag" href="/category/{esc(c)}/">{esc(cat_label(c))}</a>' for c in cats
    )
    offers_html = "\n".join(render_offer(o, doc["company"]) for o in doc["offers"])
    search_blob = " ".join(
        [doc["company"]]
        + cats
        + [o.get("product", "") + " " + o.get("what_you_get", "") for o in doc["offers"]]
    ).lower()
    if link_heading:
        heading = f'<a href="/company/{esc(slug)}/">{esc(doc["company"])}</a>'
    else:
        heading = (
            f'<a href="{esc(doc["website"])}" target="_blank" rel="noopener nofollow" '
            f'data-track="company_click" data-company="{esc(doc["company"])}">{esc(doc["company"])}</a>'
        )
    return f"""
<article class="company" id="{esc(slug)}" data-search="{esc(search_blob)}" data-categories="{esc(' '.join(cats))}">
  <h2>{heading}</h2>
  <p class="tags">{tags}</p>
  {offers_html}
</article>"""


CSS = """
:root { --bg: #ffffff; --fg: #1a1a1a; --muted: #6b6b6b; --line: #e4e4e4;
        --accent: #0b6e4f; --card: #fafafa; --tag-bg: #eef2ef; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #121212; --fg: #e8e8e8; --muted: #9a9a9a; --line: #2c2c2c;
          --accent: #5dc39a; --card: #1b1b1b; --tag-bg: #22302a; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
main { max-width: 44rem; margin: 0 auto; padding: 2rem 1rem 4rem; }
a { color: var(--accent); }
header h1 { font-size: 1.6rem; margin: 0 0 0.3rem; }
header h1 a { color: var(--fg); text-decoration: none; }
header p.sub { color: var(--muted); margin: 0 0 1.2rem; }
nav.top { margin: 0 0 1.4rem; font-size: 0.9rem; }
nav.top a { margin-right: 1rem; }
#search { width: 100%; padding: 0.55rem 0.8rem; font-size: 1rem;
  border: 1px solid var(--line); border-radius: 8px;
  background: var(--card); color: var(--fg); }
.cats { margin: 0.8rem 0 1.5rem; display: flex; flex-wrap: wrap; gap: 0.35rem; }
.cats button { border: 1px solid var(--line); background: var(--card); color: var(--fg);
  border-radius: 999px; padding: 0.15rem 0.7rem; font-size: 0.82rem; cursor: pointer; }
.cats button.on { background: var(--accent); border-color: var(--accent); color: var(--bg); }
.company { border: 1px solid var(--line); background: var(--card);
  border-radius: 10px; padding: 1rem 1.2rem; margin-bottom: 1rem; }
.company h2 { font-size: 1.15rem; margin: 0 0 0.2rem; }
.company h2 a { color: var(--fg); text-decoration: none; }
.company h2 a:hover { color: var(--accent); }
.tags { margin: 0 0 0.6rem; }
.tag { display: inline-block; background: var(--tag-bg); color: var(--muted);
  border-radius: 4px; padding: 0.05rem 0.45rem; font-size: 0.75rem;
  margin-right: 0.3rem; text-decoration: none; }
.tag:hover { color: var(--accent); }
.offer { border-top: 1px solid var(--line); padding-top: 0.7rem; margin-top: 0.7rem; }
.offer-title { margin: 0 0 0.25rem; font-weight: 600; }
.offer-what { margin: 0 0 0.35rem; }
.offer-meta { margin: 0 0 0.25rem; color: var(--muted); font-size: 0.88rem; }
.offer-verified { margin: 0; color: var(--muted); font-size: 0.78rem; }
.badge { font-size: 0.72rem; padding: 0.05rem 0.4rem; border-radius: 4px;
  vertical-align: middle; font-weight: 400; }
.badge-stale { background: #f5e9c8; color: #7a5d00; }
.badge-discontinued { background: #f3d6d6; color: #8a2626; }
@media (prefers-color-scheme: dark) {
  .badge-stale { background: #3d3416; color: #d9b84a; }
  .badge-discontinued { background: #3d1f1f; color: #d98a8a; }
}
#count { color: var(--muted); font-size: 0.88rem; margin: 0 0 1rem; }
footer { margin-top: 3rem; color: var(--muted); font-size: 0.85rem;
  border-top: 1px solid var(--line); padding-top: 1rem; }
.crumbs { font-size: 0.85rem; color: var(--muted); margin: 0 0 1rem; }

/* matcher */
#matcher { border: 1px solid var(--accent); background: var(--card);
  border-radius: 10px; padding: 1rem 1.2rem; margin: 0 0 1.6rem; }
#matcher h2 { margin: 0 0 0.3rem; font-size: 1.1rem; }
#matcher p { margin: 0 0 0.6rem; color: var(--muted); font-size: 0.9rem; }
.matcher-row { display: flex; gap: 0.5rem; }
#repo-input { flex: 1; padding: 0.5rem 0.8rem; font-size: 1rem;
  border: 1px solid var(--line); border-radius: 8px;
  background: var(--bg); color: var(--fg); }
#match-btn { padding: 0.5rem 1rem; font-size: 1rem; border: none; border-radius: 8px;
  background: var(--accent); color: var(--bg); cursor: pointer; font-weight: 600; }
#match-btn:disabled { opacity: 0.6; cursor: wait; }
#match-status { margin-top: 0.6rem; font-size: 0.88rem; color: var(--muted); }
#match-report { margin-top: 0.4rem; }
#match-report h3 { font-size: 1.05rem; margin: 1.2rem 0 0.5rem; }
#match-report .facts { color: var(--muted); font-size: 0.88rem; }
.why { color: var(--muted); font-size: 0.88rem; margin: 0.1rem 0; }
.report-offer { border-top: 1px solid var(--line); padding: 0.6rem 0; }
#match-clear { background: none; border: 1px solid var(--line); color: var(--muted);
  border-radius: 6px; padding: 0.15rem 0.6rem; font-size: 0.82rem; cursor: pointer; }

/* sponsors table */
.sp { border: 1px solid var(--line); background: var(--card); border-radius: 10px;
  padding: 0.7rem 1.1rem; margin-bottom: 0.6rem; }
.sp summary { cursor: pointer; font-weight: 600; }
.sp summary .n { color: var(--muted); font-weight: 400; font-size: 0.9rem; }
.sp ul { margin: 0.6rem 0 0.3rem; padding-left: 1.2rem; }
.sp li { font-size: 0.9rem; margin: 0.15rem 0; }
.note { border-left: 3px solid var(--accent); padding: 0.1rem 0 0.1rem 0.9rem;
  color: var(--muted); font-size: 0.92rem; }
"""

INDEX_JS = """
const search = document.getElementById('search');
const buttons = [...document.querySelectorAll('.cats button')];
const cards = [...document.querySelectorAll('.company')];
const count = document.getElementById('count');
let activeCat = null;

function apply() {
  const q = search.value.trim().toLowerCase();
  let shown = 0;
  for (const card of cards) {
    const okQ = !q || card.dataset.search.includes(q);
    const okC = !activeCat || card.dataset.categories.split(' ').includes(activeCat);
    const show = okQ && okC;
    card.style.display = show ? '' : 'none';
    if (show) shown++;
  }
  count.textContent = shown + ' of ' + cards.length + ' companies';
}

search.addEventListener('input', apply);
const q = new URLSearchParams(location.search).get('q');
if (q) search.value = q;
for (const btn of buttons) {
  btn.addEventListener('click', () => {
    activeCat = activeCat === btn.dataset.cat ? null : btn.dataset.cat;
    buttons.forEach(b => b.classList.toggle('on', b.dataset.cat === activeCat));
    apply();
  });
}
apply();
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

  function render(facts, res) {
    let out = '<p class="facts"><strong>' + h(facts.name) + '</strong> — ' +
      (facts.langs.join(', ') || 'n/a') + ' · license: ' + (facts.license || 'not detected') +
      ' · ' + res.recommended.length + ' offers matched ' +
      '<button id="match-clear">clear</button></p>';
    if (facts.truncated)
      out += '<p class="facts">note: repo tree was truncated; some signals may be missed</p>';

    out += '<h3>Recommended (' + res.recommended.length + ')</h3>';
    if (!res.recommended.length)
      out += '<p>No signal-based matches — browse the full directory below; ' +
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
    out += '<p class="facts">Personal-tool offers for maintainers (IDEs, password ' +
      'managers, …) are in the <a href="#directory">directory below</a>.</p>';
    report.innerHTML = out;
    document.getElementById('match-clear').addEventListener('click', () => {
      report.innerHTML = ''; status.textContent = '';
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
{extra_head}<style>{CSS}</style>
</head>
<body>
<main>
{body}
<footer>
  <p>Offers data is <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>.
  Community-maintained: <a href="{REPO_URL}">github.com/natwar86/foropensource</a> &mdash;
  add a company or flag a dead offer with a pull request.</p>
</footer>
</main>
<script>{TRACK_JS}</script>
{scripts}
</body>
</html>
"""


NAV = """<nav class="top">
  <a href="/">All offers</a>
  <a href="/#matcher">Match your repo</a>
  <a href="/sponsors/">Top sponsors</a>
  <a href="{repo}">GitHub</a>
</nav>""".format(repo=REPO_URL)


def build_index(docs: list[dict], n_offers: int, all_cats: list[str],
                last_verified: str) -> str:
    cat_buttons = "".join(
        f'<button data-cat="{esc(c)}">{esc(cat_label(c))}</button>' for c in all_cats
    )
    companies_html = "\n".join(render_company_card(d) for d in docs)
    body = f"""<header>
  <h1>foropensource</h1>
  <p class="sub">{len(docs)} companies with {n_offers} verified free offers for open
  source projects and maintainers.</p>
</header>
{NAV}
<section id="matcher">
  <h2>What can your repo get for free?</h2>
  <p>Paste a public GitHub repository &mdash; we detect what it uses (CI, tests, docs,
  translations, &hellip;) and list the offers it qualifies for. Runs in your browser;
  nothing is stored.</p>
  <div class="matcher-row">
    <input id="repo-input" type="text" placeholder="github.com/owner/repo" spellcheck="false">
    <button id="match-btn">Match</button>
  </div>
  <p id="match-status"></p>
  <div id="match-report"></div>
</section>
<div id="directory">
<input id="search" type="search" placeholder="Search companies, products, categories&hellip;">
<div class="cats">{cat_buttons}</div>
<p id="count"></p>
{companies_html}
</div>
<p>Latest verification pass: {esc(last_verified)}.
See also: <a href="/sponsors/">which companies sponsor the most open source projects</a>.</p>"""

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
        description=f"{len(docs)} companies with {n_offers} verified free offers for "
        "open source projects and maintainers: CI, hosting, monitoring, security, "
        "testing, and more. Paste your repo to see what it qualifies for.",
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
    offers_html = "\n".join(render_offer(o, company) for o in doc["offers"])
    verified = max((o.get("last_verified", "") for o in doc["offers"]), default="")
    body = f"""<header>
  <h1><a href="/">foropensource</a></h1>
</header>
{NAV}
<p class="crumbs"><a href="/">All offers</a> &rsaquo; {esc(company)}</p>
<article class="company">
  <h2><a href="{esc(doc['website'])}" target="_blank" rel="noopener nofollow"
    data-track="company_click" data-company="{esc(company)}">{esc(company)}</a></h2>
  <p class="tags">{cat_links}</p>
  {offers_html}
</article>
<p>Verified {esc(verified)}. Details changed?
<a href="{REPO_URL}/blob/main/data/offers/{esc(doc['slug'])}.yaml">Fix it on GitHub</a>.</p>
<p>Not sure you qualify? <a href="/#matcher">Match your repo</a> against all
{esc(doc['total_offers'])} offers, or browse {cat_links or 'the directory'}.</p>"""
    return page(
        title=f"{company} free for open source — what you get and how to apply",
        description=f"{company}'s {offers_word} for open source: "
        f"{'; '.join(products)[:120]}. Eligibility, what you get, and how to apply "
        f"— verified {verified}.",
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
    offers_html = "\n".join(render_offer(o, company) for o in doc["offers"])

    alt_docs = []
    for d in active_docs:
        if set(d.get("categories") or []) & set(cats):
            alt_docs.append(d)
    alt_html = ""
    if alt_docs:
        items = "".join(
            f'<li><a href="/company/{esc(d["slug"])}/">{esc(d["company"])}</a></li>'
            for d in alt_docs[:8]
        )
        cat_links = ", ".join(
            f'<a href="/category/{esc(c)}/">all free {esc(cat_label(c))} offers</a>'
            for c in cats
        )
        alt_html = f"""<h3>Still-active alternatives</h3>
<ul>{items}</ul>
<p>Browse {cat_links}, or <a href="/#matcher">match your repo</a> against every
current offer.</p>"""
    else:
        alt_html = ('<p><a href="/">Browse the directory</a> for current offers, or '
                    '<a href="/#matcher">match your repo</a>.</p>')

    body = f"""<header>
  <h1><a href="/">foropensource</a></h1>
</header>
{NAV}
<p class="crumbs"><a href="/">All offers</a> &rsaquo; {esc(company)}</p>
<h2>Is {esc(company)} still free for open source? No.</h2>
<div class="note"><p>{esc(company)}'s free-for-open-source
{"offer has" if len(products) == 1 else "offers have"} been discontinued
(last checked {esc(verified)}). The details below are kept for reference.</p></div>
<article class="company">
  {offers_html}
</article>
{alt_html}
<p>Know of a new {esc(company)} offer for open source?
<a href="{REPO_URL}/blob/main/data/offers/{esc(doc['slug'])}.yaml">Update it on GitHub</a>.</p>"""
    return page(
        title=f"Is {company} still free for open source? Discontinued — and alternatives",
        description=f"{company}'s free offer for open source "
        f"({'; '.join(products)[:100]}) has been discontinued, last checked "
        f"{verified}. Current alternatives and how to apply.",
        canonical_path=f"/company/{doc['slug']}/",
        body=body,
        extra_head=breadcrumbs_json_ld(
            ("All offers", "/"), (company, f"/company/{doc['slug']}/")
        ),
    )


def build_category_page(cat: str, docs: list[dict], total_companies: int) -> str:
    label = cat_label(cat)
    n_offers = sum(len(d["offers"]) for d in docs)
    names = ", ".join(d["company"] for d in docs[:6])
    cards = "\n".join(render_company_card(d) for d in docs)
    title_label = label if label == "CI/CD" or label[0].isupper() else label.capitalize()
    body = f"""<header>
  <h1><a href="/">foropensource</a></h1>
</header>
{NAV}
<p class="crumbs"><a href="/">All offers</a> &rsaquo; {esc(title_label)}</p>
<h2>Free {esc(label)} for open source projects</h2>
<p class="sub">{n_companies(len(docs))}, {n_offers} verified offers.
Not sure which you qualify for? <a href="/#matcher">Match your repo</a>.</p>
{cards}
<p><a href="/">Browse all {total_companies} companies</a></p>"""
    return page(
        title=f"Free {label} for open source projects — {n_offers} verified offers",
        description=f"{n_offers} verified free {label} offers for open source "
        f"projects, from {names} and more. What you get and how to apply.",
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

    body = f"""<header>
  <h1><a href="/">foropensource</a></h1>
</header>
{NAV}
<h2>Which companies sponsor the most open source projects?</h2>
<p class="sub">{len(ranked)} companies with {n_total} publicly visible sponsorships of
open source projects and maintainers, counted from GitHub Sponsors and Open
Collective. Expand a company to see who they sponsor.</p>
<div class="note"><p><strong>What this measures:</strong> breadth, not dollars.
GitHub Sponsors hides amounts, so a company sponsoring five projects at $10,000
each ranks below one sponsoring fifty at $10. It also excludes support that
doesn't flow through these platforms: direct grants, foundation memberships,
employing maintainers, and free products
(<a href="/">tracked separately in the offers directory</a>).</p></div>
{''.join(entries)}
<p>Data: <a href="{REPO_URL}/blob/main/data/exports/company-sponsorships.csv">company-sponsorships.csv</a>
(CC BY 4.0). Missing a company's sponsorships? <a href="{REPO_URL}">Open a pull request</a>.</p>"""
    return page(
        title="Which companies sponsor the most open source projects?",
        description=f"League table of {len(ranked)} companies by publicly visible "
        "open source sponsorships on GitHub Sponsors and Open Collective — "
        f"{n_total} sponsorships counted, updated from a public dataset.",
        canonical_path="/sponsors/",
        body=body,
    )


def build_404() -> str:
    body = f"""<header>
  <h1><a href="/">foropensource</a></h1>
</header>
{NAV}
<h2>Page not found</h2>
<p>Company pages live at <code>/company/&lt;name&gt;/</code> and categories at
<code>/category/&lt;name&gt;/</code>.</p>
<p><a href="/">Browse all offers</a> or <a href="/#matcher">match your repo</a>
to see what it qualifies for.</p>"""
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
