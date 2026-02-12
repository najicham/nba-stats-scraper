#!/usr/bin/env python3
"""Pre-commit hook: Detect dangerous --set-env-vars in deploy scripts.

Session 81/213: Using --set-env-vars WIPES ALL existing environment variables
on a Cloud Run service or Cloud Function. This can cause catastrophic failures
(missing SLACK_WEBHOOK_URL, MODEL_PATH, etc.) that are hard to diagnose.

Always use --update-env-vars instead, which preserves existing vars.

This hook scans deploy-related files for the dangerous pattern.
"""
import re
import sys
import os

# Files to check for --set-env-vars
PATTERNS = [
    ('bin/deploy/', '*.sh'),
    ('bin/', '*.sh'),
    ('orchestration/', '*.yaml'),
    ('.', 'cloudbuild*.yaml'),
]

DANGEROUS_PATTERN = re.compile(r'--set-env-vars\b')
SAFE_PATTERN = re.compile(r'--update-env-vars\b')


def main():
    print("Checking for dangerous --set-env-vars usage...")
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
                checked += 1
                try:
                    with open(filepath, 'r') as fh:
                        for line_num, line in enumerate(fh, 1):
                            if DANGEROUS_PATTERN.search(line):
                                errors.append(f"  {filepath}:{line_num}: {line.strip()}")
                except (UnicodeDecodeError, PermissionError):
                    continue

    if errors:
        print(f"\n{'='*60}")
        print(f"FAILED: Found --set-env-vars (should be --update-env-vars)")
        print(f"{'='*60}")
        for err in errors:
            print(err)
        print(f"\n--set-env-vars WIPES ALL existing env vars!")
        print(f"Use --update-env-vars instead to preserve existing vars.")
        print(f"See: Session 81 post-mortem, CLAUDE.md [ISSUES] section")
        return 1

    print(f"  Checked {checked} deploy files - no dangerous patterns found")
    return 0


if __name__ == '__main__':
    sys.exit(main())
