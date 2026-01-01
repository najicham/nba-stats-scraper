#!/usr/bin/env python3
"""
Backfill Coverage Validation Script

Validates backfill coverage by comparing:
1. Expected players (from player_game_summary)
2. Actual records (from each processor table)
3. Failure records (from precompute_failures)

Shows clear breakdown of:
- Expected vs Actual counts
- Missing players and WHY they're missing
- Errors that need investigation vs expected skips

Usage:
    python scripts/validate_backfill_coverage.py --start-date 2021-11-05 --end-date 2021-11-30
    python scripts/validate_backfill_coverage.py --start-date 2021-11-10 --end-date 2021-11-10 --processor MLFS
"""

import argparse
import logging
import os
from datetime import datetime, date
from google.cloud import bigquery
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class BackfillValidator:
    """Validates backfill coverage across all Phase 4 processors."""

    PROCESSORS = {
        'PDC': {
            'table': 'nba_precompute.player_daily_cache',
            'date_col': 'cache_date',
            'entity_col': 'player_lookup',
            'name': 'PlayerDailyCacheProcessor'
        },
        'PSZA': {
            'table': 'nba_precompute.player_shot_zone_analysis',
            'date_col': 'analysis_date',
            'entity_col': 'player_lookup',
            'name': 'PlayerShotZoneAnalysisProcessor'
        },
        'PCF': {
            'table': 'nba_precompute.player_composite_factors',
            'date_col': 'game_date',
            'entity_col': 'player_lookup',
            'name': 'PlayerCompositeFactorsProcessor'
        },
        'MLFS': {
            'table': 'nba_predictions.ml_feature_store_v2',
            'date_col': 'game_date',
            'entity_col': 'player_lookup',
            'name': 'MLFeatureStoreProcessor'
        },
        'TDZA': {
            'table': 'nba_precompute.team_defense_zone_analysis',
            'date_col': 'analysis_date',
            'entity_col': 'team_abbr',
            'name': 'TeamDefenseZoneAnalysisProcessor'
        }
    }

    # Categories that are expected (not errors)
    EXPECTED_SKIP_CATEGORIES = {
        'INSUFFICIENT_DATA',      # Not enough game history (legacy - being phased out)
        'EXPECTED_INCOMPLETE',    # Season bootstrap, player hasn't played enough games yet (NOT a failure)
        'INCOMPLETE_DATA',        # Upstream data incomplete (legacy)
        'MISSING_UPSTREAM',       # Dependency not ready
        'MISSING_DEPENDENCIES',   # Date-level: upstream processors not ready
        'MINIMUM_THRESHOLD_NOT_MET',  # Date-level: not enough upstream records
        'NO_SHOT_ZONE',          # No shot data for player
        'CIRCUIT_BREAKER_ACTIVE'  # Player blocked due to repeated failures
    }

    # Categories that need investigation (problems that require backfill)
    INVESTIGATE_CATEGORIES = {
        'INCOMPLETE_UPSTREAM',    # Player has enough games but we're missing upstream data (needs backfill)
        'PROCESSING_ERROR',       # Actual error during processing
        'UNKNOWN',               # Unknown/uncategorized failures
    }

    def __init__(self):
        bq_location = os.environ.get('BQ_LOCATION', 'us-west2')
        self.bq_client = bigquery.Client(location=bq_location)
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)

    def get_expected_players(self, game_date: date) -> Dict[str, int]:
        """Get expected players who played on this date."""
        query = f"""
        SELECT
            COUNT(DISTINCT universal_player_id) as expected_players
        FROM `nba_analytics.player_game_summary`
        WHERE game_date = '{game_date.isoformat()}'
        """
        result = self.bq_client.query(query).result(timeout=60)
        for row in result:
            return {'expected_players': row.expected_players}
        return {'expected_players': 0}

    def get_player_reconciliation(self, processor: str, game_date: date) -> Dict:
        """
        True reconciliation: For each player who played, check if they have
        EITHER a record in the output table OR a failure record explaining why not.

        Returns breakdown of:
        - has_record: Players with output records
        - has_failure: Players with failure records (but no output)
        - unaccounted: Players with NEITHER (this is the gap we care about!)
        """
        config = self.PROCESSORS.get(processor)
        if not config:
            return {'has_record': 0, 'has_failure': 0, 'unaccounted': 0, 'unaccounted_players': []}

        # For team-level processors like TDZA, skip player reconciliation
        if config['entity_col'] == 'team_abbr':
            return {'has_record': 0, 'has_failure': 0, 'unaccounted': 0, 'unaccounted_players': [], 'is_team_processor': True}

        query = f"""
        WITH expected_players AS (
            -- All players who played on this date
            SELECT DISTINCT player_lookup
            FROM `nba_analytics.player_game_summary`
            WHERE game_date = '{game_date.isoformat()}'
        ),
        actual_records AS (
            -- Players who have output records
            SELECT DISTINCT {config['entity_col']} as player_lookup
            FROM `{config['table']}`
            WHERE {config['date_col']} = '{game_date.isoformat()}'
        ),
        failure_records AS (
            -- Players who have failure records
            SELECT DISTINCT entity_id as player_lookup
            FROM `nba_processing.precompute_failures`
            WHERE processor_name = '{config['name']}'
              AND analysis_date = '{game_date.isoformat()}'
              AND entity_id != 'DATE_LEVEL'
        )
        SELECT
            COUNT(DISTINCT e.player_lookup) as total_expected,
            COUNT(DISTINCT a.player_lookup) as has_record,
            COUNT(DISTINCT CASE WHEN a.player_lookup IS NULL AND f.player_lookup IS NOT NULL THEN e.player_lookup END) as has_failure_only,
            COUNT(DISTINCT CASE WHEN a.player_lookup IS NULL AND f.player_lookup IS NULL THEN e.player_lookup END) as unaccounted
        FROM expected_players e
        LEFT JOIN actual_records a ON e.player_lookup = a.player_lookup
        LEFT JOIN failure_records f ON e.player_lookup = f.player_lookup
        """
        try:
            result = self.bq_client.query(query).result(timeout=60)
            for row in result:
                return {
                    'total_expected': row.total_expected,
                    'has_record': row.has_record,
                    'has_failure': row.has_failure_only,
                    'unaccounted': row.unaccounted
                }
        except Exception as e:
            logger.warning(f"Error in reconciliation query: {e}")
            return {'has_record': 0, 'has_failure': 0, 'unaccounted': 0}

    def get_actual_records(self, processor: str, game_date: date) -> Dict[str, int]:
        """Get actual records for a processor on a date."""
        config = self.PROCESSORS.get(processor)
        if not config:
            return {'actual_records': 0}

        query = f"""
        SELECT COUNT(DISTINCT {config['entity_col']}) as actual_records
        FROM `{config['table']}`
        WHERE {config['date_col']} = '{game_date.isoformat()}'
        """
        result = self.bq_client.query(query).result(timeout=60)
        for row in result:
            return {'actual_records': row.actual_records}
        return {'actual_records': 0}

    def get_failures(self, processor: str, game_date: date) -> Dict[str, Dict]:
        """Get failures by category for a processor on a date."""
        config = self.PROCESSORS.get(processor)
        if not config:
            return {}

        query = f"""
        SELECT
            failure_category,
            COUNT(*) as count,
            COUNT(DISTINCT entity_id) as unique_entities
        FROM `nba_processing.precompute_failures`
        WHERE processor_name = '{config['name']}'
          AND analysis_date = '{game_date.isoformat()}'
        GROUP BY failure_category
        ORDER BY count DESC
        """
        try:
            result = self.bq_client.query(query).result(timeout=60)
            failures = {}
            for row in result:
                failures[row.failure_category] = {
                    'count': row.count,
                    'unique_entities': row.unique_entities
                }
            return failures
        except Exception as e:
            logger.warning(f"Error querying failures: {e}")
            return {}

    def get_game_dates(self, start_date: date, end_date: date) -> List[date]:
        """Get game dates from player_game_summary."""
        query = f"""
        SELECT DISTINCT game_date
        FROM `nba_analytics.player_game_summary`
        WHERE game_date BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'
        ORDER BY game_date
        """
        result = self.bq_client.query(query).result(timeout=60)
        return [row.game_date for row in result]

    def validate_date(self, game_date: date, processors: Optional[List[str]] = None) -> Dict:
        """Validate coverage for a single date."""
        expected = self.get_expected_players(game_date)

        results = {
            'date': game_date.isoformat(),
            'expected_players': expected['expected_players'],
            'processors': {}
        }

        processor_list = processors if processors else self.PROCESSORS.keys()

        for proc in processor_list:
            if proc not in self.PROCESSORS:
                continue

            actual = self.get_actual_records(proc, game_date)
            failures = self.get_failures(proc, game_date)

            # Categorize failures
            expected_skips = sum(
                f['unique_entities'] for cat, f in failures.items()
                if cat in self.EXPECTED_SKIP_CATEGORIES
            )
            # INCOMPLETE_UPSTREAM and other investigate categories are NOT expected
            errors_to_investigate = sum(
                f['unique_entities'] for cat, f in failures.items()
                if cat in self.INVESTIGATE_CATEGORIES or cat not in self.EXPECTED_SKIP_CATEGORIES
            )

            # Check for date-level failures (entity_id = 'DATE_LEVEL')
            has_date_level_failure = 'MISSING_DEPENDENCIES' in failures or 'MINIMUM_THRESHOLD_NOT_MET' in failures

            results['processors'][proc] = {
                'actual': actual['actual_records'],
                'failures': failures,
                'expected_skips': expected_skips,
                'errors_to_investigate': errors_to_investigate,
                'has_date_level_failure': has_date_level_failure,
                'status': self._determine_status(
                    expected['expected_players'],
                    actual['actual_records'],
                    expected_skips,
                    errors_to_investigate,
                    has_date_level_failure
                )
            }

        return results

    def _determine_status(self, expected: int, actual: int, expected_skips: int, errors: int,
                          has_date_level_failure: bool = False) -> str:
        """Determine the status of the validation."""
        if actual == 0 and expected > 0:
            if has_date_level_failure:
                return "DEPS_MISSING"  # Date-level failure (missing dependencies)
            elif expected_skips > 0:
                return "SKIPPED"  # All records were expected skips
            else:
                return "UNTRACKED"  # No records and no failure tracking - needs investigation
        elif errors > 0:
            return "INVESTIGATE"  # Has errors that need investigation
        elif actual > 0:
            return "OK"
        else:
            return "NO_GAMES"

    def print_summary(self, results: List[Dict], show_details: bool = False):
        """Print summary of validation results."""
        print("\n" + "=" * 80)
        print("BACKFILL COVERAGE VALIDATION REPORT")
        print("=" * 80)

        # Summary by processor
        processor_stats = {}
        for proc in self.PROCESSORS.keys():
            processor_stats[proc] = {
                'ok': 0, 'skipped': 0, 'deps_missing': 0, 'untracked': 0, 'investigate': 0, 'no_games': 0
            }

        for result in results:
            for proc, data in result['processors'].items():
                status = data['status'].lower()
                if status in processor_stats[proc]:
                    processor_stats[proc][status] += 1

        print("\n STATUS KEY:")
        print("  OK         = Records present")
        print("  Skipped    = No records - player-level issues (expected)")
        print("               └─ EXPECTED_INCOMPLETE: Player hasn't played enough games (bootstrap/early season)")
        print("               └─ INSUFFICIENT_DATA: Not enough game history (legacy)")
        print("  DepsMiss   = No records - upstream dependencies missing (expected during bootstrap)")
        print("  Untracked  = No records - NO failure tracking (needs investigation!)")
        print("  Investigate = Has processing errors (needs investigation!)")
        print("               └─ INCOMPLETE_UPSTREAM: Player has games but missing upstream data (NEEDS BACKFILL)")

        print("\n SUMMARY BY PROCESSOR")
        print("-" * 90)
        print(f"{'Processor':<10} {'OK':>6} {'Skipped':>8} {'DepsMiss':>10} {'Untracked':>10} {'Investigate':>12}")
        print("-" * 90)

        for proc, stats in processor_stats.items():
            needs_attention = stats['untracked'] > 0 or stats['investigate'] > 0
            flag = " (!)" if needs_attention else "    "
            print(f"{proc:<10} {stats['ok']:>6} {stats['skipped']:>8} {stats['deps_missing']:>10} "
                  f"{stats['untracked']:>10} {stats['investigate']:>12}{flag}")

        # Detail by date if requested
        if show_details:
            print("\n📅 DETAIL BY DATE")
            print("-" * 80)

            for result in results:
                print(f"\n{result['date']} (Expected: {result['expected_players']} players)")
                for proc, data in result['processors'].items():
                    status_icon = {
                        'OK': '[OK]',
                        'SKIPPED': '[Skip]',
                        'DEPS_MISSING': '[Deps]',
                        'UNTRACKED': '[!!??]',
                        'INVESTIGATE': '[!ERR]',
                        'NO_GAMES': '[None]'
                    }.get(data['status'], '[????]')

                    print(f"  {proc:>6}: {status_icon} {data['actual']:>4} records | Status: {data['status']}")

                    if data['failures'] and (show_details or data['errors_to_investigate'] > 0):
                        for cat, counts in data['failures'].items():
                            # Explicitly mark INCOMPLETE_UPSTREAM as needs backfill
                            if cat == 'INCOMPLETE_UPSTREAM':
                                flag = "⚠️ NEEDS BACKFILL"
                            elif cat == 'EXPECTED_INCOMPLETE':
                                flag = "(expected - bootstrap/early season)"
                            elif cat in self.INVESTIGATE_CATEGORIES:
                                flag = "⚠️ INVESTIGATE"
                            elif cat in self.EXPECTED_SKIP_CATEGORIES:
                                flag = "(expected)"
                            else:
                                flag = "⚠️ INVESTIGATE"
                            print(f"           → {cat}: {counts['unique_entities']} {flag}")

        # Print errors that need investigation
        errors_found = []
        for result in results:
            for proc, data in result['processors'].items():
                if data['errors_to_investigate'] > 0:
                    errors_found.append({
                        'date': result['date'],
                        'processor': proc,
                        'errors': data['errors_to_investigate'],
                        'failures': {k: v for k, v in data['failures'].items()
                                   if k not in self.EXPECTED_SKIP_CATEGORIES}
                    })

        if errors_found:
            print("\n" + "=" * 80)
            print("🚨 ERRORS REQUIRING INVESTIGATION")
            print("=" * 80)
            for error in errors_found:
                print(f"\n{error['date']} - {error['processor']}: {error['errors']} errors")
                for cat, counts in error['failures'].items():
                    print(f"  → {cat}: {counts['unique_entities']} players")
        else:
            print("\n" + "=" * 80)
            print("✅ NO ERRORS REQUIRING INVESTIGATION")
            print("=" * 80)

        print()


def main():
    parser = argparse.ArgumentParser(description='Validate backfill coverage')
    parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--processor', help='Specific processor to validate (PDC, PSZA, PCF, MLFS, TDZA)')
    parser.add_argument('--details', action='store_true', help='Show detailed breakdown by date')
    parser.add_argument('--reconcile', action='store_true', help='Do true player-level reconciliation')

    args = parser.parse_args()

    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    processors = [args.processor.upper()] if args.processor else None

    validator = BackfillValidator()

    # Get game dates
    game_dates = validator.get_game_dates(start_date, end_date)
    print(f"Found {len(game_dates)} game dates between {start_date} and {end_date}")

    if args.reconcile:
        # True player-level reconciliation
        print("\n" + "=" * 90)
        print("PLAYER-LEVEL RECONCILIATION")
        print("For each player who played, check: Has record OR has failure record?")
        print("=" * 90)
        print("\nLegend:")
        print("  Has Record  = Player has output in processor table")
        print("  Has Failure = Player has no output BUT has failure record explaining why")
        print("  Unaccounted = Player has NEITHER output nor failure - GAP TO INVESTIGATE!")
        print()

        proc_list = processors if processors else ['PDC', 'PSZA', 'PCF', 'MLFS']  # Skip TDZA (team-level)

        for proc in proc_list:
            print(f"\n--- {proc} ---")
            print(f"{'Date':<12} {'Expected':>10} {'Has Record':>12} {'Has Failure':>13} {'Unaccounted':>13} {'Coverage':>10}")
            print("-" * 75)

            total_expected = 0
            total_record = 0
            total_failure = 0
            total_unaccounted = 0

            for game_date in game_dates:
                recon = validator.get_player_reconciliation(proc, game_date)
                if recon.get('is_team_processor'):
                    continue

                expected = recon.get('total_expected', 0)
                has_record = recon.get('has_record', 0)
                has_failure = recon.get('has_failure', 0)
                unaccounted = recon.get('unaccounted', 0)

                total_expected += expected
                total_record += has_record
                total_failure += has_failure
                total_unaccounted += unaccounted

                coverage = f"{100*(has_record + has_failure)/expected:.0f}%" if expected > 0 else "N/A"
                flag = " (!)" if unaccounted > 0 else ""

                print(f"{game_date.isoformat():<12} {expected:>10} {has_record:>12} {has_failure:>13} {unaccounted:>13} {coverage:>10}{flag}")

            print("-" * 75)
            total_coverage = f"{100*(total_record + total_failure)/total_expected:.0f}%" if total_expected > 0 else "N/A"
            print(f"{'TOTAL':<12} {total_expected:>10} {total_record:>12} {total_failure:>13} {total_unaccounted:>13} {total_coverage:>10}")

            if total_unaccounted > 0:
                print(f"\n  WARNING: {total_unaccounted} players are unaccounted for - need investigation!")
            else:
                print(f"\n  All players accounted for (record or failure)")

        return

    # Validate each date
    results = []
    for game_date in game_dates:
        result = validator.validate_date(game_date, processors)
        results.append(result)

    # Print summary
    validator.print_summary(results, show_details=args.details)


if __name__ == '__main__':
    main()
