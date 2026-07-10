#!/usr/bin/env python3
"""Validate every file in data/offers/ against schemas/offer.schema.json.

Exit code 0 if all files pass, 1 otherwise. Used by CI on every PR.
"""

import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
OFFERS_DIR = ROOT / "data" / "offers"
SCHEMA_PATH = ROOT / "schemas" / "offer.schema.json"


def main() -> int:
    schema = json.loads(SCHEMA_PATH.read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    files = sorted(OFFERS_DIR.glob("*.yaml"))
    if not files:
        print(f"No offer files found in {OFFERS_DIR}", file=sys.stderr)
        return 1

    errors = 0
    seen_companies: dict[str, Path] = {}
    for path in files:
        try:
            doc = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            print(f"FAIL {path.name}: YAML parse error: {exc}", file=sys.stderr)
            errors += 1
            continue

        file_errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
        for err in file_errors:
            where = "/".join(str(p) for p in err.path) or "(root)"
            print(f"FAIL {path.name}: {where}: {err.message}", file=sys.stderr)
            errors += 1

        company = (doc or {}).get("company")
        if isinstance(company, str):
            key = company.strip().lower()
            if key in seen_companies:
                print(
                    f"FAIL {path.name}: duplicate company {company!r}"
                    f" (also in {seen_companies[key].name})",
                    file=sys.stderr,
                )
                errors += 1
            else:
                seen_companies[key] = path

    if errors:
        print(f"\n{errors} error(s) across {len(files)} files", file=sys.stderr)
        return 1
    print(f"OK: {len(files)} offer files valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
