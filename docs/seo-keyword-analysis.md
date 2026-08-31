# SEO: keyword analysis vs. live search data

Two passes. The July pass estimated demand from Keyword Planner before the
multi-page site existed. The August pass reads Google Search Console after it
shipped. Where they disagree, trust August.

---

## August 2026: what Search Console actually shows

Property `sc-domain:foropensource.com`, 2026-06-01 to 2026-08-31.

| | |
|---|---:|
| Impressions | 6,900 |
| Clicks | 37 |
| CTR | 0.5% |
| Average position | 25.2 |
| Queries with an impression | 493 |
| Pages with an impression | 198 |

### The multi-page build worked as an indexing play

| Month | Impressions | Clicks | Avg position |
|---|---:|---:|---:|
| Jun | no data | | |
| Jul | 653 | 1 | 23.7 |
| Aug | 6,247 | 36 | 25.4 |

Impressions grew about tenfold in a month while average position stayed flat.
That is new pages entering the index, not old pages climbing. 155 of 164
company pages have been shown at least once. Nine never have.

### Company pages carry the site

| Page type | Impressions | Clicks | Pages |
|---|---:|---:|---:|
| company | 5,767 | 25 | 155 |
| home | 712 | 3 | 1 |
| category | 315 | 3 | 20 |
| sponsors | 231 | 6 | 22 |

Company pages take 82% of impressions. The July call to make them the SEO build
was right.

### The keyword bet was wrong

July said to target `"{company} open source"`. That pattern barely appears:

| query | impressions |
|---|---:|
| 1password open source | 1 |
| algolia open source | 11 |
| circleci open source | 14 |

The impressions land on the bare brand name instead:

| query | impressions | position |
|---|---:|---:|
| caphyon | 101 | 26.9 |
| jsdelivr | 66 | 19.9 |
| codecov | 58 | 30.2 |
| packagecloud | 55 | 21.7 |
| styleci | 49 | 11.4 |
| appsignal | 49 | 38.4 |
| pullapprove | 44 | 10.6 |

Someone typing "codecov" wants codecov.io. A registry entry at position 30 will
not take that click, and no title rewrite changes the intent behind the query.

### Nothing ranks near the top

| Position | Impressions |
|---|---:|
| 1 to 3 | 0 |
| 4 to 10 | 256 |
| 11 to 20 | 610 |
| 21 to 50 | 1,037 |
| 50+ | 229 |

Half the visible impressions sit past position 21. The 0.5% CTR is what an
average position of 25 produces. It is a ranking problem, not a snippet problem.

### A query family July never measured

Queries containing a word like free, pricing, cost, or trial:

| query | impressions | position |
|---|---:|---:|
| cachix free | 11 | 8.2 |
| aikido free forever | 25 | 8.8 |
| signpath pricing | 7 | 9.1 |
| signpath foundation free code signing open source | 7 | 10.7 |
| mergify pricing | 11 | 11.0 |
| macstadium open source | 11 | 15.5 |
| transifex free | 9 | 21.4 |
| keycdn free trial | 24 | 25.9 |
| deployhq pricing | 25 | 35.4 |

"Is X free forever?" is the question a foropensource record answers directly,
and several of these already sit near page one. Worth testing properly. But the
click data does not yet support it: this family has 638 impressions and zero
clicks, and so does the brand family at 1,494 impressions and two clicks. At
these positions and volumes, zero clicks is the expected outcome either way.
Do not read it as a signal.

### Read these numbers carefully

The query dimension accounts for 2,132 of 6,900 impressions. Google withholds
the rest as anonymized queries, so about two thirds of the traffic is invisible
at query level. Most of the 37 clicks come from that hidden bucket, which means
no per-query click conclusion above is safe.

The page table sums to 7,025 against a 6,900 total. Search Console aggregates
each dimension separately and the two do not reconcile. Expected, not an error.

37 clicks is a small sample. The site is three months old. Treat everything
here as direction, not proof.

### The nine pages with no impressions

Checked with the URL Inspection API on 2026-08-31. They split cleanly.

**Seven are graveyard pages and they are healthy.** Auth0, Balsamiq, codebeat,
Equinix Metal, Fosshost, Greenkeeper, lgtm. All return verdict PASS, coverage
"Submitted and indexed", crawled between 2026-07-29 and 2026-08-11, robots
ALLOWED, canonical matching. They get no impressions because nobody searches
for a discontinued product. The other ten graveyard pages do get impressions,
so the page type works. Nothing here to fix.

**Two are active pages Google has never fetched.** OpenPanel and Upstash return
"Discovered - currently not indexed" with `lastCrawlTime: never`. Every obvious
cause was ruled out: both have been in the sitemap since 2026-07-10, both are
linked from the homepage, canonical and robots are fine, and internal links
rank 86th and 66th of 164 against a median of 3. Content depth is normal at 202
and 194 words, against Cachix at 187 words which ranks and pulls 144
impressions. Google discovered the URLs and deprioritised fetching them. No
lever on this side beyond requesting indexing by hand.

### The graveyard was orphaned (fixed 2026-08-31)

Ranking company pages by inbound internal links turned up the real problem.
All 17 discontinued pages had **zero** inbound links, reachable by sitemap
alone. Keeping them out of the directory is deliberate. Leaving them with no
link anywhere was not, and it defeats their stated purpose of catching "is X
still free for open source?" and routing people to a live alternative.

Fixed in `9df2107`: each category page now ends with the discontinued companies
in that category.

Auth0 needed a data change rather than a template change. Its only category was
`auth`, it is the sole member, and it is dead, so no `/category/auth/` page gets
generated. The same gap ran the other way: its page listed no alternatives,
because that needs an active company sharing a category. It gained `security` as
a second category, which is honest for an identity product and fixes both
directions. Synced to the private repo as `03a3415`.

Audited against the live site afterwards: 17 of 17 linked, zero orphans.

### Not reflected here

Company pages got an `h1` on 2026-08-31, along with `Offer` schema, markdown
mirrors, and the graveyard links above. All landed after this data window.

---

## What to do next

1. Test the free-tier and pricing query family. It matches what the site
   answers and July never measured it.
2. Leave the bare-brand queries alone. Position 10 to 30 against the vendor's
   own domain is not winnable and not worth the effort.
3. Watch whether the graveyard links move the seven zero-impression pages.
   They were indexed already, so the links change ranking inputs, not
   discovery.
4. Re-pull this report in October. One month of tenfold growth is not a trend.

Distribution still matters more than search. July finding 1 holds: even "free
for dev" gets about 210 searches a month, and that project runs on GitHub and
word of mouth.

---

## July 2026 pass (superseded, kept for the record)

Keywords Everywhere, US, GKP data, 2026-07-14. 87 keywords across 6 groups.
Raw data in scratchpad `ke_results.json`; script pattern in
`websitebuilder/run_ke.py`.

Findings that held up:

1. Small Google demand overall. "free for dev" gets about 210 searches a month.
   Distribution beats SEO here.
3. "free for open source" (170/mo) is the head term and the site name.
4. Category queries measured near zero. Build them for browse UX and internal
   linking, not as a search bet. August confirms: 315 impressions across 20
   pages.
5. Sponsorship queries near zero. The league table is a linkbait and citation
   asset, not an organic play.

Finding that did not hold up:

2. Per-company pages were right, but the target was wrong. July predicted
   `"{company} open source"` at 30 to 170 searches a month each (tailscale 170,
   sentry 140, posthog 140). Live data shows single-digit impressions for that
   pattern and the volume on bare brand names instead.

On-page gaps listed in July, all now closed: sitemap listed one URL, no
favicon, no og:image, one page as the only ranking surface, weak internal
linking.

282,806 Keywords Everywhere credits remained after that run.
