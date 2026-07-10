# Contributing

## Add a company

1. Copy an existing file from `data/offers/` (e.g. `browserstack.yaml`) to `data/offers/<company-name>.yaml`, kebab-case, one company per file.
2. Fill in the fields. The schema is `schemas/offer.schema.json`; required per offer: `product`, `offer_url`, `what_you_get`, `eligibility`, `how_to_apply`, `status`, `last_verified`.
3. Write `what_you_get` concretely. "Free All Products Pack for active maintainers" is useful; "free stuff for open source" is not.
4. Set `last_verified` to today's date and say in `verification_source` how you checked (usually "manual: offer page live, terms match").
5. Open a PR. CI validates the file; a maintainer merges.

What counts: the offer must be specifically for open source (projects, maintainers, or contributors). A generic free tier that anyone gets does not count.

## Fix or retire an offer

If an offer's page is gone or its terms no longer match, either correct the fields or set `status: discontinued`. Keep the file; a discontinued entry stops other people from applying to a dead program.

If you checked an offer and it's still accurate, bumping `last_verified` (with a `verification_source` note) is a valid one-line PR.

## Validate locally (optional)

```sh
pip install pyyaml jsonschema
python scripts/validate.py
```

CI runs the same script on every PR.

## Exports

The CSVs in `data/exports/` are generated from a pipeline, not hand-edited, so PRs against them will generally be declined. Open an issue instead if you spot wrong data there.
