#!/usr/bin/env python3
"""
Run Phases 2-5 of MLB Historical Backfill

After Phase 1 (GCS scraping) completes, run this to:
1. Load all GCS data to BigQuery (Phase 2)
2. Match betting lines to predictions (Phase 3)
3. Grade predictions (Phase 4)
4. Calculate hit rate (Phase 5)

Usage:
    python scripts/mlb/historical_odds_backfill/run_phases_2_to_5.py

    # Dry-run to see what would happen
    python scripts/mlb/historical_odds_backfill/run_phases_2_to_5.py --dry-run
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

def run_command(cmd: list, description: str, dry_run: bool = False) -> bool:
    """Run a command and return success status."""
    print(f"\n{'='*70}")
    print(f"RUNNING: {description}")
    print(f"{'='*70}")
    print(f"Command: {' '.join(cmd)}")

    if dry_run:
        print("[DRY RUN] Would execute above command")
        return True

    print("")
    start = time.time()

    result = subprocess.run(cmd, cwd=PROJECT_ROOT)

    elapsed = time.time() - start
    print(f"\nCompleted in {elapsed:.1f}s with exit code {result.returncode}")

    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description='Run Phases 2-5 of MLB backfill')
    parser.add_argument('--dry-run', action='store_true', help='Show what would run')
    parser.add_argument('--skip-phase2', action='store_true', help='Skip BigQuery loading')
    args = parser.parse_args()

    print("="*70)
    print("MLB HISTORICAL BACKFILL - PHASES 2-5")
    print("="*70)

    results = {}

    # Phase 2: Load GCS to BigQuery
    if not args.skip_phase2:
        success = run_command(
            [sys.executable, "scripts/mlb/historical_odds_backfill/batch_load_to_bigquery.py"],
            "Phase 2: Load GCS data to BigQuery",
            args.dry_run
        )
        results['phase2'] = success
        if not success and not args.dry_run:
            print("\n❌ Phase 2 failed! Stopping.")
            sys.exit(1)
    else:
        print("\n⏭️  Skipping Phase 2 (--skip-phase2)")
        results['phase2'] = 'skipped'

    # Phase 3: Match lines to predictions
    success = run_command(
        [sys.executable, "scripts/mlb/historical_odds_backfill/match_lines_to_predictions.py"],
        "Phase 3: Match betting lines to predictions",
        args.dry_run
    )
    results['phase3'] = success
    if not success and not args.dry_run:
        print("\n❌ Phase 3 failed! Stopping.")
        sys.exit(1)

    # Phase 4: Grade predictions
    success = run_command(
        [sys.executable, "scripts/mlb/historical_odds_backfill/grade_historical_predictions.py"],
        "Phase 4: Grade predictions",
        args.dry_run
    )
    results['phase4'] = success
    if not success and not args.dry_run:
        print("\n❌ Phase 4 failed! Stopping.")
        sys.exit(1)

    # Phase 5: Calculate hit rate
    success = run_command(
        [sys.executable, "scripts/mlb/historical_odds_backfill/calculate_hit_rate.py"],
        "Phase 5: Calculate hit rate",
        args.dry_run
    )
    results['phase5'] = success

    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    for phase, status in results.items():
        icon = "✅" if status == True else "⏭️" if status == 'skipped' else "❌"
        print(f"  {icon} {phase}: {status}")

    if all(v in [True, 'skipped'] for v in results.values()):
        print("\n🎉 All phases completed successfully!")
        print("\nYour hit rate results are ready. Check the Phase 5 output above.")
    else:
        print("\n⚠️  Some phases failed. Check logs above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
