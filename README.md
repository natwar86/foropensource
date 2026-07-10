# foropensource

Companies give free products, services, and money to open source projects and maintainers. Most of those offers are scattered across program pages that are hard to find and quietly go stale. This repo collects them as structured, verified data that anyone can use or improve.

Browse the list at **https://foropensource.com**.

## What's in here

**`data/offers/`** — one YAML file per company, 163 companies so far. Each offer records what you get, who is eligible, how to apply, and a `last_verified` date with a note on how it was checked. Example:

```yaml
company: BrowserStack
website: https://www.browserstack.com
categories: [testing]
offers:
  - product: BrowserStack Open Source program (Live, Automate, Percy)
    offer_url: https://www.browserstack.com/open-source
    what_you_get: >-
      Free unlimited testing on desktop and mobile with Live, Automate, and
      Percy for 5 users and 5 parallel tests.
    eligibility:
      applies_to: project
      notes: For open source projects; a project URL is required when applying.
    how_to_apply: >-
      Sign up via the open source program page and provide the project URL.
    status: active
    last_verified: "2026-07-06"
```

**`data/exports/sponsored-projects.csv`** — 12,712 open source projects that receive funding through GitHub Sponsors or Open Collective, with sponsor counts and 12-month Open Collective totals where available.

**`data/exports/company-sponsorships.csv`** — 351 records of companies sponsoring specific maintainers and projects, matched back to the projects they fund.

## Contributing

The most useful contributions, in order:

1. **Mark a dead offer.** Offers rot. If a program page 404s or the terms changed, a PR setting `status: discontinued` (or fixing the terms) helps everyone who would have wasted an application on it.
2. **Add a company.** Copy any existing file in `data/offers/`, fill it in, set `last_verified` to today. One company per file, filename is the company name in kebab-case.
3. **Re-verify an old entry.** Check the offer page still says what we say it says, then bump `last_verified`.

Every PR is validated against `schemas/offer.schema.json` by CI, so you'll get immediate feedback if a field is missing. Details in [CONTRIBUTING.md](CONTRIBUTING.md).

## Licensing

- Offers data (`data/offers/`): [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Use it anywhere, credit "foropensource".
- Exports (`data/exports/`): [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), because they derive from [ecosyste.ms](https://ecosyste.ms) open data (CC BY-SA 4.0), with additional matching against [deps.dev](https://deps.dev) and public GitHub Sponsors / Open Collective pages.
- Code (`scripts/`): MIT.
