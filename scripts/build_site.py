#!/usr/bin/env python3
"""Build the static site (a single index.html) from data/offers/ into _site/."""

import html
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OFFERS_DIR = ROOT / "data" / "offers"
OUT_DIR = ROOT / "_site"

REPO_URL = "https://github.com/natwar86/foropensource"
SITE_URL = "https://foropensource.com"


def esc(value) -> str:
    return html.escape(str(value), quote=True)


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


def render_offer(offer: dict) -> str:
    status = offer.get("status", "active")
    badge = ""
    if status != "active":
        badge = f' <span class="badge badge-{esc(status)}">{esc(status)}</span>'
    elig = eligibility_line(offer.get("eligibility") or {})
    parts = [
        '<div class="offer">',
        f'<p class="offer-title"><a href="{esc(offer["offer_url"])}" target="_blank" rel="noopener nofollow">'
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


def render_company(doc: dict) -> str:
    cats = doc.get("categories") or []
    tags = "".join(f'<span class="tag">{esc(c)}</span>' for c in cats)
    offers_html = "\n".join(render_offer(o) for o in doc["offers"])
    search_blob = " ".join(
        [doc["company"]]
        + cats
        + [o.get("product", "") + " " + o.get("what_you_get", "") for o in doc["offers"]]
    ).lower()
    return f"""
<article class="company" data-search="{esc(search_blob)}" data-categories="{esc(' '.join(cats))}">
  <h2><a href="{esc(doc['website'])}" target="_blank" rel="noopener nofollow">{esc(doc['company'])}</a></h2>
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
header p.sub { color: var(--muted); margin: 0 0 1.2rem; }
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
  border-radius: 4px; padding: 0.05rem 0.45rem; font-size: 0.75rem; margin-right: 0.3rem; }
.offer { border-top: 1px solid var(--line); padding-top: 0.7rem; margin-top: 0.7rem; }
.offer-title { margin: 0 0 0.25rem; font-weight: 600; }
.offer-what { margin: 0 0 0.35rem; }
.offer-meta { margin: 0 0 0.25rem; color: var(--muted); font-size: 0.88rem; }
.offer-verified { margin: 0; color: var(--muted); font-size: 0.78rem; }
.badge { font-size: 0.72rem; padding: 0.05rem 0.4rem; border-radius: 4px;
  vertical-align: middle; font-weight: 400; }
.badge-stale { background: #f5e9c8; color: #7a5d00; }
#count { color: var(--muted); font-size: 0.88rem; margin: 0 0 1rem; }
footer { margin-top: 3rem; color: var(--muted); font-size: 0.85rem;
  border-top: 1px solid var(--line); padding-top: 1rem; }
"""

JS = """
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
for (const btn of buttons) {
  btn.addEventListener('click', () => {
    activeCat = activeCat === btn.dataset.cat ? null : btn.dataset.cat;
    buttons.forEach(b => b.classList.toggle('on', b.dataset.cat === activeCat));
    apply();
  });
}
apply();
"""


def main() -> int:
    docs = []
    for path in sorted(OFFERS_DIR.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text())
        if not doc:
            continue
        # Discontinued offers stay in the dataset but are not rendered.
        doc["offers"] = [o for o in doc["offers"] if o.get("status") != "discontinued"]
        if doc["offers"]:
            docs.append(doc)
    docs.sort(key=lambda d: d["company"].lower())

    n_offers = sum(len(d["offers"]) for d in docs)
    all_cats = sorted({c for d in docs for c in (d.get("categories") or [])})
    last_verified = max(
        (o.get("last_verified", "") for d in docs for o in d["offers"]), default=""
    )

    cat_buttons = "".join(
        f'<button data-cat="{esc(c)}">{esc(c)}</button>' for c in all_cats
    )
    companies_html = "\n".join(render_company(d) for d in docs)

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>foropensource — free products and services for open source</title>
<meta name="description" content="{len(docs)} companies with verified free offers for open source projects and maintainers: CI, hosting, monitoring, security, testing, and more.">
<link rel="canonical" href="{SITE_URL}/">
<meta property="og:title" content="foropensource — free products and services for open source">
<meta property="og:description" content="{len(docs)} companies with {n_offers} verified free offers for open source projects and maintainers.">
<meta property="og:url" content="{SITE_URL}/">
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary">
<script type="application/ld+json">{{
  "@context": "https://schema.org",
  "@type": "Dataset",
  "name": "foropensource offers dataset",
  "description": "Verified free-for-open-source offers from {len(docs)} companies, as structured YAML.",
  "url": "{SITE_URL}/",
  "license": "https://creativecommons.org/licenses/by/4.0/",
  "isAccessibleForFree": true,
  "distribution": [{{"@type": "DataDownload", "encodingFormat": "application/yaml",
    "contentUrl": "{REPO_URL}/tree/main/data/offers"}}]
}}</script>
<style>{CSS}</style>
</head>
<body>
<main>
<header>
  <h1>foropensource</h1>
  <p class="sub">{len(docs)} companies with {n_offers} verified free offers for open
  source projects and maintainers. Community-maintained on
  <a href="{REPO_URL}">GitHub</a> &mdash; add a company or flag a dead offer
  with a pull request.</p>
</header>
<input id="search" type="search" placeholder="Search companies, products, categories&hellip;" autofocus>
<div class="cats">{cat_buttons}</div>
<p id="count"></p>
{companies_html}
<footer>
  <p>Offers data is <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>.
  Latest verification pass: {esc(last_verified)}.
  Source and datasets: <a href="{REPO_URL}">github.com/natwar86/foropensource</a>.</p>
</footer>
</main>
<script>{JS}</script>
</body>
</html>
"""
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "index.html").write_text(page)
    (OUT_DIR / "CNAME").write_text("foropensource.com\n")
    # Machine-readable export of the full dataset (includes discontinued offers).
    all_docs = [yaml.safe_load(p.read_text()) for p in sorted(OFFERS_DIR.glob("*.yaml"))]
    (OUT_DIR / "offers.json").write_text(json.dumps(all_docs, indent=1))
    (OUT_DIR / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n"
    )
    (OUT_DIR / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{SITE_URL}/</loc><lastmod>{last_verified}</lastmod></url>\n"
        "</urlset>\n"
    )
    print(f"Wrote _site/index.html: {len(docs)} companies, {n_offers} offers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
