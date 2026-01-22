#!/usr/bin/env python3
"""
Spot Check Tool for ML Feature Store Validation

Validates that feature calculations (rolling averages, completeness tracking)
are accurate by comparing against raw source data.

Checks:
1. Rolling average calculations (points_avg_last_10, etc.)
2. Historical completeness accuracy (games_found, contributing_game_dates)
3. Game date lineage (do the dates match actual games?)
4. Bootstrap detection accuracy

Usage:
    # Quick spot check (5 random players)
    python bin/spot_check_features.py

    # Check specific player
    python bin/spot_check_features.py --player lebron_james

    # Check specific date
    python bin/spot_check_features.py --date 2026-01-21

    # Check multiple random players
    python bin/spot_check_features.py --count 20

    # Verbose output with raw data
    python bin/spot_check_features.py --verbose

    # Check entire date (all players)
    python bin/spot_check_features.py --date 2026-01-21 --all-players

Created: January 22, 2026
Purpose: Validate feature calculations before/after backfills
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import random

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Tolerance for floating point comparisons
TOLERANCE = 0.01  # 1% tolerance for averages


def get_bq_client():
    """Get BigQuery client."""
    from google.cloud import bigquery
    return bigquery.Client()


def get_random_players(client, game_date: date, count: int = 5) -> List[str]:
    """Get random players who have features for a given date."""
    query = f"""
    SELECT DISTINCT player_lookup
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
    WHERE game_date = '{game_date}'
      AND historical_completeness IS NOT NULL
    ORDER BY RAND()
    LIMIT {count}
    """
    result = client.query(query).to_dataframe()
    return result['player_lookup'].tolist()


def get_feature_record(client, player_lookup: str, game_date: date) -> Optional[Dict]:
    """Get the feature record for a player on a date."""
    query = f"""
    SELECT
        player_lookup,
        game_date,
        features,
        feature_names,
        historical_completeness.games_found,
        historical_completeness.games_expected,
        historical_completeness.is_complete,
        historical_completeness.is_bootstrap,
        historical_completeness.contributing_game_dates
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
    WHERE player_lookup = '{player_lookup}'
      AND game_date = '{game_date}'
    """
    result = client.query(query).to_dataframe()
    if result.empty:
        return None
    return result.iloc[0].to_dict()


def get_raw_games(client, player_lookup: str, before_date: date, limit: int = 10) -> List[Dict]:
    """Get raw game data from player_game_summary."""
    query = f"""
    SELECT
        game_date,
        points,
        minutes_played,
        ft_makes,
        fg_attempts,
        paint_attempts,
        mid_range_attempts,
        three_pt_attempts
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE player_lookup = '{player_lookup}'
      AND game_date < '{before_date}'
    ORDER BY game_date DESC
    LIMIT {limit}
    """
    result = client.query(query).to_dataframe()
    return result.to_dict('records')


def get_phase4_cache_value(client, player_lookup: str, cache_date: date) -> Optional[Dict]:
    """Get Phase 4 player_daily_cache values."""
    query = f"""
    SELECT
        points_avg_last_5,
        points_avg_last_10
    FROM `nba-props-platform.nba_precompute.player_daily_cache`
    WHERE player_lookup = '{player_lookup}'
      AND cache_date = '{cache_date}'
    """
    try:
        result = client.query(query).to_dataframe()
        if result.empty:
            return None
        return result.iloc[0].to_dict()
    except Exception:
        return None


def get_total_games_available(client, player_lookup: str, before_date: date, lookback_days: int = 60) -> int:
    """Get total games available for player in lookback window."""
    lookback_date = before_date - timedelta(days=lookback_days)
    query = f"""
    SELECT COUNT(*) as total
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE player_lookup = '{player_lookup}'
      AND game_date < '{before_date}'
      AND game_date >= '{lookback_date}'
    """
    result = client.query(query).to_dataframe()
    return int(result.iloc[0]['total'])


def calculate_expected_avg(games: List[Dict], field: str, count: int) -> Optional[float]:
    """Calculate expected average from raw games."""
    if len(games) < count:
        return None
    values = [g[field] for g in games[:count] if g[field] is not None]
    if not values:
        return None
    return sum(values) / len(values)


def validate_player(client, player_lookup: str, game_date: date, verbose: bool = False) -> Dict:
    """
    Validate feature calculations for a single player.

    Returns dict with validation results.
    """
    results = {
        'player_lookup': player_lookup,
        'game_date': str(game_date),
        'checks': [],
        'passed': 0,
        'failed': 0,
        'warnings': 0,
        'overall': 'UNKNOWN'
    }

    # Get feature record
    feature = get_feature_record(client, player_lookup, game_date)
    if not feature:
        results['checks'].append({
            'name': 'Feature record exists',
            'status': 'SKIP',
            'message': 'No feature record found (may not have historical_completeness yet)'
        })
        results['overall'] = 'SKIP'
        return results

    # Get raw games
    raw_games = get_raw_games(client, player_lookup, game_date, limit=15)

    if verbose:
        print(f"\n  Raw games found: {len(raw_games)}")
        for g in raw_games[:5]:
            print(f"    {g['game_date']}: {g['points']} pts, {g['minutes_played']} min")

    # =========================================================================
    # CHECK 1: Games found matches actual games
    # =========================================================================
    games_found = feature['games_found']
    actual_games = len(raw_games[:10])  # Cap at 10 (window size)

    if games_found == actual_games:
        results['checks'].append({
            'name': 'Games found accuracy',
            'status': 'PASS',
            'message': f'{games_found} games found matches raw data'
        })
        results['passed'] += 1
    else:
        results['checks'].append({
            'name': 'Games found accuracy',
            'status': 'FAIL',
            'message': f'Expected {actual_games} games, got {games_found}',
            'expected': actual_games,
            'actual': games_found
        })
        results['failed'] += 1

    # =========================================================================
    # CHECK 2: Games expected calculation
    # =========================================================================
    total_available = get_total_games_available(client, player_lookup, game_date)
    expected_games_expected = min(total_available, 10)

    if feature['games_expected'] == expected_games_expected:
        results['checks'].append({
            'name': 'Games expected calculation',
            'status': 'PASS',
            'message': f'{feature["games_expected"]} = min({total_available}, 10)'
        })
        results['passed'] += 1
    else:
        results['checks'].append({
            'name': 'Games expected calculation',
            'status': 'FAIL',
            'message': f'Expected {expected_games_expected}, got {feature["games_expected"]}',
            'total_available': total_available
        })
        results['failed'] += 1

    # =========================================================================
    # CHECK 3: is_complete flag accuracy
    # =========================================================================
    expected_is_complete = games_found >= feature['games_expected']

    if feature['is_complete'] == expected_is_complete:
        results['checks'].append({
            'name': 'is_complete flag',
            'status': 'PASS',
            'message': f'is_complete={feature["is_complete"]} ({games_found} >= {feature["games_expected"]})'
        })
        results['passed'] += 1
    else:
        results['checks'].append({
            'name': 'is_complete flag',
            'status': 'FAIL',
            'message': f'Expected is_complete={expected_is_complete}, got {feature["is_complete"]}'
        })
        results['failed'] += 1

    # =========================================================================
    # CHECK 4: is_bootstrap flag accuracy
    # =========================================================================
    expected_is_bootstrap = feature['games_expected'] < 10

    if feature['is_bootstrap'] == expected_is_bootstrap:
        results['checks'].append({
            'name': 'is_bootstrap flag',
            'status': 'PASS',
            'message': f'is_bootstrap={feature["is_bootstrap"]} (games_expected={feature["games_expected"]} < 10)'
        })
        results['passed'] += 1
    else:
        results['checks'].append({
            'name': 'is_bootstrap flag',
            'status': 'FAIL',
            'message': f'Expected is_bootstrap={expected_is_bootstrap}, got {feature["is_bootstrap"]}'
        })
        results['failed'] += 1

    # =========================================================================
    # CHECK 5: Contributing game dates match actual games
    # =========================================================================
    contributing_dates = feature.get('contributing_game_dates', [])
    # Handle numpy/pandas arrays
    if hasattr(contributing_dates, 'tolist'):
        contributing_dates = contributing_dates.tolist()
    if contributing_dates is None:
        contributing_dates = []

    raw_dates = [g['game_date'] for g in raw_games[:10]]

    # Convert to comparable format
    if len(contributing_dates) > 0 and len(raw_dates) > 0:
        # Handle different date formats - normalize to YYYY-MM-DD
        contributing_set = set()
        for d in contributing_dates:
            if isinstance(d, str):
                # Handle timestamps like '2026-01-14 00:00:00'
                d_str = d.split()[0] if ' ' in d else d
            elif hasattr(d, 'strftime'):
                d_str = d.strftime('%Y-%m-%d')
            else:
                d_str = str(d).split()[0]
            contributing_set.add(d_str)

        raw_set = set()
        for d in raw_dates:
            if isinstance(d, str):
                d_str = d.split()[0] if ' ' in d else d
            elif hasattr(d, 'strftime'):
                d_str = d.strftime('%Y-%m-%d')
            else:
                d_str = str(d).split()[0]
            raw_set.add(d_str)

        if contributing_set == raw_set:
            results['checks'].append({
                'name': 'Contributing dates match',
                'status': 'PASS',
                'message': f'{len(contributing_dates)} dates match raw game dates'
            })
            results['passed'] += 1
        else:
            missing = raw_set - contributing_set
            extra = contributing_set - raw_set
            results['checks'].append({
                'name': 'Contributing dates match',
                'status': 'FAIL',
                'message': f'Dates mismatch: missing={missing}, extra={extra}'
            })
            results['failed'] += 1
    elif len(contributing_dates) == 0 and len(raw_dates) == 0:
        results['checks'].append({
            'name': 'Contributing dates match',
            'status': 'PASS',
            'message': 'No games, no dates (correct)'
        })
        results['passed'] += 1
    else:
        results['checks'].append({
            'name': 'Contributing dates match',
            'status': 'WARN',
            'message': f'contributing_dates={len(contributing_dates)}, raw_games={len(raw_dates)}'
        })
        results['warnings'] += 1

    # =========================================================================
    # CHECK 6: Points average calculation (if features available)
    # NOTE: The feature store uses Phase 4 (player_daily_cache) when available,
    # which may differ slightly from raw Phase 3 (player_game_summary) data.
    # We check against Phase 4 cache first, then raw data as fallback.
    # =========================================================================
    features_arr = feature.get('features', [])
    feature_names_arr = feature.get('feature_names', [])
    # Handle numpy/pandas arrays
    if hasattr(features_arr, 'tolist'):
        features_arr = features_arr.tolist()
    if hasattr(feature_names_arr, 'tolist'):
        feature_names_arr = feature_names_arr.tolist()

    if features_arr and feature_names_arr and len(features_arr) > 0 and len(feature_names_arr) > 0:
        features_dict = dict(zip(feature_names_arr, features_arr))

        # Check points_avg_last_10
        if 'points_avg_last_10' in features_dict:
            actual_avg = features_dict['points_avg_last_10']

            # Try to get Phase 4 cache value (primary source)
            phase4_cache = get_phase4_cache_value(client, player_lookup, game_date)

            if phase4_cache and phase4_cache.get('points_avg_last_10') is not None:
                expected_avg = float(phase4_cache['points_avg_last_10'])
                source = 'Phase 4 cache'
            elif raw_games:
                expected_avg = calculate_expected_avg(raw_games, 'points', min(10, len(raw_games)))
                source = 'Phase 3 raw'
            else:
                expected_avg = None
                source = None

            if expected_avg is not None:
                diff = abs(expected_avg - actual_avg)
                pct_diff = diff / max(expected_avg, 0.01) * 100

                if pct_diff <= TOLERANCE * 100:
                    results['checks'].append({
                        'name': 'points_avg_last_10 calculation',
                        'status': 'PASS',
                        'message': f'{actual_avg:.2f} matches {source} {expected_avg:.2f} (diff: {pct_diff:.2f}%)'
                    })
                    results['passed'] += 1
                else:
                    # Not a failure if it matches Phase 4 but not Phase 3
                    if source == 'Phase 3 raw' and phase4_cache:
                        results['checks'].append({
                            'name': 'points_avg_last_10 calculation',
                            'status': 'WARN',
                            'message': f'Differs from Phase 3 raw ({expected_avg:.2f}) but may match Phase 4 cache',
                            'expected': expected_avg,
                            'actual': actual_avg
                        })
                        results['warnings'] += 1
                    else:
                        results['checks'].append({
                            'name': 'points_avg_last_10 calculation',
                            'status': 'FAIL',
                            'message': f'Expected {expected_avg:.2f} ({source}), got {actual_avg:.2f} (diff: {pct_diff:.2f}%)',
                            'expected': expected_avg,
                            'actual': actual_avg
                        })
                        results['failed'] += 1

    # Calculate overall status
    if results['failed'] > 0:
        results['overall'] = 'FAIL'
    elif results['warnings'] > 0:
        results['overall'] = 'WARN'
    elif results['passed'] > 0:
        results['overall'] = 'PASS'

    return results


def print_results(results: Dict, verbose: bool = False):
    """Print validation results for a player."""
    status_emoji = {
        'PASS': '✅',
        'FAIL': '❌',
        'WARN': '⚠️',
        'SKIP': '⏭️',
        'UNKNOWN': '❓'
    }

    emoji = status_emoji.get(results['overall'], '❓')
    print(f"\n{emoji} {results['player_lookup']} ({results['game_date']})")
    print(f"   Passed: {results['passed']} | Failed: {results['failed']} | Warnings: {results['warnings']}")

    if verbose or results['failed'] > 0:
        for check in results['checks']:
            check_emoji = status_emoji.get(check['status'], '❓')
            print(f"   {check_emoji} {check['name']}: {check['message']}")


def main():
    parser = argparse.ArgumentParser(
        description='Spot Check Tool for ML Feature Store Validation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Quick spot check (5 random players from yesterday)
    python bin/spot_check_features.py

    # Check specific player
    python bin/spot_check_features.py --player lebron_james

    # Check specific date with 10 random players
    python bin/spot_check_features.py --date 2026-01-21 --count 10

    # Verbose output
    python bin/spot_check_features.py --verbose
        """
    )

    parser.add_argument('--player', '-p', type=str, default=None,
                       help='Specific player to check (player_lookup format)')
    parser.add_argument('--date', '-d', type=str, default=None,
                       help='Date to check (YYYY-MM-DD, default: yesterday)')
    parser.add_argument('--count', '-c', type=int, default=5,
                       help='Number of random players to check (default: 5)')
    parser.add_argument('--all-players', action='store_true',
                       help='Check all players for the date (can be slow)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Verbose output with raw data')

    args = parser.parse_args()

    print("\n" + "="*60)
    print("SPOT CHECK: ML Feature Store Validation")
    print("="*60)

    client = get_bq_client()

    # Determine date
    if args.date:
        game_date = datetime.strptime(args.date, '%Y-%m-%d').date()
    else:
        game_date = date.today() - timedelta(days=1)

    print(f"\nDate: {game_date}")

    # Get players to check
    if args.player:
        players = [args.player]
    elif args.all_players:
        # Get all players for the date
        query = f"""
        SELECT DISTINCT player_lookup
        FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
        WHERE game_date = '{game_date}'
          AND historical_completeness IS NOT NULL
        """
        result = client.query(query).to_dataframe()
        players = result['player_lookup'].tolist()
        print(f"Checking all {len(players)} players with historical_completeness")
    else:
        players = get_random_players(client, game_date, args.count)
        if not players:
            print(f"\n⚠️  No players found with historical_completeness for {game_date}")
            print("   This date may not have been processed yet with the new feature.")
            sys.exit(1)
        print(f"Checking {len(players)} random players")

    # Run validations
    all_results = []
    total_passed = 0
    total_failed = 0
    total_warnings = 0

    for player in players:
        results = validate_player(client, player, game_date, args.verbose)
        all_results.append(results)
        print_results(results, args.verbose)

        total_passed += results['passed']
        total_failed += results['failed']
        total_warnings += results['warnings']

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Players checked: {len(players)}")
    print(f"Total checks: {total_passed + total_failed + total_warnings}")
    print(f"  Passed: {total_passed}")
    print(f"  Failed: {total_failed}")
    print(f"  Warnings: {total_warnings}")

    if total_failed > 0:
        print(f"\n❌ VALIDATION FAILED - {total_failed} checks failed")
        sys.exit(1)
    elif total_warnings > 0:
        print(f"\n⚠️  VALIDATION PASSED WITH WARNINGS")
        sys.exit(0)
    else:
        print(f"\n✅ ALL VALIDATIONS PASSED")
        sys.exit(0)


if __name__ == '__main__':
    main()
