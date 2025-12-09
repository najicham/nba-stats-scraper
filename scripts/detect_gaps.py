#!/usr/bin/env python3
"""
Comprehensive Gap Detection Script

Detects and analyzes data gaps across all processing phases with cascade impact analysis.

Features:
- Phase 2-5 date-level gap detection
- Consecutive gap range identification
- Field-level contamination detection (NULL/zero critical fields)
- Cascade impact analysis (which downstream processors are blocked)
- Actionable recovery commands

Usage:
    # Check all phases for a date range
    python scripts/detect_gaps.py --start-date 2021-12-01 --end-date 2021-12-31

    # Check specific phase only
    python scripts/detect_gaps.py --start-date 2021-12-01 --end-date 2021-12-31 --phase 3

    # Include field-level contamination check
    python scripts/detect_gaps.py --start-date 2021-12-01 --end-date 2021-12-31 --check-contamination

    # Generate recovery commands
    python scripts/detect_gaps.py --start-date 2021-12-01 --end-date 2021-12-31 --generate-commands

    # Output as JSON for automation
    python scripts/detect_gaps.py --start-date 2021-12-01 --end-date 2021-12-31 --json
"""

import os
import sys
import argparse
import json
import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, asdict
from collections import defaultdict

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import bigquery

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Phase configuration with tables and dependencies
PHASE_CONFIG = {
    2: {
        'name': 'Raw Data',
        'tables': {
            'nbac_gamebook_player_stats': {
                'dataset': 'nba_raw',
                'date_column': 'game_date',
                'critical_fields': ['points', 'player_lookup'],
                'min_records_per_game_day': 50,  # ~2 teams * ~13 players
            },
            'bdl_player_boxscores': {
                'dataset': 'nba_raw',
                'date_column': 'game_date',
                'critical_fields': ['pts', 'player_lookup'],
                'min_records_per_game_day': 50,
            },
            'bigdataball_play_by_play': {
                'dataset': 'nba_raw',
                'date_column': 'game_date',
                'critical_fields': ['event_type', 'shot_distance'],
                'min_records_per_game_day': 200,  # ~100 plays per game
            },
        },
        'upstream': [],
    },
    3: {
        'name': 'Analytics',
        'tables': {
            'player_game_summary': {
                'dataset': 'nba_analytics',
                'date_column': 'game_date',
                'critical_fields': ['points', 'paint_attempts', 'assisted_fg_makes', 'paint_blocks'],
                'min_records_per_game_day': 50,
            },
            'team_defense_game_summary': {
                'dataset': 'nba_analytics',
                'date_column': 'game_date',
                'critical_fields': ['points_allowed', 'opp_paint_attempts', 'blocks_paint'],
                'min_records_per_game_day': 2,  # 2 teams per game minimum
            },
            'team_offense_game_summary': {
                'dataset': 'nba_analytics',
                'date_column': 'game_date',
                'critical_fields': ['points_scored', 'team_paint_attempts'],
                'min_records_per_game_day': 2,
            },
            'upcoming_player_game_context': {
                'dataset': 'nba_analytics',
                'date_column': 'game_date',
                'critical_fields': ['points_avg_last_5', 'days_rest'],
                'min_records_per_game_day': 50,
            },
        },
        'upstream': [2],
    },
    4: {
        'name': 'Precompute',
        'tables': {
            'team_defense_zone_analysis': {
                'dataset': 'nba_precompute',
                'date_column': 'analysis_date',
                'critical_fields': ['paint_pct_allowed_last_15', 'paint_defense_vs_league_avg'],
                'min_records_per_game_day': 2,
            },
            'player_shot_zone_analysis': {
                'dataset': 'nba_precompute',
                'date_column': 'analysis_date',
                'critical_fields': ['paint_rate_last_10', 'primary_scoring_zone'],
                'min_records_per_game_day': 20,
            },
            'player_composite_factors': {
                'dataset': 'nba_precompute',
                'date_column': 'analysis_date',
                'critical_fields': ['fatigue_score', 'shot_zone_mismatch_score'],
                'min_records_per_game_day': 20,
            },
            'player_daily_cache': {
                'dataset': 'nba_precompute',
                'date_column': 'cache_date',
                'critical_fields': ['points_avg_last_10', 'games_played_season'],
                'min_records_per_game_day': 20,
            },
        },
        'upstream': [3],
    },
    5: {
        'name': 'ML Features',
        'tables': {
            'ml_feature_store_v2': {
                'dataset': 'nba_predictions',
                'date_column': 'feature_date',
                'critical_fields': ['feature_vector', 'feature_quality_score'],
                'min_records_per_game_day': 20,
            },
        },
        'upstream': [4],
    },
}

# Cascade dependency map: downstream -> upstream dependencies
CASCADE_DEPENDENCIES = {
    'team_defense_zone_analysis': ['team_defense_game_summary'],
    'player_shot_zone_analysis': ['player_game_summary'],
    'player_composite_factors': ['upcoming_player_game_context', 'player_shot_zone_analysis', 'team_defense_zone_analysis'],
    'player_daily_cache': ['player_game_summary', 'upcoming_player_game_context', 'player_shot_zone_analysis'],
    'ml_feature_store_v2': ['player_daily_cache', 'player_composite_factors', 'player_shot_zone_analysis', 'team_defense_zone_analysis'],
}


@dataclass
class GapInfo:
    """Information about a detected gap."""
    table: str
    phase: int
    gap_type: str  # 'missing', 'low_records', 'contaminated'
    start_date: date
    end_date: date
    days_affected: int
    details: Dict
    downstream_impact: List[str]
    priority: str  # 'critical', 'high', 'medium', 'low'


@dataclass
class GapReport:
    """Complete gap detection report."""
    start_date: date
    end_date: date
    total_expected_days: int
    phases_checked: List[int]
    gaps: List[GapInfo]
    cascade_analysis: Dict
    recovery_commands: List[str]
    summary: Dict


class GapDetector:
    """Detects and analyzes data gaps across all processing phases."""

    def __init__(self, project_id: str = 'nba-props-platform'):
        self.project_id = project_id
        self.bq_client = bigquery.Client(project=project_id)
        self.game_dates_cache: Dict[str, Set[date]] = {}

    def get_expected_game_dates(self, start_date: date, end_date: date) -> Set[date]:
        """Get expected game dates from schedule."""
        cache_key = f"{start_date}_{end_date}"
        if cache_key in self.game_dates_cache:
            return self.game_dates_cache[cache_key]

        query = f"""
        SELECT DISTINCT game_date
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        ORDER BY game_date
        """
        try:
            df = self.bq_client.query(query).to_dataframe()
            dates = set(df['game_date'].dt.date if hasattr(df['game_date'].iloc[0], 'date') else df['game_date'])
            self.game_dates_cache[cache_key] = dates
            return dates
        except Exception as e:
            logger.warning(f"Could not get game dates from schedule: {e}")
            # Fallback: assume all dates are game dates
            dates = set()
            current = start_date
            while current <= end_date:
                dates.add(current)
                current += timedelta(days=1)
            return dates

    def get_table_date_coverage(self, table: str, config: Dict, start_date: date, end_date: date) -> Dict:
        """Get date coverage for a specific table."""
        dataset = config['dataset']
        date_col = config['date_column']

        query = f"""
        SELECT
            {date_col} as check_date,
            COUNT(*) as record_count
        FROM `{self.project_id}.{dataset}.{table}`
        WHERE {date_col} BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY {date_col}
        ORDER BY {date_col}
        """

        try:
            df = self.bq_client.query(query).to_dataframe()
            coverage = {}
            for _, row in df.iterrows():
                d = row['check_date'].date() if hasattr(row['check_date'], 'date') else row['check_date']
                coverage[d] = int(row['record_count'])
            return coverage
        except Exception as e:
            logger.error(f"Error checking {table}: {e}")
            return {}

    def check_field_contamination(self, table: str, config: Dict, start_date: date, end_date: date) -> Dict:
        """Check for NULL/zero values in critical fields."""
        dataset = config['dataset']
        date_col = config['date_column']
        critical_fields = config.get('critical_fields', [])

        if not critical_fields:
            return {}

        # Build field check expressions
        field_checks = []
        for field in critical_fields:
            field_checks.append(f"COUNTIF({field} IS NULL) as {field}_null")
            field_checks.append(f"COUNT(*) as total_records")

        field_expr = ", ".join(field_checks)

        query = f"""
        SELECT
            {date_col} as check_date,
            {field_expr}
        FROM `{self.project_id}.{dataset}.{table}`
        WHERE {date_col} BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY {date_col}
        ORDER BY {date_col}
        """

        try:
            df = self.bq_client.query(query).to_dataframe()
            contamination = {}
            for _, row in df.iterrows():
                d = row['check_date'].date() if hasattr(row['check_date'], 'date') else row['check_date']
                total = row['total_records']
                issues = {}
                for field in critical_fields:
                    null_count = row.get(f'{field}_null', 0)
                    if null_count > 0:
                        pct = (null_count / total) * 100 if total > 0 else 100
                        if pct > 10:  # Flag if >10% NULL
                            issues[field] = {'null_count': int(null_count), 'null_pct': round(pct, 1)}
                if issues:
                    contamination[d] = issues
            return contamination
        except Exception as e:
            logger.warning(f"Error checking contamination for {table}: {e}")
            return {}

    def find_consecutive_gaps(self, missing_dates: List[date]) -> List[Tuple[date, date, int]]:
        """Group missing dates into consecutive ranges."""
        if not missing_dates:
            return []

        sorted_dates = sorted(missing_dates)
        ranges = []
        range_start = sorted_dates[0]
        range_end = sorted_dates[0]

        for d in sorted_dates[1:]:
            if (d - range_end).days == 1:
                range_end = d
            else:
                ranges.append((range_start, range_end, (range_end - range_start).days + 1))
                range_start = d
                range_end = d

        ranges.append((range_start, range_end, (range_end - range_start).days + 1))
        return ranges

    def get_downstream_impact(self, table: str) -> List[str]:
        """Get list of downstream tables affected by a gap in this table."""
        impacted = []
        for downstream, upstreams in CASCADE_DEPENDENCIES.items():
            if table in upstreams:
                impacted.append(downstream)
                # Recursively find further downstream impact
                impacted.extend(self.get_downstream_impact(downstream))
        return list(set(impacted))

    def calculate_priority(self, gap: GapInfo) -> str:
        """Calculate priority based on gap characteristics."""
        # More downstream impact = higher priority
        if len(gap.downstream_impact) >= 3:
            return 'critical'
        elif len(gap.downstream_impact) >= 1:
            return 'high'
        elif gap.gap_type == 'missing':
            return 'high'
        elif gap.gap_type == 'contaminated':
            return 'medium'
        else:
            return 'low'

    def detect_gaps(
        self,
        start_date: date,
        end_date: date,
        phases: Optional[List[int]] = None,
        check_contamination: bool = False
    ) -> GapReport:
        """Detect all gaps in the specified date range."""
        if phases is None:
            phases = [2, 3, 4, 5]

        expected_dates = self.get_expected_game_dates(start_date, end_date)
        logger.info(f"Found {len(expected_dates)} expected game dates in range")

        all_gaps = []
        cascade_analysis = defaultdict(list)

        for phase in phases:
            if phase not in PHASE_CONFIG:
                continue

            phase_config = PHASE_CONFIG[phase]
            logger.info(f"\n{'='*60}")
            logger.info(f"Checking Phase {phase}: {phase_config['name']}")
            logger.info(f"{'='*60}")

            for table, config in phase_config['tables'].items():
                logger.info(f"\nTable: {table}")

                # Get coverage
                coverage = self.get_table_date_coverage(table, config, start_date, end_date)
                covered_dates = set(coverage.keys())

                # Find missing dates
                missing_dates = expected_dates - covered_dates
                if missing_dates:
                    ranges = self.find_consecutive_gaps(list(missing_dates))
                    for range_start, range_end, days in ranges:
                        downstream = self.get_downstream_impact(table)
                        gap = GapInfo(
                            table=table,
                            phase=phase,
                            gap_type='missing',
                            start_date=range_start,
                            end_date=range_end,
                            days_affected=days,
                            details={'missing_dates': [str(d) for d in sorted(missing_dates) if range_start <= d <= range_end]},
                            downstream_impact=downstream,
                            priority='high'
                        )
                        gap.priority = self.calculate_priority(gap)
                        all_gaps.append(gap)
                        logger.warning(f"  MISSING: {range_start} to {range_end} ({days} days)")

                        # Track cascade impact
                        for downstream_table in downstream:
                            cascade_analysis[downstream_table].append({
                                'blocked_by': table,
                                'date_range': f"{range_start} to {range_end}",
                                'days': days
                            })

                # Check for low record counts
                min_records = config.get('min_records_per_game_day', 1)
                low_record_dates = [d for d, count in coverage.items() if count < min_records]
                if low_record_dates:
                    ranges = self.find_consecutive_gaps(low_record_dates)
                    for range_start, range_end, days in ranges:
                        downstream = self.get_downstream_impact(table)
                        gap = GapInfo(
                            table=table,
                            phase=phase,
                            gap_type='low_records',
                            start_date=range_start,
                            end_date=range_end,
                            days_affected=days,
                            details={
                                'dates_with_low_records': {
                                    str(d): coverage[d] for d in low_record_dates if range_start <= d <= range_end
                                },
                                'min_expected': min_records
                            },
                            downstream_impact=downstream,
                            priority='medium'
                        )
                        gap.priority = self.calculate_priority(gap)
                        all_gaps.append(gap)
                        logger.warning(f"  LOW RECORDS: {range_start} to {range_end} ({days} days)")

                # Check contamination if requested
                if check_contamination:
                    contamination = self.check_field_contamination(table, config, start_date, end_date)
                    if contamination:
                        contaminated_dates = list(contamination.keys())
                        ranges = self.find_consecutive_gaps(contaminated_dates)
                        for range_start, range_end, days in ranges:
                            downstream = self.get_downstream_impact(table)
                            gap = GapInfo(
                                table=table,
                                phase=phase,
                                gap_type='contaminated',
                                start_date=range_start,
                                end_date=range_end,
                                days_affected=days,
                                details={
                                    'contaminated_fields': {
                                        str(d): contamination[d] for d in contaminated_dates if range_start <= d <= range_end
                                    }
                                },
                                downstream_impact=downstream,
                                priority='medium'
                            )
                            gap.priority = self.calculate_priority(gap)
                            all_gaps.append(gap)
                            logger.warning(f"  CONTAMINATED: {range_start} to {range_end} ({days} days)")

                if not missing_dates and not low_record_dates:
                    logger.info(f"  OK: Full coverage ({len(covered_dates)} dates)")

        # Generate recovery commands
        recovery_commands = self.generate_recovery_commands(all_gaps)

        # Create summary
        summary = {
            'total_gaps': len(all_gaps),
            'by_phase': defaultdict(int),
            'by_type': defaultdict(int),
            'by_priority': defaultdict(int),
            'total_days_affected': sum(g.days_affected for g in all_gaps),
        }
        for gap in all_gaps:
            summary['by_phase'][f"phase_{gap.phase}"] += 1
            summary['by_type'][gap.gap_type] += 1
            summary['by_priority'][gap.priority] += 1

        return GapReport(
            start_date=start_date,
            end_date=end_date,
            total_expected_days=len(expected_dates),
            phases_checked=phases,
            gaps=all_gaps,
            cascade_analysis=dict(cascade_analysis),
            recovery_commands=recovery_commands,
            summary=dict(summary)
        )

    def generate_recovery_commands(self, gaps: List[GapInfo]) -> List[str]:
        """Generate commands to fix detected gaps, ordered by dependency."""
        commands = []

        # Group gaps by table and find overall date ranges
        table_ranges = defaultdict(lambda: {'min': None, 'max': None})
        for gap in gaps:
            if gap.gap_type == 'missing':
                tr = table_ranges[gap.table]
                if tr['min'] is None or gap.start_date < tr['min']:
                    tr['min'] = gap.start_date
                if tr['max'] is None or gap.end_date > tr['max']:
                    tr['max'] = gap.end_date

        # Order by phase (upstream first)
        phase_order = {
            'nbac_gamebook_player_stats': 2,
            'bdl_player_boxscores': 2,
            'bigdataball_play_by_play': 2,
            'player_game_summary': 3,
            'team_defense_game_summary': 3,
            'team_offense_game_summary': 3,
            'upcoming_player_game_context': 3,
            'team_defense_zone_analysis': 4,
            'player_shot_zone_analysis': 4,
            'player_composite_factors': 4,
            'player_daily_cache': 4,
            'ml_feature_store_v2': 5,
        }

        sorted_tables = sorted(table_ranges.keys(), key=lambda t: phase_order.get(t, 99))

        for table in sorted_tables:
            tr = table_ranges[table]
            if tr['min'] and tr['max']:
                start = tr['min'].isoformat()
                end = tr['max'].isoformat()

                # Generate appropriate command based on table
                if table == 'player_game_summary':
                    commands.append(
                        f"# Fix Phase 3: player_game_summary ({start} to {end})\n"
                        f"PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py "
                        f"--start-date {start} --end-date {end}"
                    )
                elif table == 'team_defense_game_summary':
                    commands.append(
                        f"# Fix Phase 3: team_defense_game_summary ({start} to {end})\n"
                        f"PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py "
                        f"--start-date {start} --end-date {end}"
                    )
                elif table == 'upcoming_player_game_context':
                    commands.append(
                        f"# Fix Phase 3: upcoming_player_game_context ({start} to {end})\n"
                        f"PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py "
                        f"--start-date {start} --end-date {end}"
                    )
                elif table in ['team_defense_zone_analysis', 'player_shot_zone_analysis', 'player_composite_factors', 'player_daily_cache']:
                    commands.append(
                        f"# Fix Phase 4: {table} ({start} to {end})\n"
                        f"./bin/backfill/run_phase4_backfill.sh {start} {end}"
                    )

        return commands


def print_report(report: GapReport, as_json: bool = False):
    """Print the gap report."""
    if as_json:
        # Convert to JSON-serializable format
        output = {
            'start_date': report.start_date.isoformat(),
            'end_date': report.end_date.isoformat(),
            'total_expected_days': report.total_expected_days,
            'phases_checked': report.phases_checked,
            'gaps': [asdict(g) for g in report.gaps],
            'cascade_analysis': report.cascade_analysis,
            'recovery_commands': report.recovery_commands,
            'summary': report.summary,
        }
        # Convert date objects in gaps
        for gap in output['gaps']:
            gap['start_date'] = gap['start_date'].isoformat() if isinstance(gap['start_date'], date) else gap['start_date']
            gap['end_date'] = gap['end_date'].isoformat() if isinstance(gap['end_date'], date) else gap['end_date']
        print(json.dumps(output, indent=2, default=str))
        return

    print("\n" + "=" * 80)
    print("GAP DETECTION REPORT")
    print("=" * 80)
    print(f"Date Range: {report.start_date} to {report.end_date}")
    print(f"Expected Game Days: {report.total_expected_days}")
    print(f"Phases Checked: {report.phases_checked}")

    print("\n" + "-" * 40)
    print("SUMMARY")
    print("-" * 40)
    print(f"Total Gaps Found: {report.summary['total_gaps']}")
    print(f"Total Days Affected: {report.summary['total_days_affected']}")
    print(f"\nBy Phase:")
    for phase, count in sorted(report.summary['by_phase'].items()):
        print(f"  {phase}: {count} gaps")
    print(f"\nBy Type:")
    for gtype, count in report.summary['by_type'].items():
        print(f"  {gtype}: {count} gaps")
    print(f"\nBy Priority:")
    for priority, count in report.summary['by_priority'].items():
        print(f"  {priority}: {count} gaps")

    if report.gaps:
        print("\n" + "-" * 40)
        print("DETAILED GAPS (sorted by priority)")
        print("-" * 40)

        # Sort by priority
        priority_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        sorted_gaps = sorted(report.gaps, key=lambda g: (priority_order.get(g.priority, 99), g.phase))

        for gap in sorted_gaps:
            print(f"\n[{gap.priority.upper()}] Phase {gap.phase} - {gap.table}")
            print(f"  Type: {gap.gap_type}")
            print(f"  Date Range: {gap.start_date} to {gap.end_date} ({gap.days_affected} days)")
            if gap.downstream_impact:
                print(f"  Downstream Impact: {', '.join(gap.downstream_impact)}")

    if report.cascade_analysis:
        print("\n" + "-" * 40)
        print("CASCADE IMPACT ANALYSIS")
        print("-" * 40)
        for table, blockers in report.cascade_analysis.items():
            print(f"\n{table} is blocked by:")
            for blocker in blockers:
                print(f"  - {blocker['blocked_by']}: {blocker['date_range']} ({blocker['days']} days)")

    if report.recovery_commands:
        print("\n" + "-" * 40)
        print("RECOVERY COMMANDS (run in order)")
        print("-" * 40)
        for i, cmd in enumerate(report.recovery_commands, 1):
            print(f"\n{i}. {cmd}")

    print("\n" + "=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description='Detect data gaps across all processing phases',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--start-date', type=str, required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--phase', type=int, choices=[2, 3, 4, 5], help='Check specific phase only')
    parser.add_argument('--check-contamination', action='store_true', help='Include field-level contamination check')
    parser.add_argument('--generate-commands', action='store_true', help='Generate recovery commands')
    parser.add_argument('--json', action='store_true', help='Output as JSON')

    args = parser.parse_args()

    # Parse dates
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()

    # Determine phases to check
    phases = [args.phase] if args.phase else [2, 3, 4, 5]

    # Run detection
    detector = GapDetector()
    report = detector.detect_gaps(
        start_date=start_date,
        end_date=end_date,
        phases=phases,
        check_contamination=args.check_contamination
    )

    # Print report
    print_report(report, as_json=args.json)

    # Exit with appropriate code
    if report.summary['total_gaps'] > 0:
        critical_count = report.summary['by_priority'].get('critical', 0)
        high_count = report.summary['by_priority'].get('high', 0)
        if critical_count > 0:
            sys.exit(2)  # Critical gaps
        elif high_count > 0:
            sys.exit(1)  # High priority gaps
    sys.exit(0)


if __name__ == "__main__":
    main()
