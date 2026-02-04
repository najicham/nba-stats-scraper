#!/usr/bin/env python3
"""
Reconcile Phase 3 completion tracking.

Finds dates where:
- Actual processor count != _completed_count
- All 5 processors present but _triggered = False

Created: 2026-02-04 (Session 116)
Purpose: Fix orchestrator Firestore tracking failures

Usage:
    # Preview issues
    python bin/maintenance/reconcile_phase3_completion.py --days 7

    # Fix issues
    python bin/maintenance/reconcile_phase3_completion.py --days 7 --fix

    # Verbose output
    python bin/maintenance/reconcile_phase3_completion.py --days 7 --fix --verbose
"""

import argparse
import sys
from datetime import datetime, timedelta
from typing import List, Dict
from google.cloud import firestore

# Expected processors for Phase 3
EXPECTED_PROCESSORS = 5
PROCESSOR_NAMES = [
    'player_game_summary',
    'team_offense_game_summary',
    'team_defense_game_summary',
    'upcoming_player_game_context',
    'upcoming_team_game_context'
]


def reconcile_completion(days_back: int = 7, fix: bool = False, verbose: bool = False) -> List[Dict]:
    """
    Reconcile Phase 3 completion tracking.

    Args:
        days_back: How many days to check
        fix: Whether to fix issues (default: False, just report)
        verbose: Print detailed information

    Returns:
        List of issues found
    """
    db = firestore.Client(project='nba-props-platform')
    issues = []

    print(f"\n{'='*80}")
    print(f"Phase 3 Completion Reconciliation")
    print(f"Checking last {days_back} days...")
    print(f"Mode: {'FIX' if fix else 'REPORT ONLY'}")
    print(f"{'='*80}\n")

    for i in range(days_back):
        date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        doc = db.collection('phase3_completion').document(date).get()

        if not doc.exists:
            if verbose:
                print(f"  {date}: No completion document (no games or not processed yet)")
            continue

        data = doc.to_dict()

        # Calculate actual vs stored counts
        actual_processors = [k for k in data.keys() if not k.startswith('_')]
        actual = len(actual_processors)
        stored = data.get('_completed_count', 0)
        triggered = data.get('_triggered', False)
        mode = data.get('_mode', 'unknown')

        # Check for issues
        has_mismatch = actual != stored
        has_untriggered = actual >= EXPECTED_PROCESSORS and not triggered

        if has_mismatch or has_untriggered:
            issue = {
                'date': date,
                'actual': actual,
                'stored': stored,
                'triggered': triggered,
                'mode': mode,
                'processors': actual_processors,
                'mismatch': has_mismatch,
                'untriggered': has_untriggered
            }
            issues.append(issue)

            # Print issue details
            status_parts = []
            if has_mismatch:
                status_parts.append(f"COUNT MISMATCH (actual:{actual} stored:{stored})")
            if has_untriggered:
                status_parts.append(f"NOT TRIGGERED ({actual}/{EXPECTED_PROCESSORS} complete)")

            status = " + ".join(status_parts)
            print(f"  ⚠️  {date}: {status}")

            if verbose:
                print(f"      Mode: {mode}")
                print(f"      Processors: {', '.join(actual_processors)}")

                # Check which processors are missing if not complete
                if actual < EXPECTED_PROCESSORS:
                    missing = set(PROCESSOR_NAMES) - set(actual_processors)
                    if missing:
                        print(f"      Missing: {', '.join(missing)}")

            # Fix if requested
            if fix:
                try:
                    update_data = {
                        '_completed_count': actual,
                        '_last_update': firestore.SERVER_TIMESTAMP,
                        '_reconciliation_fix': datetime.now(tz=firestore.SERVER_TIMESTAMP.tzinfo).isoformat()
                    }

                    # Trigger if complete but not triggered
                    if actual >= EXPECTED_PROCESSORS and not triggered:
                        update_data['_triggered'] = True
                        update_data['_trigger_reason'] = 'reconciliation_fix'

                    db.collection('phase3_completion').document(date).update(update_data)
                    print(f"      ✅ Fixed")

                except Exception as e:
                    print(f"      ❌ Fix failed: {e}")
        else:
            if verbose:
                print(f"  ✅ {date}: OK (actual:{actual} stored:{stored} triggered:{triggered})")

    # Summary
    print(f"\n{'='*80}")
    print(f"Summary:")
    print(f"  Dates checked: {days_back}")
    print(f"  Issues found: {len(issues)}")

    if issues:
        mismatch_count = sum(1 for i in issues if i['mismatch'])
        untriggered_count = sum(1 for i in issues if i['untriggered'])

        print(f"    - Count mismatches: {mismatch_count}")
        print(f"    - Untriggered (complete): {untriggered_count}")

        if fix:
            print(f"\n  ✅ All issues fixed!")
        else:
            print(f"\n  Run with --fix to apply fixes")
    else:
        print(f"  ✅ No issues found - all dates are consistent")

    print(f"{'='*80}\n")

    return issues


def main():
    parser = argparse.ArgumentParser(
        description='Reconcile Phase 3 completion tracking',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check last 7 days
  python bin/maintenance/reconcile_phase3_completion.py --days 7

  # Fix issues in last 7 days
  python bin/maintenance/reconcile_phase3_completion.py --days 7 --fix

  # Check last 30 days with verbose output
  python bin/maintenance/reconcile_phase3_completion.py --days 30 --verbose
        """
    )
    parser.add_argument(
        '--days',
        type=int,
        default=7,
        help='Number of days to check (default: 7)'
    )
    parser.add_argument(
        '--fix',
        action='store_true',
        help='Fix issues (default: report only)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Print detailed information'
    )

    args = parser.parse_args()

    # Validate days
    if args.days < 1 or args.days > 365:
        print(f"Error: --days must be between 1 and 365")
        sys.exit(1)

    try:
        issues = reconcile_completion(
            days_back=args.days,
            fix=args.fix,
            verbose=args.verbose
        )

        # Exit code: 0 if no issues, 1 if issues found
        sys.exit(1 if issues and not args.fix else 0)

    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)


if __name__ == '__main__':
    main()
