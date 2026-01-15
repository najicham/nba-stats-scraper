#!/usr/bin/env python3
"""
Run All Phases - Unified Pipeline Executor

Runs all phases of the historical odds backfill pipeline in sequence:
- Phase 2: Process GCS to BigQuery
- Phase 3: Match lines to predictions
- Phase 4: Grade predictions
- Phase 5: Calculate hit rate (enhanced)
- Bonus: Pitcher analysis

Usage:
    # Run all phases after backfill completes
    python scripts/mlb/historical_odds_backfill/run_all_phases.py

    # Start from specific phase
    python scripts/mlb/historical_odds_backfill/run_all_phases.py --start-phase 3

    # Run only specific phases
    python scripts/mlb/historical_odds_backfill/run_all_phases.py --phases 4,5

    # Dry run (show what would run)
    python scripts/mlb/historical_odds_backfill/run_all_phases.py --dry-run

    # Skip interactive prompts
    python scripts/mlb/historical_odds_backfill/run_all_phases.py --yes
"""

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Phase definitions
PHASES = {
    2: {
        'name': 'Process GCS to BigQuery',
        'script': 'process_historical_to_bigquery.py',
        'description': 'Load historical betting lines from GCS to BigQuery',
        'estimated_time': '5-10 minutes',
    },
    3: {
        'name': 'Match Lines to Predictions',
        'script': 'match_lines_to_predictions.py',
        'description': 'Match consensus betting lines to predictions',
        'estimated_time': '1-2 minutes',
    },
    4: {
        'name': 'Grade Predictions',
        'script': 'grade_historical_predictions.py',
        'description': 'Grade predictions against actual results',
        'estimated_time': '1-2 minutes',
    },
    5: {
        'name': 'Calculate Hit Rate (Enhanced)',
        'script': 'calculate_hit_rate.py',
        'description': 'Calculate comprehensive hit rate with statistical analysis',
        'estimated_time': '2-3 minutes',
    },
    6: {
        'name': 'Pitcher Analysis',
        'script': 'analyze_by_pitcher.py',
        'description': 'Analyze performance by individual pitcher',
        'estimated_time': '1-2 minutes',
        'optional': True,
    },
    7: {
        'name': 'Edge Threshold Optimization',
        'script': 'optimize_edge_threshold.py',
        'description': 'Find optimal edge threshold for betting',
        'estimated_time': '1-2 minutes',
        'optional': True,
    },
    8: {
        'name': 'Bookmaker Analysis',
        'script': 'analyze_by_bookmaker.py',
        'description': 'Analyze performance by bookmaker',
        'estimated_time': '1-2 minutes',
        'optional': True,
    },
}

SCRIPT_DIR = Path(__file__).parent


def run_phase(phase_num: int, dry_run: bool = False, extra_args: List[str] = None) -> bool:
    """Run a single phase."""
    if phase_num not in PHASES:
        logger.error(f"Unknown phase: {phase_num}")
        return False

    phase = PHASES[phase_num]
    script_path = SCRIPT_DIR / phase['script']

    if not script_path.exists():
        logger.error(f"Script not found: {script_path}")
        return False

    logger.info("")
    logger.info("=" * 70)
    logger.info(f"PHASE {phase_num}: {phase['name']}")
    logger.info("=" * 70)
    logger.info(f"Description: {phase['description']}")
    logger.info(f"Estimated time: {phase['estimated_time']}")
    logger.info(f"Script: {phase['script']}")

    if dry_run:
        logger.info("DRY RUN: Would execute this phase")
        return True

    cmd = [sys.executable, str(script_path)]
    if extra_args:
        cmd.extend(extra_args)

    logger.info(f"Command: {' '.join(cmd)}")
    logger.info("-" * 70)

    start_time = time.time()

    try:
        # Run the script and capture output
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            timeout=1800,  # 30 minute timeout per phase
        )

        elapsed = time.time() - start_time

        if result.returncode == 0:
            logger.info(f"\n✓ Phase {phase_num} completed successfully in {elapsed:.1f}s")
            return True
        else:
            logger.error(f"\n✗ Phase {phase_num} failed with return code {result.returncode}")
            return False

    except subprocess.TimeoutExpired:
        logger.error(f"\n✗ Phase {phase_num} timed out after 30 minutes")
        return False
    except Exception as e:
        logger.exception(f"\n✗ Phase {phase_num} failed with error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Run all phases of the historical odds backfill pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Available Phases:
  2 - Process GCS to BigQuery (load historical betting lines)
  3 - Match Lines to Predictions (calculate consensus lines)
  4 - Grade Predictions (compare to actual results)
  5 - Calculate Hit Rate (statistical analysis)
  6 - Pitcher Analysis (optional, analyze by pitcher)

Examples:
  # Run all phases
  python run_all_phases.py

  # Run from phase 3 onwards
  python run_all_phases.py --start-phase 3

  # Run only phases 4 and 5
  python run_all_phases.py --phases 4,5

  # Dry run to see what would execute
  python run_all_phases.py --dry-run
        """
    )

    parser.add_argument(
        '--start-phase',
        type=int,
        default=2,
        help='Phase to start from (default: 2)'
    )
    parser.add_argument(
        '--phases',
        type=str,
        help='Specific phases to run (comma-separated, e.g., "4,5")'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be run without executing'
    )
    parser.add_argument(
        '--yes', '-y',
        action='store_true',
        help='Skip confirmation prompts'
    )
    parser.add_argument(
        '--include-optional',
        action='store_true',
        help='Include optional phases (pitcher analysis)'
    )
    parser.add_argument(
        '--start-date',
        help='Start date for analysis (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        help='End date for analysis (YYYY-MM-DD)'
    )

    args = parser.parse_args()

    # Determine which phases to run
    if args.phases:
        phases_to_run = [int(p.strip()) for p in args.phases.split(',')]
    else:
        phases_to_run = [p for p in PHASES.keys() if p >= args.start_phase]
        if not args.include_optional:
            phases_to_run = [p for p in phases_to_run if not PHASES[p].get('optional')]

    # Build extra args
    extra_args = []
    if args.start_date:
        extra_args.extend(['--start-date', args.start_date])
    if args.end_date:
        extra_args.extend(['--end-date', args.end_date])

    # Display plan
    logger.info("=" * 70)
    logger.info("MLB HISTORICAL ODDS BACKFILL - PIPELINE EXECUTOR")
    logger.info("=" * 70)
    logger.info(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("")
    logger.info("Phases to execute:")
    total_estimated = 0
    for phase_num in phases_to_run:
        phase = PHASES[phase_num]
        optional = " (optional)" if phase.get('optional') else ""
        logger.info(f"  {phase_num}. {phase['name']}{optional}")
        logger.info(f"     {phase['description']}")
        logger.info(f"     Est. time: {phase['estimated_time']}")

    # Confirmation
    if not args.dry_run and not args.yes:
        logger.info("")
        response = input("Proceed with execution? [y/N]: ")
        if response.lower() not in ['y', 'yes']:
            logger.info("Aborted by user")
            sys.exit(0)

    # Execute phases
    start_time = time.time()
    results = {}

    for phase_num in phases_to_run:
        success = run_phase(phase_num, dry_run=args.dry_run, extra_args=extra_args)
        results[phase_num] = success

        if not success and not args.dry_run:
            logger.error(f"\nPipeline stopped due to failure in phase {phase_num}")
            break

    # Summary
    elapsed = time.time() - start_time
    logger.info("")
    logger.info("=" * 70)
    logger.info("PIPELINE SUMMARY")
    logger.info("=" * 70)
    logger.info(f"Total time: {elapsed:.1f}s ({elapsed/60:.1f} minutes)")
    logger.info("")
    logger.info("Phase Results:")

    all_success = True
    for phase_num, success in results.items():
        status = "✓ Success" if success else "✗ Failed"
        logger.info(f"  Phase {phase_num}: {status}")
        if not success:
            all_success = False

    if all_success and not args.dry_run:
        logger.info("")
        logger.info("=" * 70)
        logger.info("✓ ALL PHASES COMPLETED SUCCESSFULLY")
        logger.info("=" * 70)
        logger.info("")
        logger.info("Results saved to:")
        logger.info("  - docs/08-projects/current/mlb-pitcher-strikeouts/TRUE-HIT-RATE-RESULTS.json")
        logger.info("  - docs/08-projects/current/mlb-pitcher-strikeouts/PITCHER-ANALYSIS-RESULTS.json")

    sys.exit(0 if all_success else 1)


if __name__ == "__main__":
    main()
