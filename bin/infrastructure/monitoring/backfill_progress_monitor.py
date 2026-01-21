#!/usr/bin/env python3
"""
Backfill Progress Monitor

Real-time monitoring for Phase 3 and Phase 4 backfill execution.
Tracks progress across all tables, detects failures, estimates completion.

Usage:
    # Single check
    python backfill_progress_monitor.py

    # Continuous monitoring (refresh every 30 seconds)
    python backfill_progress_monitor.py --continuous

    # Custom refresh interval
    python backfill_progress_monitor.py --continuous --interval 60

    # Show only failures
    python backfill_progress_monitor.py --failures-only

    # Focus on specific season
    python backfill_progress_monitor.py --season 2023-24

    # Show detailed table breakdown
    python backfill_progress_monitor.py --detailed

Features:
- Overall progress by phase (Phase 3, Phase 4)
- Season-by-season breakdown
- Table-level progress tracking
- Recent failure detection
- Processing rate estimation
- Bootstrap period tracking (Phase 4)
- Continuous monitoring mode

Created: 2025-11-30
Version: 1.0
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from google.cloud import bigquery

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

# Initialize BigQuery client
PROJECT_ID = 'nba-props-platform'
bq_client = bigquery.Client(project=PROJECT_ID)

# Phase 3 Analytics Tables (5 processors)
PHASE3_TABLES = [
    'player_game_summary',
    'team_defense_game_summary',
    'team_offense_game_summary',
    'upcoming_player_game_context',
    'upcoming_team_game_context',
]

# Phase 4 Precompute Tables (5 backfill jobs)
# Map table name -> date field
PHASE4_TABLES = {
    'team_defense_zone_analysis': 'analysis_date',
    'player_shot_zone_analysis': 'analysis_date',
    'player_composite_factors': 'game_date',
    'player_daily_cache': 'cache_date',
    # 'ml_feature_store': 'feature_date',  # Commented - verify field name
}

# Date ranges for backfill (4 years)
BACKFILL_START = '2021-10-01'
BACKFILL_END = '2024-11-29'

# Season definitions
SEASONS = [
    {'name': '2021-22', 'start': '2021-10-01', 'end': '2022-06-30'},
    {'name': '2022-23', 'start': '2022-10-01', 'end': '2023-06-30'},
    {'name': '2023-24', 'start': '2023-10-01', 'end': '2024-06-30'},
    {'name': '2024-25', 'start': '2024-10-01', 'end': '2024-11-29'},
]


class BackfillProgressMonitor:
    """Monitor backfill progress across Phase 3 and Phase 4."""

    def __init__(self, season_filter: Optional[str] = None):
        self.client = bq_client
        self.season_filter = season_filter
        self.start_time = datetime.now()

    def get_expected_dates(self, season: Optional[str] = None) -> int:
        """Get expected number of game dates from schedule."""
        if season:
            season_info = next((s for s in SEASONS if s['name'] == season), None)
            if not season_info:
                return 0
            start, end = season_info['start'], season_info['end']
        else:
            start, end = BACKFILL_START, BACKFILL_END

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", start),
                bigquery.ScalarQueryParameter("end_date", "DATE", end),
            ]
        )
        query = f"""
        SELECT COUNT(DISTINCT game_date) as total
        FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
        WHERE game_status = 3
          AND game_date BETWEEN @start_date AND @end_date
        """
        result = self.client.query(query, job_config=job_config).result(timeout=60)
        return next(result).total

    def get_phase_progress(self, phase: str, tables, date_field: str = 'game_date',
                          season: Optional[str] = None) -> Dict:
        """Get progress for a phase across all tables.

        Args:
            phase: 'Phase 3' or 'Phase 4'
            tables: List of table names (Phase 3) or Dict mapping table -> date_field (Phase 4)
            date_field: Default date field (used for Phase 3)
            season: Optional season filter
        """
        if season:
            season_info = next((s for s in SEASONS if s['name'] == season), None)
            if not season_info:
                return {}
            start, end = season_info['start'], season_info['end']
        else:
            start, end = BACKFILL_START, BACKFILL_END

        dataset = 'nba_analytics' if phase == 'Phase 3' else 'nba_precompute'

        progress = {
            'phase': phase,
            'tables': {},
            'total_dates': 0,
            'expected_dates': self.get_expected_dates(season),
        }

        # Handle both list (Phase 3) and dict (Phase 4) table definitions
        if isinstance(tables, dict):
            table_items = tables.items()
        else:
            table_items = [(t, date_field) for t in tables]

        for table, field in table_items:
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("start_date", "DATE", start),
                    bigquery.ScalarQueryParameter("end_date", "DATE", end),
                ]
            )
            query = f"""
            SELECT COUNT(DISTINCT {field}) as dates
            FROM `{PROJECT_ID}.{dataset}.{table}`
            WHERE {field} BETWEEN @start_date AND @end_date
            """
            try:
                result = self.client.query(query, job_config=job_config).result(timeout=60)
                dates = next(result).dates
                progress['tables'][table] = dates
                # Use max for overall phase progress (tables should converge)
                progress['total_dates'] = max(progress['total_dates'], dates)
            except Exception as e:
                progress['tables'][table] = f"Error: {str(e)[:50]}"

        return progress

    def get_recent_failures(self, hours: int = 2, limit: int = 20) -> List[Dict]:
        """Get recent processor failures from run history."""
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("hours", "INT64", hours),
                bigquery.ScalarQueryParameter("limit", "INT64", limit),
            ]
        )
        query = f"""
        SELECT
            data_date,
            processor_name,
            status,
            started_at,
            duration_seconds,
            SUBSTR(TO_JSON_STRING(errors), 1, 150) as error_msg
        FROM `{PROJECT_ID}.nba_reference.processor_run_history`
        WHERE status = 'failed'
          AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
        ORDER BY started_at DESC
        LIMIT @limit
        """
        result = self.client.query(query, job_config=job_config).result(timeout=60)
        return [dict(row) for row in result]

    def get_processing_rate(self, phase: str, hours: int = 1) -> Dict:
        """Calculate processing rate over last N hours."""
        dataset = 'nba_analytics' if phase == 'Phase 3' else 'nba_precompute'
        table = PHASE3_TABLES[0] if phase == 'Phase 3' else list(PHASE4_TABLES.keys())[0]
        table_search = table.replace('_', '')

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("hours", "INT64", hours),
                bigquery.ScalarQueryParameter("table_pattern", "STRING", f'%{table_search}%'),
            ]
        )
        query = f"""
        WITH recent_runs AS (
            SELECT
                data_date,
                started_at,
                processor_name,
                status
            FROM `{PROJECT_ID}.nba_reference.processor_run_history`
            WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
              AND processor_name LIKE @table_pattern
              AND status = 'success'
        )
        SELECT
            COUNT(DISTINCT data_date) as dates_processed,
            COUNT(*) as total_runs,
            MIN(started_at) as first_run,
            MAX(started_at) as last_run
        FROM recent_runs
        """
        try:
            result = self.client.query(query, job_config=job_config).result(timeout=60)
            row = next(result)
            return {
                'dates_processed': row.dates_processed,
                'total_runs': row.total_runs,
                'first_run': row.first_run,
                'last_run': row.last_run,
            }
        except Exception:
            return {'dates_processed': 0, 'total_runs': 0}

    def get_season_breakdown(self) -> List[Dict]:
        """Get progress breakdown by season."""
        breakdown = []
        for season in SEASONS:
            phase3 = self.get_phase_progress('Phase 3', PHASE3_TABLES, season=season['name'])
            phase4 = self.get_phase_progress('Phase 4', PHASE4_TABLES, season=season['name'])

            breakdown.append({
                'season': season['name'],
                'expected': phase3['expected_dates'],
                'phase3_complete': phase3['total_dates'],
                'phase4_complete': phase4['total_dates'],
                'phase3_pct': round(100.0 * phase3['total_dates'] / phase3['expected_dates'], 1) if phase3['expected_dates'] > 0 else 0,
                'phase4_pct': round(100.0 * phase4['total_dates'] / phase4['expected_dates'], 1) if phase4['expected_dates'] > 0 else 0,
            })

        return breakdown

    def estimate_completion(self, current: int, expected: int, rate_per_hour: float) -> str:
        """Estimate time to completion based on processing rate."""
        if rate_per_hour == 0:
            return "Unknown (no recent activity)"

        remaining = expected - current
        if remaining <= 0:
            return "Complete!"

        hours_remaining = remaining / rate_per_hour

        if hours_remaining < 1:
            return f"{int(hours_remaining * 60)} minutes"
        elif hours_remaining < 24:
            return f"{hours_remaining:.1f} hours"
        else:
            days = hours_remaining / 24
            return f"{days:.1f} days"

    def print_header(self):
        """Print monitor header."""
        print("\n" + "="*80)
        print("🔍 NBA BACKFILL PROGRESS MONITOR")
        print(f"📅 Target: {BACKFILL_START} to {BACKFILL_END}")
        print(f"⏰ Checked: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if self.season_filter:
            print(f"🎯 Season Filter: {self.season_filter}")
        print("="*80)

    def print_overall_progress(self):
        """Print overall progress summary."""
        print("\n📊 OVERALL PROGRESS")
        print("-" * 80)

        phase3 = self.get_phase_progress('Phase 3', PHASE3_TABLES, season=self.season_filter)
        phase4 = self.get_phase_progress('Phase 4', PHASE4_TABLES, season=self.season_filter)

        expected = phase3['expected_dates']

        # Phase 3
        p3_pct = round(100.0 * phase3['total_dates'] / expected, 1) if expected > 0 else 0
        p3_bar = self._progress_bar(p3_pct)
        print(f"\n🔵 Phase 3 (Analytics): {phase3['total_dates']}/{expected} dates ({p3_pct}%)")
        print(f"   {p3_bar}")

        # Phase 4
        p4_pct = round(100.0 * phase4['total_dates'] / expected, 1) if expected > 0 else 0
        p4_bar = self._progress_bar(p4_pct)
        print(f"\n🟣 Phase 4 (Precompute): {phase4['total_dates']}/{expected} dates ({p4_pct}%)")
        print(f"   {p4_bar}")
        print(f"   Note: Bootstrap periods (first 7 days) are intentionally skipped")

    def print_table_progress(self, detailed: bool = False):
        """Print progress for each table."""
        if not detailed:
            return

        print("\n📋 TABLE-LEVEL PROGRESS")
        print("-" * 80)

        # Phase 3 tables
        print("\n🔵 Phase 3 Analytics:")
        phase3 = self.get_phase_progress('Phase 3', PHASE3_TABLES, season=self.season_filter)
        expected = phase3['expected_dates']

        for table, dates in sorted(phase3['tables'].items()):
            if isinstance(dates, int):
                pct = round(100.0 * dates / expected, 1) if expected > 0 else 0
                status = "✅" if pct == 100.0 else "⏳"
                print(f"   {status} {table:40s} {dates:4d}/{expected} ({pct:5.1f}%)")
            else:
                print(f"   ❌ {table:40s} {dates}")

        # Phase 4 tables
        print("\n🟣 Phase 4 Precompute:")
        phase4 = self.get_phase_progress('Phase 4', PHASE4_TABLES, season=self.season_filter)

        for table, dates in sorted(phase4['tables'].items()):
            if isinstance(dates, int):
                pct = round(100.0 * dates / expected, 1) if expected > 0 else 0
                status = "✅" if pct >= 95.0 else "⏳"  # 95%+ acceptable due to bootstrap skip
                print(f"   {status} {table:40s} {dates:4d}/{expected} ({pct:5.1f}%)")
            else:
                print(f"   ❌ {table:40s} {dates}")

    def print_season_breakdown(self):
        """Print season-by-season breakdown."""
        print("\n🗓️  SEASON-BY-SEASON BREAKDOWN")
        print("-" * 80)
        print(f"{'Season':<12} {'Expected':>10} {'Phase 3':>12} {'Phase 4':>12} {'P3 %':>8} {'P4 %':>8}")
        print("-" * 80)

        breakdown = self.get_season_breakdown()
        for season in breakdown:
            print(f"{season['season']:<12} {season['expected']:>10} "
                  f"{season['phase3_complete']:>12} {season['phase4_complete']:>12} "
                  f"{season['phase3_pct']:>7.1f}% {season['phase4_pct']:>7.1f}%")

    def print_recent_failures(self, limit: int = 10):
        """Print recent failures."""
        failures = self.get_recent_failures(hours=2, limit=limit)

        if not failures:
            print("\n✅ NO RECENT FAILURES (last 2 hours)")
            return

        print(f"\n⚠️  RECENT FAILURES (last 2 hours, showing {len(failures)})")
        print("-" * 80)

        for f in failures[:limit]:
            print(f"\n❌ {f['processor_name']}")
            print(f"   Date: {f['data_date']}")
            print(f"   Time: {f['started_at']}")
            print(f"   Error: {f['error_msg']}")

    def print_processing_rate(self):
        """Print current processing rate and estimates."""
        print("\n⚡ PROCESSING RATE")
        print("-" * 80)

        # Get rates for last hour
        p3_rate = self.get_processing_rate('Phase 3', hours=1)
        p4_rate = self.get_processing_rate('Phase 4', hours=1)

        # Phase 3
        p3_dates_per_hour = p3_rate['dates_processed']
        print(f"\n🔵 Phase 3: {p3_dates_per_hour} dates/hour (last 1 hour)")
        if p3_dates_per_hour > 0:
            phase3 = self.get_phase_progress('Phase 3', PHASE3_TABLES, season=self.season_filter)
            expected = phase3['expected_dates']
            remaining = expected - phase3['total_dates']
            if remaining > 0:
                est = self.estimate_completion(phase3['total_dates'], expected, p3_dates_per_hour)
                print(f"   Remaining: {remaining} dates")
                print(f"   ETA: {est}")

        # Phase 4
        p4_dates_per_hour = p4_rate['dates_processed']
        print(f"\n🟣 Phase 4: {p4_dates_per_hour} dates/hour (last 1 hour)")
        if p4_dates_per_hour > 0:
            phase4 = self.get_phase_progress('Phase 4', PHASE4_TABLES,
                                            date_field='analysis_date', season=self.season_filter)
            expected = phase4['expected_dates']
            remaining = expected - phase4['total_dates']
            if remaining > 0:
                est = self.estimate_completion(phase4['total_dates'], expected, p4_dates_per_hour)
                print(f"   Remaining: {remaining} dates")
                print(f"   ETA: {est}")

    def print_summary(self, detailed: bool = False, failures_only: bool = False):
        """Print complete monitoring summary."""
        if failures_only:
            self.print_header()
            self.print_recent_failures(limit=20)
            return

        self.print_header()
        self.print_overall_progress()

        if detailed:
            self.print_table_progress(detailed=True)

        self.print_season_breakdown()
        self.print_processing_rate()
        self.print_recent_failures(limit=5)

        print("\n" + "="*80 + "\n")

    def _progress_bar(self, percent: float, width: int = 50) -> str:
        """Generate a text progress bar."""
        filled = int(width * percent / 100)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}] {percent:.1f}%"


def main():
    parser = argparse.ArgumentParser(
        description='Monitor NBA backfill progress across Phase 3 and Phase 4',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single check
  python backfill_progress_monitor.py

  # Continuous monitoring (30 second refresh)
  python backfill_progress_monitor.py --continuous

  # Custom interval
  python backfill_progress_monitor.py --continuous --interval 60

  # Show failures only
  python backfill_progress_monitor.py --failures-only

  # Detailed table breakdown
  python backfill_progress_monitor.py --detailed

  # Focus on specific season
  python backfill_progress_monitor.py --season 2023-24
        """
    )

    parser.add_argument('--continuous', action='store_true',
                       help='Run continuously with periodic refresh')
    parser.add_argument('--interval', type=int, default=30,
                       help='Refresh interval in seconds (default: 30)')
    parser.add_argument('--detailed', action='store_true',
                       help='Show detailed table-level progress')
    parser.add_argument('--failures-only', action='store_true',
                       help='Show only recent failures')
    parser.add_argument('--season', type=str,
                       help='Filter by season (e.g., 2023-24)')

    args = parser.parse_args()

    monitor = BackfillProgressMonitor(season_filter=args.season)

    if args.continuous:
        print(f"Starting continuous monitoring (refresh every {args.interval}s)")
        print("Press Ctrl+C to stop\n")

        try:
            while True:
                # Clear screen (cross-platform)
                os.system('clear' if os.name == 'posix' else 'cls')
                monitor.print_summary(detailed=args.detailed, failures_only=args.failures_only)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n\nMonitoring stopped by user")
            sys.exit(0)
    else:
        monitor.print_summary(detailed=args.detailed, failures_only=args.failures_only)


if __name__ == '__main__':
    main()
