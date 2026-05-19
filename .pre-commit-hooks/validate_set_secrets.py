#!/usr/bin/env python3
"""Pre-commit hook: Detect dangerous --set-secrets in deploy scripts.

Similar bug class to --set-env-vars (Session 81/213): using --set-secrets on a
Cloud Run service or Cloud Function REPLACES all currently-mounted secrets.
Any secret not enumerated in the --set-secrets argument gets unmounted, and
the next process restart will fail because env vars like
OPENWEATHERMAP_API_KEY / BETTINGPROS_API_KEY simply disappear.

2026-05-17 incident: bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh used
--set-secrets but only listed ODDS_API_KEY. Re-running the script would have
unmounted OPENWEATHERMAP_API_KEY, breaking the mlb_weather scraper. Fix was
to extend the list AND prefer --update-secrets going forward.

Use --update-secrets instead — preserves all existing secret mounts and only
adds/changes the ones you specify.

This hook scans deploy-related files for the dangerous pattern.
"""
import os
import re
import sys

PATTERNS = [
    ('bin/', '*.sh'),
    ('orchestration/', '*.yaml'),
    ('.', 'cloudbuild*.yaml'),
]

EXCLUDE_DIRS = {
    'bin/archive',
}

# Files that legitimately discuss --set-secrets (this hook, docs).
EXCLUDE_FILES = {
    '.pre-commit-hooks/validate_set_secrets.py',
}

DANGEROUS_PATTERN = re.compile(r'--set-secrets\b')


def is_false_positive(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith('#'):
        return True
    if stripped.startswith(('echo ', 'echo "', "echo '", 'printf ')):
        return True
    return False


def should_exclude_path(filepath: str) -> bool:
    normalized = filepath.replace(os.sep, '/')
    for exclude_dir in EXCLUDE_DIRS:
        if normalized.startswith(exclude_dir + '/') or ('/' + exclude_dir + '/') in normalized:
            return True
    for exclude_file in EXCLUDE_FILES:
        if normalized == exclude_file or normalized.endswith('/' + exclude_file):
            return True
    return False


def main() -> int:
    print("Checking for dangerous --set-secrets usage...")
    errors = []
    checked = 0

    for search_dir, file_pattern in PATTERNS:
        if not os.path.exists(search_dir):
            continue
        for root, _, files in os.walk(search_dir):
            for f in files:
                if file_pattern.startswith('*'):
                    ext = file_pattern[1:]
                    if not f.endswith(ext):
                        continue
                elif f != file_pattern:
                    continue

                filepath = os.path.join(root, f)
                if should_exclude_path(filepath):
                    continue

                checked += 1
                try:
                    with open(filepath, 'r') as fh:
                        for line_num, line in enumerate(fh, 1):
                            if DANGEROUS_PATTERN.search(line) and not is_false_positive(line):
                                errors.append(f"  {filepath}:{line_num}: {line.strip()}")
                except (UnicodeDecodeError, PermissionError):
                    continue

    if errors:
        print(f"\n{'='*60}")
        print(f"FAILED: Found --set-secrets (should be --update-secrets)")
        print(f"{'='*60}")
        for err in errors:
            print(err)
        print(f"\n--set-secrets REPLACES all mounted secrets — any secret not")
        print(f"listed gets unmounted at next restart (the 2026-05-17 mlb_weather")
        print(f"incident). Use --update-secrets instead to preserve mounts.")
        return 1

    print(f"  Checked {checked} deploy files - no dangerous patterns found")
    return 0


if __name__ == '__main__':
    sys.exit(main())
