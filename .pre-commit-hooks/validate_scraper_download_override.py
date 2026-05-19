#!/usr/bin/env python3
"""Pre-commit hook: detect dead `download()` overrides on scrapers.

The base scraper lifecycle (scrapers/scraper_base.py:run → download_and_decode
→ start_download → download_data) NEVER calls `download(self)`. Overriding it
is dead code: the method exists in the class but the framework skips past it.

This caught us at least three times:
  * mlb_weather (fixed 2026-05-17): override existed for 6+ months, scraper
    silently 401'd every run; weather data only landed after `start_download`
    was correctly overridden.
  * mlb_ballpark_factors (cleaned up 2026-05-18): harmless because transform
    reads a module constant directly, but the dead method was confusing.
  * mlb_statcast_pitcher (cleaned up 2026-05-18): would have crashed at
    transform if anything had invoked it; target table had 0 rows ever.

Correct overrides:
  * `start_download(self)` — full control over download phase
  * `download_data(self)` — full control over the HTTP fetch step
  * `download_and_decode(self)` — replace the whole phase
  * `download_from_gcs(self)` — when reading pre-staged files from GCS
  * `download_via_browser(self)` / `download_data_with_proxy(self)` — variants

Anything matching `def download(self` exactly (no other suffix) is wrong.
"""
import os
import re
import sys

# Walk the scrapers/ tree.
SCRAPERS_DIR = 'scrapers'

# Files this hook itself or tests that *test* the dead-method pattern.
EXCLUDE_FILES = {
    '.pre-commit-hooks/validate_scraper_download_override.py',
}

# `def download(self` followed by an open paren or a colon — but NOT
# `download_data`, `download_and_decode`, `download_from_gcs`, etc.
# The trailing lookahead ensures we don't match download_*.
DEAD_PATTERN = re.compile(r'^\s*def\s+download\s*\(\s*self\b')


def should_exclude_path(filepath: str) -> bool:
    normalized = filepath.replace(os.sep, '/')
    for exclude in EXCLUDE_FILES:
        if normalized == exclude or normalized.endswith('/' + exclude):
            return True
    return False


def main() -> int:
    print("Checking scrapers for dead `download()` overrides...")
    if not os.path.exists(SCRAPERS_DIR):
        print(f"  {SCRAPERS_DIR}/ not found — skipping")
        return 0

    errors = []
    checked = 0

    for root, _, files in os.walk(SCRAPERS_DIR):
        if '__pycache__' in root:
            continue
        for f in files:
            if not f.endswith('.py'):
                continue
            filepath = os.path.join(root, f)
            if should_exclude_path(filepath):
                continue
            checked += 1
            try:
                with open(filepath, 'r') as fh:
                    for line_num, line in enumerate(fh, 1):
                        if DEAD_PATTERN.search(line):
                            errors.append(f"  {filepath}:{line_num}: {line.rstrip()}")
            except (UnicodeDecodeError, PermissionError):
                continue

    if errors:
        print(f"\n{'='*60}")
        print(f"FAILED: dead `download(self)` overrides found")
        print(f"{'='*60}")
        for err in errors:
            print(err)
        print(f"\nThe base scraper lifecycle never calls download(self). Override")
        print(f"`start_download` (or `download_data` / `download_from_gcs` /")
        print(f"`download_via_browser` / `download_data_with_proxy`) instead.")
        print(f"See scrapers/mlb/external/mlb_weather.py for the canonical fix.")
        return 1

    print(f"  Checked {checked} scraper files — no dead download() overrides found")
    return 0


if __name__ == '__main__':
    sys.exit(main())
