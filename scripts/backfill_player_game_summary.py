#!/usr/bin/env python3
"""
FILE: scripts/backfill_player_game_summary.py

Backfill player_game_summary data for a date range with validation.

This script was created in response to the Nov 2025 - Jan 2026 data quality
issues where minutes_played and usage_rate fields had degraded coverage.

Usage:
    # Backfill Oct 2025 - Jan 2026 (the affected period)
    python scripts/backfill_player_game_summary.py --start-date 2025-10-01 --end-date 2026-01-26

    # Dry run (check without executing)
    python scripts/backfill_player_game_summary.py --start-date 2025-10-01 --end-date 2026-01-26 --dry-run

    # Force overwrite even if data looks good
    python scripts/backfill_player_game_summary.py --start-date 2025-10-01 --end-date 2026-01-26 --force

Features:
- Pre-check: Verifies team_offense_game_summary data exists (required for usage_rate)
- Pre-check: Shows current data quality before backfill
- Execution: Runs player_game_summary_processor with --backfill-mode
- Post-check: Validates improved coverage
- Reporting: Detailed before/after comparison
"""

import sys
import os
import argparse
from datetime import date, datetime, timedelta
from typing import Dict, Tuple
import subprocess

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from google.cloud import bigquery


class PlayerGameSummaryBackfiller:
    """Backfill player_game_summary with validation."""

    def __init__(self, start_date: date, end_date: date, dry_run: bool = False, force: bool = False):
        self.start_date = start_date
        self.end_date = end_date
        self.dry_run = dry_run
        self.force = force
        self.client = bigquery.Client()
        self.project = self.client.project

    def check_team_stats_availability(self) -> Tuple[bool, Dict]:
        """
        Check if team_offense_game_summary exists for date range.

        Returns:
            (bool, dict): (all_dates_covered, stats)
        """
        print(f"\n{'='*70}")
        print("PRE-CHECK 1: Team Stats Availability")
        print(f"{'='*70}")

        query = f"""
        WITH date_range AS (
            SELECT date
            FROM UNNEST(GENERATE_DATE_ARRAY('{self.start_date}', '{self.end_date}', INTERVAL 1 DAY)) AS date
        ),
        team_stats AS (
            SELECT
                game_date,
                COUNT(DISTINCT game_id) as games_with_team_stats
            FROM `{self.project}.nba_analytics.team_offense_game_summary`
            WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
            GROUP BY game_date
        ),
        schedule AS (
            SELECT
                game_date,
                COUNT(DISTINCT game_id) as scheduled_games
            FROM `{self.project}.nba_raw.nbac_schedule`
            WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
            GROUP BY game_date
        )
        SELECT
            dr.date,
            COALESCE(s.scheduled_games, 0) as scheduled_games,
            COALESCE(ts.games_with_team_stats, 0) as games_with_team_stats,
            CASE
                WHEN s.scheduled_games IS NULL THEN 'NO_GAMES'
                WHEN ts.games_with_team_stats >= s.scheduled_games THEN 'OK'
                WHEN ts.games_with_team_stats > 0 THEN 'PARTIAL'
                ELSE 'MISSING'
            END as status
        FROM date_range dr
        LEFT JOIN schedule s ON dr.date = s.game_date
        LEFT JOIN team_stats ts ON dr.date = ts.game_date
        ORDER BY dr.date
        """

        results = list(self.client.query(query).result(timeout=120))

        # Analyze results
        total_dates = len(results)
        dates_with_issues = []
        dates_ok = 0
        dates_no_games = 0

        for row in results:
            if row.status == 'NO_GAMES':
                dates_no_games += 1
            elif row.status == 'OK':
                dates_ok += 1
            else:
                dates_with_issues.append({
                    'date': str(row.date),
                    'scheduled': row.scheduled_games,
                    'has_team_stats': row.games_with_team_stats,
                    'status': row.status
                })

        print(f"\nDate range: {self.start_date} to {self.end_date} ({total_dates} days)")
        print(f"  ✓ Dates with full team stats: {dates_ok}")
        print(f"  - Dates with no games: {dates_no_games}")
        print(f"  ⚠️ Dates with issues: {len(dates_with_issues)}")

        if dates_with_issues:
            print(f"\nDates missing team stats:")
            for issue in dates_with_issues[:10]:  # Show first 10
                print(f"  {issue['date']}: {issue['has_team_stats']}/{issue['scheduled']} games ({issue['status']})")
            if len(dates_with_issues) > 10:
                print(f"  ... and {len(dates_with_issues) - 10} more")

        all_ok = len(dates_with_issues) == 0
        return all_ok, {
            'total_dates': total_dates,
            'dates_ok': dates_ok,
            'dates_no_games': dates_no_games,
            'dates_with_issues': len(dates_with_issues)
        }

    def check_current_data_quality(self) -> Dict:
        """
        Check current data quality in player_game_summary.

        Returns:
            dict: Coverage statistics
        """
        print(f"\n{'='*70}")
        print("PRE-CHECK 2: Current Data Quality")
        print(f"{'='*70}")

        query = f"""
        SELECT
            COUNT(*) as total_records,
            COUNTIF(minutes_played IS NOT NULL) as has_minutes,
            COUNTIF(usage_rate IS NOT NULL) as has_usage_rate,
            COUNTIF(source_team_last_updated IS NOT NULL) as has_team_join,
            ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL) / COUNT(*), 1) as minutes_pct,
            ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as usage_rate_pct,
            -- For active players only
            COUNTIF(minutes_played > 0) as active_players,
            COUNTIF(minutes_played > 0 AND usage_rate IS NOT NULL) as active_with_usage,
            ROUND(100.0 * COUNTIF(minutes_played > 0 AND usage_rate IS NOT NULL) / NULLIF(COUNTIF(minutes_played > 0), 0), 1) as active_usage_pct
        FROM `{self.project}.nba_analytics.player_game_summary`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
        """

        result = list(self.client.query(query).result(timeout=60))[0]

        stats = {
            'total_records': result.total_records,
            'minutes_pct': result.minutes_pct or 0,
            'usage_rate_pct': result.usage_rate_pct or 0,
            'active_usage_pct': result.active_usage_pct or 0,
            'has_team_join': result.has_team_join or 0
        }

        print(f"\nDate range: {self.start_date} to {self.end_date}")
        print(f"  Total records: {stats['total_records']:,}")
        print(f"  minutes_played coverage: {stats['minutes_pct']}%")
        print(f"  usage_rate coverage: {stats['usage_rate_pct']}% (all players)")
        print(f"  usage_rate coverage: {stats['active_usage_pct']}% (active players only)")
        print(f"  Team stats joined: {'Yes' if stats['has_team_join'] > 0 else 'No'} ({stats['has_team_join']} records)")

        # Assess if backfill is needed
        needs_backfill = (
            stats['minutes_pct'] < 95.0 or
            stats['active_usage_pct'] < 90.0
        )

        if needs_backfill:
            print(f"\n⚠️ Data quality is below thresholds - backfill recommended")
        else:
            print(f"\n✓ Data quality is good (minutes: {stats['minutes_pct']}%, usage: {stats['active_usage_pct']}%)")
            if not self.force:
                print(f"   Use --force to backfill anyway")

        return stats

    def run_backfill(self) -> bool:
        """
        Execute the player_game_summary processor for the date range.

        Returns:
            bool: True if successful
        """
        print(f"\n{'='*70}")
        print("EXECUTING BACKFILL")
        print(f"{'='*70}")

        if self.dry_run:
            print("\n[DRY RUN] Would execute:")
            print(f"  python -m data_processors.analytics.player_game_summary.player_game_summary_processor \\")
            print(f"      --start-date {self.start_date} --end-date {self.end_date} --backfill-mode")
            return True

        print(f"\nRunning player_game_summary_processor...")
        print(f"  Date range: {self.start_date} to {self.end_date}")
        print(f"  Mode: backfill (will overwrite existing data)")

        cmd = [
            'python', '-m',
            'data_processors.analytics.player_game_summary.player_game_summary_processor',
            '--start-date', str(self.start_date),
            '--end-date', str(self.end_date),
            '--backfill-mode'
        ]

        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                cwd=os.path.join(os.path.dirname(__file__), '..')
            )

            print(f"\n✓ Processor completed successfully")
            print(f"\nOutput (last 20 lines):")
            output_lines = result.stdout.strip().split('\n')
            for line in output_lines[-20:]:
                print(f"  {line}")

            return True

        except subprocess.CalledProcessError as e:
            print(f"\n❌ Processor failed with exit code {e.returncode}")
            print(f"\nError output:")
            print(e.stderr)
            return False

    def validate_results(self, before_stats: Dict) -> Dict:
        """
        Validate that backfill improved data quality.

        Args:
            before_stats: Stats from check_current_data_quality() before backfill

        Returns:
            dict: Comparison statistics
        """
        print(f"\n{'='*70}")
        print("POST-CHECK: Validation Results")
        print(f"{'='*70}")

        # Re-run quality check
        after_stats = self.check_current_data_quality()

        # Calculate improvements
        comparison = {
            'total_records_before': before_stats['total_records'],
            'total_records_after': after_stats['total_records'],
            'minutes_pct_before': before_stats['minutes_pct'],
            'minutes_pct_after': after_stats['minutes_pct'],
            'usage_pct_before': before_stats['active_usage_pct'],
            'usage_pct_after': after_stats['active_usage_pct'],
            'minutes_improvement': after_stats['minutes_pct'] - before_stats['minutes_pct'],
            'usage_improvement': after_stats['active_usage_pct'] - before_stats['active_usage_pct']
        }

        print(f"\n{'='*70}")
        print("COMPARISON: Before vs After")
        print(f"{'='*70}")

        print(f"\nminutes_played coverage:")
        print(f"  Before: {comparison['minutes_pct_before']}%")
        print(f"  After:  {comparison['minutes_pct_after']}%")
        print(f"  Change: {comparison['minutes_improvement']:+.1f} percentage points")

        print(f"\nusage_rate coverage (active players):")
        print(f"  Before: {comparison['usage_pct_before']}%")
        print(f"  After:  {comparison['usage_pct_after']}%")
        print(f"  Change: {comparison['usage_improvement']:+.1f} percentage points")

        # Assess success
        success = (
            comparison['minutes_pct_after'] >= 95.0 and
            comparison['usage_pct_after'] >= 90.0
        )

        if success:
            print(f"\n✅ BACKFILL SUCCESSFUL - Data quality meets thresholds")
        else:
            print(f"\n⚠️ BACKFILL COMPLETE - Data quality still below thresholds")
            if comparison['minutes_pct_after'] < 95.0:
                print(f"   - minutes_played: {comparison['minutes_pct_after']}% (target: 95%)")
            if comparison['usage_pct_after'] < 90.0:
                print(f"   - usage_rate: {comparison['usage_pct_after']}% (target: 90%)")

        return comparison

    def run(self) -> bool:
        """
        Run the full backfill workflow.

        Returns:
            bool: True if successful
        """
        print(f"\n{'='*70}")
        print(f"PLAYER GAME SUMMARY BACKFILL")
        print(f"{'='*70}")
        print(f"\nDate range: {self.start_date} to {self.end_date}")
        print(f"Mode: {'DRY RUN' if self.dry_run else 'EXECUTE'}")
        print(f"Force: {'Yes' if self.force else 'No'}")

        # Step 1: Check team stats availability
        team_stats_ok, team_stats = self.check_team_stats_availability()

        if not team_stats_ok and not self.force:
            print(f"\n❌ ABORTED: Team stats not available for all dates")
            print(f"   Run team_offense_game_summary processor first, or use --force to continue anyway")
            return False

        # Step 2: Check current data quality
        before_stats = self.check_current_data_quality()

        # Check if backfill is needed
        if before_stats['minutes_pct'] >= 95.0 and before_stats['active_usage_pct'] >= 90.0:
            if not self.force:
                print(f"\n✓ Data quality is already good - no backfill needed")
                print(f"   Use --force to backfill anyway")
                return True

        # Step 3: Execute backfill
        if not self.run_backfill():
            print(f"\n❌ BACKFILL FAILED")
            return False

        # Step 4: Validate results (skip if dry run)
        if not self.dry_run:
            comparison = self.validate_results(before_stats)

            print(f"\n{'='*70}")
            print("BACKFILL COMPLETE")
            print(f"{'='*70}")

            return True
        else:
            print(f"\n{'='*70}")
            print("DRY RUN COMPLETE")
            print(f"{'='*70}")
            return True


def main():
    parser = argparse.ArgumentParser(
        description='Backfill player_game_summary with validation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Backfill Oct 2025 - Jan 2026 (the affected period)
  python scripts/backfill_player_game_summary.py --start-date 2025-10-01 --end-date 2026-01-26

  # Dry run (check without executing)
  python scripts/backfill_player_game_summary.py --start-date 2025-10-01 --end-date 2026-01-26 --dry-run

  # Force backfill even if data looks good
  python scripts/backfill_player_game_summary.py --start-date 2025-10-01 --end-date 2026-01-26 --force
        """
    )

    parser.add_argument(
        '--start-date',
        type=str,
        required=True,
        help='Start date (YYYY-MM-DD)'
    )

    parser.add_argument(
        '--end-date',
        type=str,
        required=True,
        help='End date (YYYY-MM-DD)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Check what would be done without executing'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Force backfill even if data looks good or team stats missing'
    )

    args = parser.parse_args()

    # Parse dates
    try:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    except ValueError as e:
        print(f"❌ Invalid date format: {e}")
        print(f"   Use YYYY-MM-DD format")
        sys.exit(1)

    # Validate date range
    if start_date > end_date:
        print(f"❌ Invalid date range: start_date must be <= end_date")
        sys.exit(1)

    if (end_date - start_date).days > 365:
        print(f"❌ Date range too large: {(end_date - start_date).days} days")
        print(f"   Maximum: 365 days")
        sys.exit(1)

    # Run backfill
    backfiller = PlayerGameSummaryBackfiller(
        start_date=start_date,
        end_date=end_date,
        dry_run=args.dry_run,
        force=args.force
    )

    success = backfiller.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
