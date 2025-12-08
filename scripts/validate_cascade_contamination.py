#!/usr/bin/env python3
"""
Cascade Contamination Validation Script

Validates data quality by checking critical fields aren't NULL/zero.
This complements validate_backfill_coverage.py which checks record existence.

Cascade Contamination: When gaps in upstream data cause downstream processes
to run with incomplete inputs, producing records that exist but contain invalid
values (NULLs, zeros, or incorrect calculations).

Usage:
    # Check all tables for December 2021
    python scripts/validate_cascade_contamination.py --start-date 2021-12-01 --end-date 2021-12-31

    # Check specific stage
    python scripts/validate_cascade_contamination.py --start-date 2021-12-01 --end-date 2021-12-31 --stage phase3

    # Quick check (summary only)
    python scripts/validate_cascade_contamination.py --start-date 2021-12-01 --end-date 2021-12-31 --quick

    # Use as validation gate in backfill (exits non-zero if contaminated)
    python scripts/validate_cascade_contamination.py --start-date 2021-12-01 --end-date 2021-12-31 --strict
"""

import argparse
import logging
import os
import sys
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class ContaminationStatus(Enum):
    """Status levels for contamination detection."""
    CLEAN = "CLEAN"           # 100% valid
    PARTIAL = "PARTIAL"       # Some invalid (1-90%)
    CONTAMINATED = "CONTAMINATED"  # >90% invalid or 0% valid
    NO_DATA = "NO_DATA"       # No records found


@dataclass
class FieldValidation:
    """Result of validating a single critical field."""
    field: str
    description: str
    total: int
    valid: int
    valid_pct: float
    status: ContaminationStatus


@dataclass
class TableValidation:
    """Result of validating a table's critical fields."""
    table: str
    stage: str
    date_range: Tuple[str, str]
    fields: List[FieldValidation]
    overall_status: ContaminationStatus
    contaminated_dates: List[str]


# Critical fields configuration
# Format: (field_name, valid_condition_sql, description)
CRITICAL_FIELDS = {
    # Phase 3
    'nba_analytics.team_defense_game_summary': {
        'date_field': 'game_date',
        'stage': 'phase3',
        'fields': [
            ('opp_paint_attempts', '> 0', 'Shot zone paint data'),
            ('opp_mid_range_attempts', '> 0', 'Shot zone mid-range data'),
            ('opp_three_pt_attempts', '> 0', 'Shot zone 3PT data'),
        ]
    },
    # Phase 4
    'nba_precompute.team_defense_zone_analysis': {
        'date_field': 'analysis_date',
        'stage': 'phase4',
        'fields': [
            ('paint_defense_vs_league_avg', 'IS NOT NULL', 'Paint defense metric'),
            ('mid_range_defense_vs_league_avg', 'IS NOT NULL', 'Mid-range defense metric'),
            ('three_pt_defense_vs_league_avg', 'IS NOT NULL', '3PT defense metric'),
        ]
    },
    'nba_precompute.player_shot_zone_analysis': {
        'date_field': 'analysis_date',
        'stage': 'phase4',
        'fields': [
            ('paint_pct_last_10', 'IS NOT NULL', 'Paint FG% (last 10 games)'),
            ('games_in_sample_10', '> 0', 'Games in sample count'),
        ]
    },
    'nba_precompute.player_composite_factors': {
        'date_field': 'game_date',
        'stage': 'phase4',
        'fields': [
            ('opponent_strength_score', '> 0', 'Opponent strength calculation'),
            ('shot_zone_mismatch_score', 'IS NOT NULL', 'Shot zone mismatch'),
        ]
    },
    'nba_precompute.player_daily_cache': {
        'date_field': 'cache_date',
        'stage': 'phase4',
        'fields': [
            ('points_avg_season', 'IS NOT NULL', 'Season average points'),
            ('games_played_season', '> 0', 'Games played count'),
        ]
    },
    # Phase 5
    'nba_predictions.ml_feature_store_v2': {
        'date_field': 'game_date',
        'stage': 'phase5',
        'fields': [
            ('opp_def_rating', 'IS NOT NULL', 'Opponent defense rating'),
            ('quality_tier', 'IS NOT NULL', 'Quality tier assignment'),
        ]
    },
}


class CascadeContaminationValidator:
    """Validates critical fields to detect cascade contamination."""

    def __init__(self):
        bq_location = os.environ.get('BQ_LOCATION', 'us-west2')
        self.bq_client = bigquery.Client(location=bq_location)
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)

    def validate_table(
        self,
        table: str,
        start_date: date,
        end_date: date
    ) -> Optional[TableValidation]:
        """Validate all critical fields for a table."""
        config = CRITICAL_FIELDS.get(table)
        if not config:
            logger.warning(f"No critical fields defined for {table}")
            return None

        date_field = config['date_field']
        stage = config['stage']
        fields = config['fields']

        # Build efficient aggregation query
        field_checks = []
        for field, condition, _ in fields:
            field_checks.append(f"COUNTIF({field} {condition}) as {field}_valid")
            field_checks.append(f"COUNT(*) as {field}_total")

        query = f"""
        SELECT
            {date_field} as check_date,
            {', '.join(field_checks)}
        FROM `{table}`
        WHERE {date_field} BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'
        GROUP BY {date_field}
        ORDER BY {date_field}
        """

        try:
            results = list(self.bq_client.query(query).result())
        except Exception as e:
            logger.error(f"Error querying {table}: {e}")
            return None

        if not results:
            return TableValidation(
                table=table,
                stage=stage,
                date_range=(start_date.isoformat(), end_date.isoformat()),
                fields=[],
                overall_status=ContaminationStatus.NO_DATA,
                contaminated_dates=[]
            )

        # Aggregate across all dates
        field_results = []
        contaminated_dates = set()

        for field, condition, desc in fields:
            total = sum(getattr(row, f"{field}_total", 0) for row in results)
            valid = sum(getattr(row, f"{field}_valid", 0) for row in results)
            valid_pct = (valid / total * 100) if total > 0 else 0

            # Find dates with contamination for this field
            for row in results:
                row_total = getattr(row, f"{field}_total", 0)
                row_valid = getattr(row, f"{field}_valid", 0)
                if row_total > 0 and row_valid < row_total * 0.5:  # <50% valid
                    contaminated_dates.add(str(row.check_date))

            status = self._determine_field_status(valid_pct)
            field_results.append(FieldValidation(
                field=field,
                description=desc,
                total=total,
                valid=valid,
                valid_pct=valid_pct,
                status=status
            ))

        # Determine overall status
        if all(f.status == ContaminationStatus.CLEAN for f in field_results):
            overall_status = ContaminationStatus.CLEAN
        elif any(f.status == ContaminationStatus.CONTAMINATED for f in field_results):
            overall_status = ContaminationStatus.CONTAMINATED
        else:
            overall_status = ContaminationStatus.PARTIAL

        return TableValidation(
            table=table,
            stage=stage,
            date_range=(start_date.isoformat(), end_date.isoformat()),
            fields=field_results,
            overall_status=overall_status,
            contaminated_dates=sorted(contaminated_dates)
        )

    def _determine_field_status(self, valid_pct: float) -> ContaminationStatus:
        """Determine status based on valid percentage."""
        if valid_pct >= 99.0:
            return ContaminationStatus.CLEAN
        elif valid_pct >= 50.0:
            return ContaminationStatus.PARTIAL
        else:
            return ContaminationStatus.CONTAMINATED

    def validate_stage(
        self,
        stage: str,
        start_date: date,
        end_date: date
    ) -> List[TableValidation]:
        """Validate all tables in a pipeline stage."""
        results = []
        for table, config in CRITICAL_FIELDS.items():
            if config['stage'] == stage:
                result = self.validate_table(table, start_date, end_date)
                if result:
                    results.append(result)
        return results

    def validate_all(
        self,
        start_date: date,
        end_date: date
    ) -> Dict[str, List[TableValidation]]:
        """Validate all tables grouped by stage."""
        results = {}
        for stage in ['phase3', 'phase4', 'phase5']:
            results[stage] = self.validate_stage(stage, start_date, end_date)
        return results

    def get_per_date_breakdown(
        self,
        table: str,
        start_date: date,
        end_date: date
    ) -> List[Dict]:
        """Get per-date validation breakdown for a table."""
        config = CRITICAL_FIELDS.get(table)
        if not config:
            return []

        date_field = config['date_field']
        fields = config['fields']

        field_checks = []
        for field, condition, _ in fields:
            field_checks.append(f"COUNTIF({field} {condition}) as {field}_valid")
            field_checks.append(f"COUNT(*) as {field}_total")

        query = f"""
        SELECT
            {date_field} as check_date,
            COUNT(*) as total_records,
            {', '.join(field_checks)}
        FROM `{table}`
        WHERE {date_field} BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'
        GROUP BY {date_field}
        ORDER BY {date_field}
        """

        try:
            results = list(self.bq_client.query(query).result())
            breakdown = []
            for row in results:
                date_info = {
                    'date': str(row.check_date),
                    'total_records': row.total_records,
                    'fields': {}
                }
                for field, condition, desc in fields:
                    total = getattr(row, f"{field}_total", 0)
                    valid = getattr(row, f"{field}_valid", 0)
                    valid_pct = (valid / total * 100) if total > 0 else 0
                    date_info['fields'][field] = {
                        'valid': valid,
                        'total': total,
                        'valid_pct': valid_pct,
                        'status': self._determine_field_status(valid_pct).value
                    }
                breakdown.append(date_info)
            return breakdown
        except Exception as e:
            logger.error(f"Error getting breakdown for {table}: {e}")
            return []


def print_results(
    results: Dict[str, List[TableValidation]],
    show_dates: bool = False,
    validator: Optional[CascadeContaminationValidator] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
):
    """Print validation results."""
    print("\n" + "=" * 90)
    print("CASCADE CONTAMINATION VALIDATION REPORT")
    print("=" * 90)

    print("\n STATUS KEY:")
    print("  CLEAN        = 99%+ of records have valid critical field values")
    print("  PARTIAL      = 50-99% valid (some issues)")
    print("  CONTAMINATED = <50% valid (cascade contamination detected!)")
    print("  NO_DATA      = No records found in table for date range")

    has_contamination = False

    for stage, tables in results.items():
        if not tables:
            continue

        print(f"\n{'=' * 90}")
        print(f" {stage.upper()}")
        print("=" * 90)

        for table_result in tables:
            status_icon = {
                ContaminationStatus.CLEAN: "[CLEAN]",
                ContaminationStatus.PARTIAL: "[WARN]",
                ContaminationStatus.CONTAMINATED: "[CONTAMINATED]",
                ContaminationStatus.NO_DATA: "[NO DATA]"
            }.get(table_result.overall_status, "[???]")

            if table_result.overall_status == ContaminationStatus.CONTAMINATED:
                has_contamination = True

            print(f"\n {status_icon} {table_result.table}")
            print("-" * 80)

            if table_result.overall_status == ContaminationStatus.NO_DATA:
                print("   No records found for date range")
                continue

            for field in table_result.fields:
                field_icon = {
                    ContaminationStatus.CLEAN: "[OK]",
                    ContaminationStatus.PARTIAL: "[!]",
                    ContaminationStatus.CONTAMINATED: "[X]"
                }.get(field.status, "[?]")

                print(f"   {field_icon} {field.field}: {field.valid_pct:.1f}% valid "
                      f"({field.valid:,}/{field.total:,}) - {field.description}")

            if table_result.contaminated_dates and len(table_result.contaminated_dates) <= 10:
                print(f"\n   Contaminated dates: {', '.join(table_result.contaminated_dates)}")
            elif table_result.contaminated_dates:
                print(f"\n   Contaminated dates: {len(table_result.contaminated_dates)} dates affected")

            # Show per-date breakdown if requested
            if show_dates and validator and start_date and end_date:
                breakdown = validator.get_per_date_breakdown(
                    table_result.table, start_date, end_date
                )
                if breakdown:
                    print("\n   Per-date breakdown:")
                    for date_info in breakdown[:20]:  # Limit to first 20
                        date_status = 'OK'
                        for f, info in date_info['fields'].items():
                            if info['status'] == 'CONTAMINATED':
                                date_status = 'BAD'
                                break
                            elif info['status'] == 'PARTIAL':
                                date_status = 'WARN'

                        icon = {'OK': '+', 'WARN': '!', 'BAD': 'X'}[date_status]
                        print(f"     [{icon}] {date_info['date']}: {date_info['total_records']} records")
                    if len(breakdown) > 20:
                        print(f"     ... and {len(breakdown) - 20} more dates")

    # Summary
    print("\n" + "=" * 90)
    if has_contamination:
        print(" CASCADE CONTAMINATION DETECTED!")
        print("=" * 90)
        print("\n Recommended actions:")
        print("   1. Identify the root cause (usually Phase 3 upstream data)")
        print("   2. Run backfill in dependency order:")
        print("      Phase 3 -> TDZA -> PSZA -> PDC -> PCF -> MLFS")
        print("   3. Re-run this validation after each stage")
        print("\n See: docs/02-operations/guides/cascade-contamination-prevention.md")
    else:
        print(" ALL CLEAN - No cascade contamination detected")
        print("=" * 90)

    print()
    return has_contamination


def main():
    parser = argparse.ArgumentParser(
        description='Validate data quality to detect cascade contamination'
    )
    parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--stage', choices=['phase3', 'phase4', 'phase5'],
                        help='Validate specific stage only')
    parser.add_argument('--table', help='Validate specific table only')
    parser.add_argument('--quick', action='store_true',
                        help='Quick summary without per-date details')
    parser.add_argument('--show-dates', action='store_true',
                        help='Show per-date breakdown')
    parser.add_argument('--strict', action='store_true',
                        help='Exit with code 1 if contamination detected (for CI/backfill gates)')

    args = parser.parse_args()

    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()

    print(f"Validating cascade contamination: {start_date} to {end_date}")

    validator = CascadeContaminationValidator()

    if args.table:
        result = validator.validate_table(args.table, start_date, end_date)
        if result:
            results = {result.stage: [result]}
        else:
            print(f"No validation configuration for table: {args.table}")
            sys.exit(1)
    elif args.stage:
        stage_results = validator.validate_stage(args.stage, start_date, end_date)
        results = {args.stage: stage_results}
    else:
        results = validator.validate_all(start_date, end_date)

    has_contamination = print_results(
        results,
        show_dates=args.show_dates and not args.quick,
        validator=validator if args.show_dates else None,
        start_date=start_date,
        end_date=end_date
    )

    if args.strict and has_contamination:
        sys.exit(1)


if __name__ == '__main__':
    main()
