#!/usr/bin/env python3
"""
Golden Dataset Verification Script

Verifies that rolling averages in player_daily_cache match manually verified
expected values in the golden dataset table.

This script:
1. Queries golden dataset records (manually verified values)
2. For each record, queries raw boxscores for the player's last N games
3. Calculates expected L5/L10 averages using same logic as stats_aggregator.py
4. Compares calculated values to player_daily_cache
5. Alerts if difference > tolerance threshold

Usage:
    # Verify all active golden dataset records
    python scripts/verify_golden_dataset.py

    # Verify specific player
    python scripts/verify_golden_dataset.py --player "LeBron James"

    # Verify specific date
    python scripts/verify_golden_dataset.py --date 2024-12-15

    # Verify with custom tolerance
    python scripts/verify_golden_dataset.py --tolerance 0.05

    # Verbose output with detailed calculations
    python scripts/verify_golden_dataset.py --verbose

    # Check against raw data only (skip cache comparison)
    python scripts/verify_golden_dataset.py --raw-only

Created: 2026-01-27
Purpose: Automated verification of rolling average calculations
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
import pandas as pd

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Default tolerance for floating point comparisons (0.1 points)
DEFAULT_TOLERANCE = 0.1


def get_bq_client():
    """Get BigQuery client."""
    from google.cloud import bigquery
    return bigquery.Client()


def get_golden_dataset_records(
    client,
    player_name: Optional[str] = None,
    game_date: Optional[date] = None
) -> pd.DataFrame:
    """
    Retrieve golden dataset records to verify.

    Args:
        client: BigQuery client
        player_name: Optional filter for specific player
        game_date: Optional filter for specific date

    Returns:
        DataFrame with golden dataset records
    """
    project_id = client.project

    where_clauses = ["is_active = TRUE"]

    if player_name:
        where_clauses.append(f"player_name = '{player_name}'")

    if game_date:
        where_clauses.append(f"game_date = '{game_date}'")

    where_clause = " AND ".join(where_clauses)

    query = f"""
    SELECT
        player_id,
        player_name,
        player_lookup,
        game_date,
        expected_pts_l5,
        expected_pts_l10,
        expected_pts_season,
        expected_reb_l5,
        expected_reb_l10,
        expected_ast_l5,
        expected_ast_l10,
        expected_minutes_l10,
        expected_usage_rate_l10,
        verified_by,
        verified_at,
        notes
    FROM `{project_id}.nba_reference.golden_dataset`
    WHERE {where_clause}
    ORDER BY game_date DESC, player_name
    """

    logger.info(f"Fetching golden dataset records...")
    results = client.query(query).result(timeout=60)
    df = results.to_dataframe()

    logger.info(f"Found {len(df)} golden dataset record(s) to verify")
    return df


def get_player_games_before_date(
    client,
    player_lookup: str,
    game_date: date,
    season: str = "2024-25"
) -> pd.DataFrame:
    """
    Get a player's games before a specific date, sorted descending by date.

    Args:
        client: BigQuery client
        player_lookup: Normalized player lookup key
        game_date: Date to get games before
        season: NBA season (e.g., "2024-25")

    Returns:
        DataFrame with player's game history
    """
    project_id = client.project

    # Use player_game_summary which has all the stats we need
    query = f"""
    SELECT
        game_date,
        points,
        rebounds_total as rebounds,
        assists,
        minutes_played,
        usage_rate
    FROM `{project_id}.nba_analytics.player_game_summary`
    WHERE player_lookup = '{player_lookup}'
      AND game_date < '{game_date}'
      AND season = '{season}'
      AND minutes_played > 0  -- Only games where player actually played
    ORDER BY game_date DESC
    """

    results = client.query(query).result(timeout=60)
    df = results.to_dataframe()

    return df


def calculate_rolling_averages(player_games: pd.DataFrame) -> Dict[str, Optional[float]]:
    """
    Calculate rolling averages using same logic as stats_aggregator.py.

    Args:
        player_games: DataFrame with player game-level stats (sorted desc by date)

    Returns:
        Dictionary with calculated averages
    """
    # Get windows
    last_5_games = player_games.head(5)
    last_10_games = player_games.head(10)

    # Calculate averages (round to 4 decimal places for BigQuery NUMERIC compatibility)
    result = {}

    # Points averaging
    if len(last_5_games) > 0:
        result['pts_l5'] = round(float(last_5_games['points'].mean()), 4)
    else:
        result['pts_l5'] = None

    if len(last_10_games) > 0:
        result['pts_l10'] = round(float(last_10_games['points'].mean()), 4)
    else:
        result['pts_l10'] = None

    if len(player_games) > 0:
        result['pts_season'] = round(float(player_games['points'].mean()), 4)
    else:
        result['pts_season'] = None

    # Rebounds averaging
    if len(last_5_games) > 0:
        result['reb_l5'] = round(float(last_5_games['rebounds'].mean()), 4)
    else:
        result['reb_l5'] = None

    if len(last_10_games) > 0:
        result['reb_l10'] = round(float(last_10_games['rebounds'].mean()), 4)
    else:
        result['reb_l10'] = None

    # Assists averaging
    if len(last_5_games) > 0:
        result['ast_l5'] = round(float(last_5_games['assists'].mean()), 4)
    else:
        result['ast_l5'] = None

    if len(last_10_games) > 0:
        result['ast_l10'] = round(float(last_10_games['assists'].mean()), 4)
    else:
        result['ast_l10'] = None

    # Minutes averaging
    if len(last_10_games) > 0:
        result['minutes_l10'] = round(float(last_10_games['minutes_played'].mean()), 4)
    else:
        result['minutes_l10'] = None

    # Usage rate averaging
    if len(last_10_games) > 0:
        result['usage_l10'] = round(float(last_10_games['usage_rate'].mean()), 4)
    else:
        result['usage_l10'] = None

    return result


def get_cache_values(
    client,
    player_lookup: str,
    game_date: date
) -> Dict[str, Optional[float]]:
    """
    Get values from player_daily_cache for comparison.

    Args:
        client: BigQuery client
        player_lookup: Normalized player lookup key
        game_date: Date to query

    Returns:
        Dictionary with cached values
    """
    project_id = client.project

    query = f"""
    SELECT
        points_avg_last_5,
        points_avg_last_10,
        points_avg_season
    FROM `{project_id}.nba_precompute.player_daily_cache`
    WHERE player_lookup = '{player_lookup}'
      AND game_date = '{game_date}'
    """

    results = client.query(query).result(timeout=60)
    rows = list(results)

    if not rows:
        return {}

    row = rows[0]
    return {
        'pts_l5': float(row.points_avg_last_5) if row.points_avg_last_5 is not None else None,
        'pts_l10': float(row.points_avg_last_10) if row.points_avg_last_10 is not None else None,
        'pts_season': float(row.points_avg_season) if row.points_avg_season is not None else None,
    }


def verify_record(
    client,
    record: pd.Series,
    tolerance: float = DEFAULT_TOLERANCE,
    verbose: bool = False,
    raw_only: bool = False
) -> Dict[str, any]:
    """
    Verify a single golden dataset record.

    Args:
        client: BigQuery client
        record: Golden dataset record (pandas Series)
        tolerance: Tolerance for floating point comparison
        verbose: Whether to print detailed calculations
        raw_only: If True, only check against raw data (skip cache comparison)

    Returns:
        Dictionary with verification results
    """
    player_name = record['player_name']
    player_lookup = record['player_lookup']
    game_date = record['game_date']

    logger.info(f"\n{'='*80}")
    logger.info(f"Verifying: {player_name} on {game_date}")
    logger.info(f"{'='*80}")

    # Get player's game history before this date
    player_games = get_player_games_before_date(client, player_lookup, game_date)

    if len(player_games) == 0:
        logger.warning(f"No game history found for {player_name} before {game_date}")
        return {
            'player_name': player_name,
            'game_date': game_date,
            'status': 'ERROR',
            'message': 'No game history found'
        }

    if verbose:
        logger.info(f"Found {len(player_games)} games before {game_date}")
        logger.info(f"Last 10 games:\n{player_games.head(10)[['game_date', 'points', 'rebounds', 'assists']].to_string()}")

    # Calculate rolling averages from raw data
    calculated = calculate_rolling_averages(player_games)

    # Compare to expected values from golden dataset
    checks = []
    failures = []

    # Points L5
    if record['expected_pts_l5'] is not None and calculated['pts_l5'] is not None:
        diff = abs(calculated['pts_l5'] - record['expected_pts_l5'])
        passed = diff <= tolerance
        checks.append({
            'metric': 'points_l5',
            'expected': record['expected_pts_l5'],
            'calculated': calculated['pts_l5'],
            'diff': diff,
            'passed': passed
        })
        if not passed:
            failures.append(f"PTS L5: expected={record['expected_pts_l5']:.2f}, calculated={calculated['pts_l5']:.2f}, diff={diff:.4f}")

    # Points L10
    if record['expected_pts_l10'] is not None and calculated['pts_l10'] is not None:
        diff = abs(calculated['pts_l10'] - record['expected_pts_l10'])
        passed = diff <= tolerance
        checks.append({
            'metric': 'points_l10',
            'expected': record['expected_pts_l10'],
            'calculated': calculated['pts_l10'],
            'diff': diff,
            'passed': passed
        })
        if not passed:
            failures.append(f"PTS L10: expected={record['expected_pts_l10']:.2f}, calculated={calculated['pts_l10']:.2f}, diff={diff:.4f}")

    # Points Season
    if record['expected_pts_season'] is not None and calculated['pts_season'] is not None:
        diff = abs(calculated['pts_season'] - record['expected_pts_season'])
        passed = diff <= tolerance
        checks.append({
            'metric': 'points_season',
            'expected': record['expected_pts_season'],
            'calculated': calculated['pts_season'],
            'diff': diff,
            'passed': passed
        })
        if not passed:
            failures.append(f"PTS Season: expected={record['expected_pts_season']:.2f}, calculated={calculated['pts_season']:.2f}, diff={diff:.4f}")

    # Rebounds L5
    if record['expected_reb_l5'] is not None and calculated['reb_l5'] is not None:
        diff = abs(calculated['reb_l5'] - record['expected_reb_l5'])
        passed = diff <= tolerance
        checks.append({
            'metric': 'rebounds_l5',
            'expected': record['expected_reb_l5'],
            'calculated': calculated['reb_l5'],
            'diff': diff,
            'passed': passed
        })
        if not passed:
            failures.append(f"REB L5: expected={record['expected_reb_l5']:.2f}, calculated={calculated['reb_l5']:.2f}, diff={diff:.4f}")

    # Rebounds L10
    if record['expected_reb_l10'] is not None and calculated['reb_l10'] is not None:
        diff = abs(calculated['reb_l10'] - record['expected_reb_l10'])
        passed = diff <= tolerance
        checks.append({
            'metric': 'rebounds_l10',
            'expected': record['expected_reb_l10'],
            'calculated': calculated['reb_l10'],
            'diff': diff,
            'passed': passed
        })
        if not passed:
            failures.append(f"REB L10: expected={record['expected_reb_l10']:.2f}, calculated={calculated['reb_l10']:.2f}, diff={diff:.4f}")

    # Assists L5
    if record['expected_ast_l5'] is not None and calculated['ast_l5'] is not None:
        diff = abs(calculated['ast_l5'] - record['expected_ast_l5'])
        passed = diff <= tolerance
        checks.append({
            'metric': 'assists_l5',
            'expected': record['expected_ast_l5'],
            'calculated': calculated['ast_l5'],
            'diff': diff,
            'passed': passed
        })
        if not passed:
            failures.append(f"AST L5: expected={record['expected_ast_l5']:.2f}, calculated={calculated['ast_l5']:.2f}, diff={diff:.4f}")

    # Assists L10
    if record['expected_ast_l10'] is not None and calculated['ast_l10'] is not None:
        diff = abs(calculated['ast_l10'] - record['expected_ast_l10'])
        passed = diff <= tolerance
        checks.append({
            'metric': 'assists_l10',
            'expected': record['expected_ast_l10'],
            'calculated': calculated['ast_l10'],
            'diff': diff,
            'passed': passed
        })
        if not passed:
            failures.append(f"AST L10: expected={record['expected_ast_l10']:.2f}, calculated={calculated['ast_l10']:.2f}, diff={diff:.4f}")

    # Minutes L10
    if record['expected_minutes_l10'] is not None and calculated['minutes_l10'] is not None:
        diff = abs(calculated['minutes_l10'] - record['expected_minutes_l10'])
        passed = diff <= tolerance
        checks.append({
            'metric': 'minutes_l10',
            'expected': record['expected_minutes_l10'],
            'calculated': calculated['minutes_l10'],
            'diff': diff,
            'passed': passed
        })
        if not passed:
            failures.append(f"MIN L10: expected={record['expected_minutes_l10']:.2f}, calculated={calculated['minutes_l10']:.2f}, diff={diff:.4f}")

    # Usage Rate L10
    if record['expected_usage_rate_l10'] is not None and calculated['usage_l10'] is not None:
        diff = abs(calculated['usage_l10'] - record['expected_usage_rate_l10'])
        passed = diff <= tolerance
        checks.append({
            'metric': 'usage_rate_l10',
            'expected': record['expected_usage_rate_l10'],
            'calculated': calculated['usage_l10'],
            'diff': diff,
            'passed': passed
        })
        if not passed:
            failures.append(f"USG L10: expected={record['expected_usage_rate_l10']:.2f}, calculated={calculated['usage_l10']:.2f}, diff={diff:.4f}")

    # Compare to cached values (unless raw_only mode)
    cache_checks = []
    if not raw_only:
        cache_values = get_cache_values(client, player_lookup, game_date)

        if cache_values:
            # Points L5 cache comparison
            if calculated['pts_l5'] is not None and cache_values.get('pts_l5') is not None:
                diff = abs(calculated['pts_l5'] - cache_values['pts_l5'])
                passed = diff <= tolerance
                cache_checks.append({
                    'metric': 'points_l5_cache',
                    'calculated': calculated['pts_l5'],
                    'cached': cache_values['pts_l5'],
                    'diff': diff,
                    'passed': passed
                })
                if not passed:
                    failures.append(f"CACHE PTS L5: calculated={calculated['pts_l5']:.2f}, cached={cache_values['pts_l5']:.2f}, diff={diff:.4f}")

            # Points L10 cache comparison
            if calculated['pts_l10'] is not None and cache_values.get('pts_l10') is not None:
                diff = abs(calculated['pts_l10'] - cache_values['pts_l10'])
                passed = diff <= tolerance
                cache_checks.append({
                    'metric': 'points_l10_cache',
                    'calculated': calculated['pts_l10'],
                    'cached': cache_values['pts_l10'],
                    'diff': diff,
                    'passed': passed
                })
                if not passed:
                    failures.append(f"CACHE PTS L10: calculated={calculated['pts_l10']:.2f}, cached={cache_values['pts_l10']:.2f}, diff={diff:.4f}")

            # Points Season cache comparison
            if calculated['pts_season'] is not None and cache_values.get('pts_season') is not None:
                diff = abs(calculated['pts_season'] - cache_values['pts_season'])
                passed = diff <= tolerance
                cache_checks.append({
                    'metric': 'points_season_cache',
                    'calculated': calculated['pts_season'],
                    'cached': cache_values['pts_season'],
                    'diff': diff,
                    'passed': passed
                })
                if not passed:
                    failures.append(f"CACHE PTS Season: calculated={calculated['pts_season']:.2f}, cached={cache_values['pts_season']:.2f}, diff={diff:.4f}")
        else:
            logger.warning(f"No cached values found for {player_name} on {game_date}")

    # Print results
    if verbose:
        logger.info("\nCalculated vs Expected:")
        for check in checks:
            status = "✓ PASS" if check['passed'] else "✗ FAIL"
            logger.info(f"  {check['metric']:20s}: expected={check['expected']:7.2f}, calculated={check['calculated']:7.2f}, diff={check['diff']:7.4f} {status}")

        if cache_checks:
            logger.info("\nCalculated vs Cached:")
            for check in cache_checks:
                status = "✓ PASS" if check['passed'] else "✗ FAIL"
                logger.info(f"  {check['metric']:20s}: calculated={check['calculated']:7.2f}, cached={check['cached']:7.2f}, diff={check['diff']:7.4f} {status}")

    # Determine overall status
    all_passed = all(check['passed'] for check in checks)
    cache_passed = all(check['passed'] for check in cache_checks) if cache_checks else True

    if all_passed and cache_passed:
        status = "PASS"
        logger.info(f"✓ PASS: All checks passed for {player_name} on {game_date}")
    else:
        status = "FAIL"
        logger.error(f"✗ FAIL: {len(failures)} check(s) failed for {player_name} on {game_date}")
        for failure in failures:
            logger.error(f"  - {failure}")

    return {
        'player_name': player_name,
        'game_date': game_date,
        'status': status,
        'checks': checks,
        'cache_checks': cache_checks,
        'failures': failures,
        'notes': record.get('notes')
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Verify golden dataset rolling averages',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Verify all active golden dataset records
  python scripts/verify_golden_dataset.py

  # Verify specific player
  python scripts/verify_golden_dataset.py --player "LeBron James"

  # Verify specific date
  python scripts/verify_golden_dataset.py --date 2024-12-15

  # Verbose output
  python scripts/verify_golden_dataset.py --verbose

  # Custom tolerance (default is 0.1)
  python scripts/verify_golden_dataset.py --tolerance 0.05

  # Skip cache comparison, only check raw calculation
  python scripts/verify_golden_dataset.py --raw-only
        """
    )

    parser.add_argument(
        '--player',
        help='Filter by player name (e.g., "LeBron James")'
    )

    parser.add_argument(
        '--date',
        help='Filter by game date (YYYY-MM-DD format)'
    )

    parser.add_argument(
        '--tolerance',
        type=float,
        default=DEFAULT_TOLERANCE,
        help=f'Tolerance for floating point comparison (default: {DEFAULT_TOLERANCE})'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Print detailed calculations and comparisons'
    )

    parser.add_argument(
        '--raw-only',
        action='store_true',
        help='Only check against raw data, skip cache comparison'
    )

    args = parser.parse_args()

    # Parse date if provided
    game_date = None
    if args.date:
        try:
            game_date = datetime.strptime(args.date, '%Y-%m-%d').date()
        except ValueError:
            logger.error(f"Invalid date format: {args.date}. Use YYYY-MM-DD.")
            return 1

    # Get BigQuery client
    try:
        client = get_bq_client()
    except Exception as e:
        logger.error(f"Failed to create BigQuery client: {e}")
        return 1

    # Get golden dataset records
    try:
        golden_records = get_golden_dataset_records(client, args.player, game_date)
    except Exception as e:
        logger.error(f"Failed to fetch golden dataset records: {e}")
        return 1

    if len(golden_records) == 0:
        logger.warning("No golden dataset records found matching criteria")
        return 0

    # Verify each record
    results = []
    for _, record in golden_records.iterrows():
        try:
            result = verify_record(
                client,
                record,
                tolerance=args.tolerance,
                verbose=args.verbose,
                raw_only=args.raw_only
            )
            results.append(result)
        except Exception as e:
            logger.error(f"Failed to verify {record['player_name']} on {record['game_date']}: {e}")
            results.append({
                'player_name': record['player_name'],
                'game_date': record['game_date'],
                'status': 'ERROR',
                'message': str(e)
            })

    # Print summary
    logger.info(f"\n{'='*80}")
    logger.info("VERIFICATION SUMMARY")
    logger.info(f"{'='*80}")

    passed = sum(1 for r in results if r['status'] == 'PASS')
    failed = sum(1 for r in results if r['status'] == 'FAIL')
    errors = sum(1 for r in results if r['status'] == 'ERROR')

    logger.info(f"Total records checked: {len(results)}")
    logger.info(f"  ✓ Passed: {passed}")
    logger.info(f"  ✗ Failed: {failed}")
    logger.info(f"  ⚠ Errors: {errors}")

    if failed > 0:
        logger.info(f"\nFailed records:")
        for result in results:
            if result['status'] == 'FAIL':
                logger.info(f"  - {result['player_name']} on {result['game_date']}")
                if result.get('failures'):
                    for failure in result['failures']:
                        logger.info(f"    • {failure}")

    # Return exit code based on results
    if failed > 0 or errors > 0:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
