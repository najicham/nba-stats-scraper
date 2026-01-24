#!/usr/bin/env python3
"""
Fast Smoke Test - Validate pipeline health in <1 second per date

Checks all 6 phases for data existence without detailed analysis.
Perfect for quick validation after backfills.

Usage:
    # Single date
    python scripts/smoke_test.py 2026-01-20

    # Date range
    python scripts/smoke_test.py 2026-01-15 2026-01-20

    # With details
    python scripts/smoke_test.py 2026-01-20 --verbose

Output:
    ✅ 2026-01-20: P2:PASS P3:PASS P4:PASS P5:PASS P6:PASS [Overall: PASS]
    ❌ 2026-01-19: P2:PASS P3:PASS P4:FAIL P5:FAIL P6:FAIL [Overall: FAIL]
"""

import argparse
import sys
from datetime import datetime, timedelta
from typing import Dict, List
from google.cloud import bigquery

PROJECT_ID = "nba-props-platform"


class SmokeTest:
    """Fast smoke test validator"""

    def __init__(self, project_id: str = PROJECT_ID):
        self.bq_client = bigquery.Client(project=project_id)
        self.project_id = project_id

    def test_date(self, game_date: str, verbose: bool = False) -> Dict:
        """
        Test single date across all phases in <1 second

        Returns dict with PASS/FAIL for each phase
        """
        # Use parameterized query to prevent SQL injection
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("game_date", "STRING", game_date)]
        )

        # Single batch query checks all phases at once
        query = f"""
        SELECT
          -- Phase 2: Box scores exist (ANY source)
          IF(
            EXISTS(SELECT 1 FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
                   WHERE game_date = @game_date LIMIT 1)
            OR
            EXISTS(SELECT 1 FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
                   WHERE game_date = @game_date LIMIT 1),
            'PASS', 'FAIL'
          ) as phase2,

          -- Phase 3: Analytics exist
          IF(
            EXISTS(SELECT 1 FROM `{self.project_id}.nba_analytics.player_game_summary`
                   WHERE game_date = @game_date LIMIT 1),
            'PASS', 'FAIL'
          ) as phase3,

          -- Phase 4: Processors exist (>=3 required for PASS)
          CASE
            WHEN (
              IF(EXISTS(SELECT 1 FROM `{self.project_id}.nba_precompute.player_daily_cache`
                        WHERE cache_date = @game_date LIMIT 1), 1, 0) +
              IF(EXISTS(SELECT 1 FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
                        WHERE analysis_date = @game_date LIMIT 1), 1, 0) +
              IF(EXISTS(SELECT 1 FROM `{self.project_id}.nba_precompute.player_composite_factors`
                        WHERE game_date = @game_date LIMIT 1), 1, 0) +
              IF(EXISTS(SELECT 1 FROM `{self.project_id}.nba_precompute.team_defense_zone_analysis`
                        WHERE analysis_date = @game_date LIMIT 1), 1, 0)
            ) >= 3 THEN 'PASS'
            ELSE 'FAIL'
          END as phase4,

          -- Phase 5: Predictions exist
          IF(
            EXISTS(SELECT 1 FROM `{self.project_id}.nba_predictions.player_prop_predictions`
                   WHERE game_date = @game_date LIMIT 1),
            'PASS', 'FAIL'
          ) as phase5,

          -- Phase 6: Grading exists
          IF(
            EXISTS(SELECT 1 FROM `{self.project_id}.nba_predictions.prediction_grades`
                   WHERE game_date = @game_date LIMIT 1),
            'PASS', 'FAIL'
          ) as phase6,

          -- Verbose details (only if requested)
          {'1 as verbose_requested' if verbose else '0 as verbose_requested'}
        """

        try:
            result = list(self.bq_client.query(query, job_config=job_config).result())[0]

            return {
                'game_date': game_date,
                'phase2': result.phase2,
                'phase3': result.phase3,
                'phase4': result.phase4,
                'phase5': result.phase5,
                'phase6': result.phase6,
                'overall': 'PASS' if all([
                    result.phase2 == 'PASS',
                    result.phase3 == 'PASS',
                    result.phase4 == 'PASS',
                    result.phase5 == 'PASS',
                    result.phase6 == 'PASS'
                ]) else 'FAIL'
            }
        except Exception as e:
            return {
                'game_date': game_date,
                'phase2': 'ERROR',
                'phase3': 'ERROR',
                'phase4': 'ERROR',
                'phase5': 'ERROR',
                'phase6': 'ERROR',
                'overall': 'ERROR',
                'error': str(e)
            }

    def test_date_range(self, start_date: str, end_date: str, verbose: bool = False) -> List[Dict]:
        """Test multiple dates"""
        dates = self._get_dates_between(start_date, end_date)
        results = []

        for date in dates:
            result = self.test_date(date, verbose)
            results.append(result)

        return results

    def _get_dates_between(self, start: str, end: str) -> List[str]:
        """Generate list of dates between start and end (inclusive)"""
        start_dt = datetime.strptime(start, '%Y-%m-%d')
        end_dt = datetime.strptime(end, '%Y-%m-%d')

        dates = []
        current = start_dt
        while current <= end_dt:
            dates.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)

        return dates

    def print_results(self, results: List[Dict], verbose: bool = False):
        """Pretty print results"""
        if not results:
            print("No results to display")
            return

        # Summary stats
        total = len(results)
        passed = sum(1 for r in results if r['overall'] == 'PASS')
        failed = sum(1 for r in results if r['overall'] == 'FAIL')
        errors = sum(1 for r in results if r['overall'] == 'ERROR')

        # Print each date
        for r in results:
            status_icon = {
                'PASS': '✅',
                'FAIL': '❌',
                'ERROR': '⚠️'
            }.get(r['overall'], '❓')

            if verbose:
                print(f"\n{status_icon} {r['game_date']}:")
                print(f"  Phase 2 (Scrapers):    {r['phase2']}")
                print(f"  Phase 3 (Analytics):   {r['phase3']}")
                print(f"  Phase 4 (Precompute):  {r['phase4']}")
                print(f"  Phase 5 (Predictions): {r['phase5']}")
                print(f"  Phase 6 (Grading):     {r['phase6']}")
                if 'error' in r:
                    print(f"  Error: {r['error']}")
            else:
                phases = f"P2:{r['phase2']} P3:{r['phase3']} P4:{r['phase4']} P5:{r['phase5']} P6:{r['phase6']}"
                print(f"{status_icon} {r['game_date']}: {phases} [Overall: {r['overall']}]")

        # Summary
        if total > 1:
            print(f"\nSummary: {passed}/{total} passed ({passed/total*100:.1f}%), {failed} failed, {errors} errors")


def main():
    parser = argparse.ArgumentParser(
        description='Fast smoke test for NBA pipeline validation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single date
  python scripts/smoke_test.py 2026-01-20

  # Date range
  python scripts/smoke_test.py 2026-01-15 2026-01-20

  # Verbose output
  python scripts/smoke_test.py 2026-01-20 --verbose

  # After backfill, verify 10 dates
  python scripts/smoke_test.py 2026-01-10 2026-01-20
        """
    )
    parser.add_argument('start_date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('end_date', nargs='?', help='End date (YYYY-MM-DD), defaults to start_date')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output with details per phase')

    args = parser.parse_args()

    # Default end_date to start_date if not provided
    start_date = args.start_date
    end_date = args.end_date if args.end_date else args.start_date

    # Validate date format
    try:
        datetime.strptime(start_date, '%Y-%m-%d')
        datetime.strptime(end_date, '%Y-%m-%d')
    except ValueError:
        print("Error: Dates must be in YYYY-MM-DD format")
        sys.exit(1)

    # Run smoke test
    tester = SmokeTest()
    results = tester.test_date_range(start_date, end_date, args.verbose)
    tester.print_results(results, args.verbose)

    # Exit code based on results
    if any(r['overall'] == 'FAIL' for r in results):
        sys.exit(1)
    elif any(r['overall'] == 'ERROR' for r in results):
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
