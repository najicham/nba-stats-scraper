#!/usr/bin/env python3
"""Pre-commit hook: Validate Python syntax in bin/ and orchestration/ directories.

Session 213: Orphaned code in bin/monitoring/phase_transition_monitor.py caused
IndentationError that broke Cloud Function deploys via cloudbuild-functions.yaml.
Cloud Functions deploy validates ALL Python files in the deploy package, so a syntax
error in any file (even unrelated monitoring scripts) blocks deployment.

This hook prevents syntax errors from reaching main by catching them at commit time.
"""
import py_compile
import sys
import os

# Directories included in Cloud Function / Cloud Run deploy packages.
# 2026-07-04: added 'scrapers' and 'orchestration' — 3 SyntaxErrors in scrapers/espn/*.py
# reached main because the scope excluded scrapers/ (orchestration/ was in the docstring but
# never actually in this list).
DEPLOY_DIRS = ['bin', 'shared', 'data_processors', 'predictions', 'backfill_jobs',
               'scrapers', 'orchestration']

def main():
    print("Checking Python syntax in deploy-critical directories...")
    errors = []
    checked = 0

    for deploy_dir in DEPLOY_DIRS:
        if not os.path.isdir(deploy_dir):
            continue
        for root, _, files in os.walk(deploy_dir):
            for f in files:
                if not f.endswith('.py'):
                    continue
                filepath = os.path.join(root, f)
                # Skip symlinks: orchestration/ CF dirs symlink into shared/, and the real
                # targets are already validated under the 'shared' walk. A dangling symlink
                # would otherwise raise FileNotFoundError and crash the whole hook.
                if os.path.islink(filepath):
                    continue
                checked += 1
                try:
                    py_compile.compile(filepath, doraise=True)
                except py_compile.PyCompileError as e:
                    errors.append(str(e))
                except (OSError, ValueError) as e:
                    # Unreadable file (e.g. broken path) — report, don't crash the hook.
                    errors.append(f"{filepath}: {e}")

    if errors:
        print(f"\n{'='*60}")
        print(f"FAILED: {len(errors)} Python syntax error(s) found!")
        print(f"{'='*60}")
        for err in errors:
            print(f"\n  {err}")
        print(f"\nThese errors will break Cloud Function deploys.")
        print(f"Fix the syntax errors before committing.")
        return 1

    print(f"  Checked {checked} Python files - all OK")
    return 0


if __name__ == '__main__':
    sys.exit(main())
