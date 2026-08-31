# Which company sponsors open source the most? (analysis, 2026-07-14)

Ranking derived from `data/exports/company-sponsorships.csv` (351 sponsorship rows,
35 companies tracked so far out of the 165 in the catalogue).

**What this measures: breadth, not dollars.** It counts publicly visible
sponsorships on GitHub Sponsors / Open Collective per company. GitHub Sponsors
hides amounts, so `known_usd` is almost always empty — a company sponsoring 5
projects at $10k each ranks below one sponsoring 99 at $10 each.

## Top 20 by number of sponsored projects/maintainers

| # | Company | Sponsored targets | Known USD |
|---|---------|------------------:|----------:|
| 1 | CodeRabbit | 99 | — |
| 2 | OpenAI | 50 | — |
| 3 | Sentry | 30 | — |
| 4 | Emerge Tools | 17 | — |
| 5 | GitBook | 17 | — |
| 6 | Tailscale | 15 | — |
| 7 | Convex | 13 | — |
| 8 | GitHub | 12 | — |
| 9 | Healthchecks.io | 12 | — |
| 10 | Weblate | 11 | ~$2,230 (Open Collective) |
| 11 | PostHog | 9 | — |
| 12 | Greptile | 7 | — |
| 13 | 1Password | 5 | — |
| 14 | Datadog | 5 | — |
| 15 | elmah.io | 5 | — |
| 16 | Keygen | 5 | — |
| 17 | Nx Cloud | 5 | — |
| 18 | Chromatic | 4 | — |
| 19 | Screenshotbot | 4 | — |
| 20 | Tuist | 4 | — |

Near-misses: Vercel (4), Crowdin (3), Read the Docs (2 but ~$2,042 verified via
Open Collective), Transloadit (2), AWS (1).

## Known gaps

- **Product sponsorship isn't counted.** The other ~130 catalogue companies
  (AWS, Anthropic, BrowserStack, JetBrains, …) support OSS with free
  products/credits; that value isn't quantified in the data yet. By real
  economic value, AWS or GitHub (free Actions/hosting for public repos) likely
  dwarf everyone above.
- **Big known funders are absent.** Google, Microsoft, Meta, Sovereign Tech
  Fund and foundations fund OSS at millions/year via grants, memberships, and
  employed maintainers — channels this dataset doesn't track.

## Regenerate

```bash
python3 - <<'EOF'
import csv
from collections import defaultdict
counts, dollars = defaultdict(int), defaultdict(float)
with open('data/exports/company-sponsorships.csv') as f:
    for r in csv.DictReader(f):
        counts[r['company']] += 1
        if r['oc_total_donated_usd']:
            dollars[r['company']] += float(r['oc_total_donated_usd'])
for c, n in sorted(counts.items(), key=lambda kv: (-kv[1], -dollars[kv[0]]))[:25]:
    print(f"{c:30} {n:>4} {dollars[c]:>10,.0f}")
EOF
```

## Ideas to get a dollar-weighted ranking (next steps)

- Cross-reference Open Collective API for `oc_total_donated_usd` where missing.
- Scrape sponsor-tier badges on GitHub Sponsors profiles (tier ranges are
  sometimes public even when amounts aren't).
- Estimate product-offer value per company (e.g. list-price of the sponsored
  plan, like Sentry's OSS plan quotas) to compare cash vs product support.
