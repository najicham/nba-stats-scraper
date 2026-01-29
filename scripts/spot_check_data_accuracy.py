#!/usr/bin/env python3
"""
Comprehensive Data Accuracy Spot Check System

Validates data accuracy by randomly sampling player-date combinations and
verifying that calculated fields match expected values from raw data.

This system helps detect:
- Calculation errors in rolling averages
- Missing data joins (e.g., team stats for usage_rate)
- Data transformation bugs (e.g., minutes parsing)
- Cross-table consistency issues

Checks Implemented:
- Check A: Rolling averages (points_avg_last_5, points_avg_last_10)
- Check B: Usage rate calculation
- Check C: Minutes parsing from MM:SS format
- Check D: ML feature store consistency
- Check E: player_daily_cache L0 features
- Check F: Points total arithmetic (points = 2×2P + 3×3P + FT)

Usage:
    # Run 20 random spot checks
    python scripts/spot_check_data_accuracy.py --samples 20

    # Check specific player and date
    python scripts/spot_check_data_accuracy.py --player-id 203566 --date 2025-12-15

    # Check specific date range
    python scripts/spot_check_data_accuracy.py --start-date 2025-11-01 --end-date 2025-11-30 --samples 50

    # Verbose output with SQL queries
    python scripts/spot_check_data_accuracy.py --samples 10 --verbose

    # Only run specific checks
    python scripts/spot_check_data_accuracy.py --samples 10 --checks rolling_avg,usage_rate

Created: 2026-01-26
Purpose: Automated data accuracy verification
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
TOLERANCE = 0.02  # 2% tolerance for averages


def get_bq_client():
    """Get BigQuery client."""
    from google.cloud import bigquery
    return bigquery.Client()


# Import bigquery module at top level for QueryJobConfig
from google.cloud import bigquery


def get_random_samples(
    client,
    start_date: date,
    end_date: date,
    count: int = 20
) -> List[Tuple[str, str, date]]:
    """
    Get random player-date combinations for spot checking.

    Returns list of tuples: (player_lookup, universal_player_id, game_date)
    """
    project_id = client.project

    query = f"""
    SELECT DISTINCT
        player_lookup,
        universal_player_id,
        game_date
    FROM `{project_id}.nba_analytics.player_game_summary`
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      AND minutes_played > 0  -- Only check players who actually played
      AND points IS NOT NULL
    ORDER BY RAND()
    LIMIT {count}
    """

    results = list(client.query(query).result(timeout=60))
    return [(row.player_lookup, row.universal_player_id, row.game_date) for row in results]


def check_rolling_averages(
    client,
    player_lookup: str,
    game_date: date,
    verbose: bool = False
) -> Dict:
    """
    Check A: Verify rolling average calculations (points_avg_last_5, points_avg_last_10).

    Validates that stored rolling averages match recalculated values from raw game history.
    Note: Rolling averages are stored in player_daily_cache, keyed by cache_date (day before game).
    """
    project_id = client.project
    results = {
        'check_name': 'Rolling Averages',
        'status': 'UNKNOWN',
        'details': [],
        'errors': []
    }

    try:
        # Cache date is the day before game (contains features "as of" that date)
        from datetime import timedelta
        cache_date = game_date - timedelta(days=1)

        # Get stored values from player_daily_cache
        stored_query = f"""
        SELECT
            player_lookup,
            cache_date,
            points_avg_last_5,
            points_avg_last_10
        FROM `{project_id}.nba_precompute.player_daily_cache`
        WHERE player_lookup = @player_lookup
          AND cache_date = @cache_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("cache_date", "DATE", cache_date),
            ]
        )

        stored_results = list(client.query(stored_query, job_config=job_config).result(timeout=60))

        if not stored_results:
            results['status'] = 'SKIP'
            results['details'].append(f'No cache data found for cache_date={cache_date}')
            return results

        stored = stored_results[0]

        # Get raw game history for recalculation (games before cache_date)
        history_query = f"""
        SELECT
            game_date,
            points
        FROM `{project_id}.nba_analytics.player_game_summary`
        WHERE player_lookup = @player_lookup
          AND game_date < @cache_date
        ORDER BY game_date DESC
        LIMIT 10
        """

        history_results = list(client.query(history_query, job_config=job_config).result(timeout=60))

        if verbose:
            logger.info(f"  Found {len(history_results)} previous games for {player_lookup}")

        # Calculate expected averages
        points_list = [row.points for row in history_results if row.points is not None]

        checks_passed = 0
        checks_failed = 0

        # Check points_avg_last_5
        if stored.points_avg_last_5 is not None and len(points_list) >= 5:
            expected_avg_5 = sum(points_list[:5]) / 5
            actual_avg_5 = float(stored.points_avg_last_5)
            diff_pct_5 = abs(expected_avg_5 - actual_avg_5) / max(expected_avg_5, 0.01) * 100

            if diff_pct_5 <= TOLERANCE * 100:
                results['details'].append(f'✓ points_avg_last_5: {actual_avg_5:.2f} matches expected {expected_avg_5:.2f}')
                checks_passed += 1
            else:
                results['details'].append(
                    f'✗ points_avg_last_5: Expected {expected_avg_5:.2f}, Got {actual_avg_5:.2f} '
                    f'(diff: {diff_pct_5:.2f}%)'
                )
                checks_failed += 1
                results['errors'].append(f'points_avg_last_5 mismatch: {diff_pct_5:.2f}%')

        # Check points_avg_last_10
        if stored.points_avg_last_10 is not None and len(points_list) >= 10:
            expected_avg_10 = sum(points_list[:10]) / 10
            actual_avg_10 = float(stored.points_avg_last_10)
            diff_pct_10 = abs(expected_avg_10 - actual_avg_10) / max(expected_avg_10, 0.01) * 100

            if diff_pct_10 <= TOLERANCE * 100:
                results['details'].append(f'✓ points_avg_last_10: {actual_avg_10:.2f} matches expected {expected_avg_10:.2f}')
                checks_passed += 1
            else:
                results['details'].append(
                    f'✗ points_avg_last_10: Expected {expected_avg_10:.2f}, Got {actual_avg_10:.2f} '
                    f'(diff: {diff_pct_10:.2f}%)'
                )
                checks_failed += 1
                results['errors'].append(f'points_avg_last_10 mismatch: {diff_pct_10:.2f}%')

        # Determine overall status
        if checks_failed > 0:
            results['status'] = 'FAIL'
        elif checks_passed > 0:
            results['status'] = 'PASS'
        else:
            results['status'] = 'SKIP'
            results['details'].append('Insufficient data for rolling average checks')

    except Exception as e:
        results['status'] = 'ERROR'
        results['errors'].append(f'Exception: {str(e)}')
        logger.error(f"Error checking rolling averages: {e}", exc_info=True)

    return results


def check_usage_rate(
    client,
    player_lookup: str,
    game_date: date,
    verbose: bool = False
) -> Dict:
    """
    Check B: Verify usage_rate calculation.

    Formula: USG% = 100 × (Player FGA + 0.44 × FTA + TO) × 48 / (MP × Team Usage)
    Where Team Usage = Team FGA + 0.44 × Team FTA + Team TO
    """
    project_id = client.project
    results = {
        'check_name': 'Usage Rate Calculation',
        'status': 'UNKNOWN',
        'details': [],
        'errors': []
    }

    try:
        # Get player stats and team stats
        # NOTE: game_id format differs between tables:
        #   - player_game_summary uses AWAY_HOME format (e.g., 20260128_NYK_TOR)
        #   - team_offense_game_summary uses HOME_AWAY format (e.g., 20260128_TOR_NYK)
        # We handle this by creating a reversed game_id for the join
        # NOTE: team_offense_game_summary often has duplicate records per team-game
        # with different game_id formats (HOME_AWAY vs AWAY_HOME). We use ROW_NUMBER()
        # to deduplicate, keeping the record with higher possessions (more complete data).
        query = f"""
        WITH player_stats AS (
            SELECT
                player_lookup,
                game_date,
                game_id,
                -- Create reversed game_id: YYYYMMDD_AWAY_HOME -> YYYYMMDD_HOME_AWAY
                CONCAT(
                    SPLIT(game_id, '_')[OFFSET(0)], '_',
                    SPLIT(game_id, '_')[OFFSET(2)], '_',
                    SPLIT(game_id, '_')[OFFSET(1)]
                ) as game_id_reversed,
                team_abbr,
                usage_rate,
                minutes_played,
                fg_attempts,
                ft_attempts,
                turnovers
            FROM `{project_id}.nba_analytics.player_game_summary`
            WHERE player_lookup = @player_lookup
              AND game_date = @game_date
        ),
        team_stats_raw AS (
            SELECT
                game_id,
                team_abbr,
                fg_attempts as team_fg_attempts,
                ft_attempts as team_ft_attempts,
                turnovers as team_turnovers,
                -- Calculate possessions for ranking (higher = more complete data)
                COALESCE(fg_attempts, 0) + 0.44 * COALESCE(ft_attempts, 0) + COALESCE(turnovers, 0) as possessions
            FROM `{project_id}.nba_analytics.team_offense_game_summary`
            WHERE game_date = @game_date  -- Required for partition elimination
        ),
        team_stats_deduped AS (
            -- Deduplicate by keeping the record with highest possessions per team
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY team_abbr
                    ORDER BY possessions DESC
                ) as rn
            FROM team_stats_raw
        ),
        team_stats AS (
            SELECT game_id, team_abbr, team_fg_attempts, team_ft_attempts, team_turnovers
            FROM team_stats_deduped
            WHERE rn = 1
        )
        SELECT
            p.*,
            t.team_fg_attempts,
            t.team_ft_attempts,
            t.team_turnovers
        FROM player_stats p
        LEFT JOIN team_stats t
            ON p.team_abbr = t.team_abbr
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        query_results = list(client.query(query, job_config=job_config).result(timeout=60))

        if not query_results:
            results['status'] = 'SKIP'
            results['details'].append('No data found for player-date combination')
            return results

        row = query_results[0]

        # Check if we have all required data
        if row.minutes_played is None or row.minutes_played == 0:
            results['status'] = 'SKIP'
            results['details'].append('Player did not play (minutes = 0)')
            return results

        if (row.team_fg_attempts is None or
            row.team_ft_attempts is None or
            row.team_turnovers is None):
            if row.usage_rate is not None:
                results['status'] = 'FAIL'
                results['errors'].append('usage_rate is not NULL but team stats are missing')
                results['details'].append('✗ usage_rate should be NULL when team stats are unavailable')
            else:
                results['status'] = 'PASS'
                results['details'].append('✓ usage_rate is NULL (team stats unavailable, expected)')
            return results

        # Calculate expected usage rate
        player_poss = (row.fg_attempts or 0) + 0.44 * (row.ft_attempts or 0) + (row.turnovers or 0)
        team_poss = row.team_fg_attempts + 0.44 * row.team_ft_attempts + row.team_turnovers

        if team_poss == 0:
            results['status'] = 'SKIP'
            results['details'].append('Team possessions = 0, cannot calculate')
            return results

        expected_usage = 100.0 * player_poss * 48.0 / (float(row.minutes_played) * team_poss)

        if row.usage_rate is None:
            results['status'] = 'FAIL'
            results['errors'].append('usage_rate is NULL but should be calculated')
            results['details'].append(f'✗ Expected usage_rate: {expected_usage:.2f}, Got: NULL')
        else:
            actual_usage = float(row.usage_rate)
            diff_pct = abs(expected_usage - actual_usage) / max(expected_usage, 0.01) * 100

            if diff_pct <= TOLERANCE * 100:
                results['status'] = 'PASS'
                results['details'].append(
                    f'✓ usage_rate: {actual_usage:.2f} matches expected {expected_usage:.2f}'
                )
            else:
                results['status'] = 'FAIL'
                results['errors'].append(f'usage_rate mismatch: {diff_pct:.2f}%')
                results['details'].append(
                    f'✗ Expected {expected_usage:.2f}, Got {actual_usage:.2f} (diff: {diff_pct:.2f}%)'
                )

        if verbose:
            logger.info(f"  Player poss: {player_poss:.2f}, Team poss: {team_poss:.2f}")
            logger.info(f"  Minutes: {row.minutes_played}, Expected usage: {expected_usage:.2f}")

    except Exception as e:
        results['status'] = 'ERROR'
        results['errors'].append(f'Exception: {str(e)}')
        logger.error(f"Error checking usage rate: {e}", exc_info=True)

    return results


def check_minutes_parsing(
    client,
    player_lookup: str,
    game_date: date,
    verbose: bool = False
) -> Dict:
    """
    Check C: Verify minutes_played correctly parsed from MM:SS format in raw gamebook.

    This is a regression test for the Nov 3, 2025 bug where _clean_numeric_columns()
    destroyed MM:SS format data.
    """
    project_id = client.project
    results = {
        'check_name': 'Minutes Parsing',
        'status': 'UNKNOWN',
        'details': [],
        'errors': []
    }

    try:
        # Get processed minutes
        processed_query = f"""
        SELECT
            player_lookup,
            game_date,
            game_id,
            minutes_played
        FROM `{project_id}.nba_analytics.player_game_summary`
        WHERE player_lookup = @player_lookup
          AND game_date = @game_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        processed_results = list(client.query(processed_query, job_config=job_config).result(timeout=60))

        if not processed_results:
            results['status'] = 'SKIP'
            results['details'].append('No processed data found')
            return results

        processed = processed_results[0]

        if processed.minutes_played is None or processed.minutes_played == 0:
            results['status'] = 'SKIP'
            results['details'].append('Player did not play (minutes = 0 or NULL)')
            return results

        # Get raw minutes from gamebook
        raw_query = f"""
        SELECT
            player_name,
            game_id,
            minutes
        FROM `{project_id}.nba_raw.nbac_gamebook_player_stats`
        WHERE game_id = @game_id
          AND LOWER(player_name) = LOWER(@player_lookup)
        LIMIT 1
        """

        raw_job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_id", "STRING", processed.game_id),
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup.replace('_', ' ')),
            ]
        )

        raw_results = list(client.query(raw_query, job_config=raw_job_config).result(timeout=60))

        if not raw_results:
            results['status'] = 'SKIP'
            results['details'].append('No raw gamebook data found (may use different data source)')
            return results

        raw = raw_results[0]

        if raw.minutes is None or raw.minutes == 'DNP' or raw.minutes == '':
            results['status'] = 'SKIP'
            results['details'].append('No minutes in raw data')
            return results

        # Parse MM:SS format
        if ':' in str(raw.minutes):
            parts = str(raw.minutes).split(':')
            expected_minutes = int(parts[0]) + int(parts[1]) / 60.0
            actual_minutes = float(processed.minutes_played)

            diff = abs(expected_minutes - actual_minutes)

            if diff < 0.1:  # Allow small rounding error
                results['status'] = 'PASS'
                results['details'].append(
                    f'✓ minutes_played: {actual_minutes:.2f} matches parsed {expected_minutes:.2f} '
                    f'(raw: {raw.minutes})'
                )
            else:
                results['status'] = 'FAIL'
                results['errors'].append(f'Minutes parsing error: {diff:.2f} minute difference')
                results['details'].append(
                    f'✗ Expected {expected_minutes:.2f} from "{raw.minutes}", Got {actual_minutes:.2f}'
                )
        else:
            # Raw data is already numeric
            results['status'] = 'PASS'
            results['details'].append(f'✓ Raw minutes already numeric: {raw.minutes}')

    except Exception as e:
        results['status'] = 'ERROR'
        results['errors'].append(f'Exception: {str(e)}')
        logger.error(f"Error checking minutes parsing: {e}", exc_info=True)

    return results


def check_ml_feature_consistency(
    client,
    player_lookup: str,
    game_date: date,
    verbose: bool = False
) -> Dict:
    """
    Check D: Verify ML feature store consistency with source tables.

    Validates that ml_feature_store_v2 values match source tables like
    player_daily_cache, team_offense_game_summary, etc.
    Note: Rolling averages come from player_daily_cache (cache_date = day before game).
    """
    project_id = client.project
    results = {
        'check_name': 'ML Feature Store Consistency',
        'status': 'UNKNOWN',
        'details': [],
        'errors': []
    }

    try:
        # Cache date is the day before game (contains features "as of" that date)
        from datetime import timedelta
        cache_date = game_date - timedelta(days=1)

        # Get ML features
        ml_query = f"""
        SELECT
            player_lookup,
            game_date,
            features,
            feature_names
        FROM `{project_id}.nba_predictions.ml_feature_store_v2`
        WHERE player_lookup = @player_lookup
          AND game_date = @game_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                bigquery.ScalarQueryParameter("cache_date", "DATE", cache_date),
            ]
        )

        ml_results = list(client.query(ml_query, job_config=job_config).result(timeout=60))

        if not ml_results:
            results['status'] = 'SKIP'
            results['details'].append('No ML feature store record found')
            return results

        ml_row = ml_results[0]

        # Parse features into dict
        features_dict = {}
        if ml_row.features and ml_row.feature_names:
            features_dict = dict(zip(ml_row.feature_names, ml_row.features))

        if not features_dict:
            results['status'] = 'SKIP'
            results['details'].append('No features available in ML store')
            return results

        # Get source data from player_daily_cache
        source_query = f"""
        SELECT
            points_avg_last_5,
            points_avg_last_10
        FROM `{project_id}.nba_precompute.player_daily_cache`
        WHERE player_lookup = @player_lookup
          AND cache_date = @cache_date
        """

        source_results = list(client.query(source_query, job_config=job_config).result(timeout=60))

        if not source_results:
            results['status'] = 'SKIP'
            results['details'].append(f'No source cache data found for cache_date={cache_date}')
            return results

        source = source_results[0]

        checks_passed = 0
        checks_failed = 0

        # Check points_avg_last_5
        if 'points_avg_last_5' in features_dict and source.points_avg_last_5 is not None:
            ml_value = features_dict['points_avg_last_5']
            source_value = float(source.points_avg_last_5)
            diff_pct = abs(ml_value - source_value) / max(source_value, 0.01) * 100

            if diff_pct <= TOLERANCE * 100:
                results['details'].append(
                    f'✓ points_avg_last_5: ML {ml_value:.2f} matches source {source_value:.2f}'
                )
                checks_passed += 1
            else:
                results['details'].append(
                    f'✗ points_avg_last_5: ML {ml_value:.2f}, source {source_value:.2f} '
                    f'(diff: {diff_pct:.2f}%)'
                )
                results['errors'].append(f'points_avg_last_5 mismatch: {diff_pct:.2f}%')
                checks_failed += 1

        # Check points_avg_last_10
        if 'points_avg_last_10' in features_dict and source.points_avg_last_10 is not None:
            ml_value = features_dict['points_avg_last_10']
            source_value = float(source.points_avg_last_10)
            diff_pct = abs(ml_value - source_value) / max(source_value, 0.01) * 100

            if diff_pct <= TOLERANCE * 100:
                results['details'].append(
                    f'✓ points_avg_last_10: ML {ml_value:.2f} matches source {source_value:.2f}'
                )
                checks_passed += 1
            else:
                results['details'].append(
                    f'✗ points_avg_last_10: ML {ml_value:.2f}, source {source_value:.2f} '
                    f'(diff: {diff_pct:.2f}%)'
                )
                results['errors'].append(f'points_avg_last_10 mismatch: {diff_pct:.2f}%')
                checks_failed += 1

        # Determine overall status
        if checks_failed > 0:
            results['status'] = 'FAIL'
        elif checks_passed > 0:
            results['status'] = 'PASS'
        else:
            results['status'] = 'SKIP'
            results['details'].append('No comparable features found')

    except Exception as e:
        results['status'] = 'ERROR'
        results['errors'].append(f'Exception: {str(e)}')
        logger.error(f"Error checking ML feature consistency: {e}", exc_info=True)

    return results


def check_player_daily_cache(
    client,
    player_lookup: str,
    game_date: date,
    verbose: bool = False
) -> Dict:
    """
    Check E: Verify player_daily_cache L0 features match computed values.

    The cache is keyed by cache_date (not game_date), so we check the day before
    the game to see if cached features match source tables.
    """
    project_id = client.project
    results = {
        'check_name': 'Player Daily Cache L0 Features',
        'status': 'UNKNOWN',
        'details': [],
        'errors': []
    }

    try:
        # Cache date is the day before game (contains features "as of" that date)
        cache_date = game_date - timedelta(days=1)

        # Get cached values
        cache_query = f"""
        SELECT
            player_lookup,
            cache_date,
            points_avg_last_5,
            points_avg_last_10,
            minutes_avg_last_10
        FROM `{project_id}.nba_precompute.player_daily_cache`
        WHERE player_lookup = @player_lookup
          AND cache_date = @cache_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("cache_date", "DATE", cache_date),
            ]
        )

        cache_results = list(client.query(cache_query, job_config=job_config).result(timeout=60))

        if not cache_results:
            results['status'] = 'SKIP'
            results['details'].append(f'No cache record found for cache_date={cache_date}')
            return results

        cache = cache_results[0]

        # Get source data (player_game_summary) as of cache_date
        source_query = f"""
        WITH recent_games AS (
            SELECT
                game_date,
                points,
                minutes_played,
                ROW_NUMBER() OVER (ORDER BY game_date DESC) as game_rank
            FROM `{project_id}.nba_analytics.player_game_summary`
            WHERE player_lookup = @player_lookup
              AND game_date < @cache_date
            ORDER BY game_date DESC
            LIMIT 10
        )
        SELECT
            AVG(CASE WHEN game_rank <= 5 THEN points END) as expected_points_avg_5,
            AVG(points) as expected_points_avg_10,
            AVG(minutes_played) as expected_minutes_avg_10
        FROM recent_games
        """

        source_results = list(client.query(source_query, job_config=job_config).result(timeout=60))

        if not source_results:
            results['status'] = 'SKIP'
            results['details'].append('No source data found for comparison')
            return results

        source = source_results[0]

        checks_passed = 0
        checks_failed = 0

        # Check points_avg_last_5
        if cache.points_avg_last_5 is not None and source.expected_points_avg_5 is not None:
            cached_value = float(cache.points_avg_last_5)
            expected_value = float(source.expected_points_avg_5)
            diff_pct = abs(cached_value - expected_value) / max(expected_value, 0.01) * 100

            if diff_pct <= TOLERANCE * 100:
                results['details'].append(
                    f'✓ points_avg_last_5: Cached {cached_value:.2f} matches expected {expected_value:.2f}'
                )
                checks_passed += 1
            else:
                results['details'].append(
                    f'✗ points_avg_last_5: Cached {cached_value:.2f}, expected {expected_value:.2f} '
                    f'(diff: {diff_pct:.2f}%)'
                )
                results['errors'].append(f'points_avg_last_5 cache mismatch: {diff_pct:.2f}%')
                checks_failed += 1

        # Check points_avg_last_10
        if cache.points_avg_last_10 is not None and source.expected_points_avg_10 is not None:
            cached_value = float(cache.points_avg_last_10)
            expected_value = float(source.expected_points_avg_10)
            diff_pct = abs(cached_value - expected_value) / max(expected_value, 0.01) * 100

            if diff_pct <= TOLERANCE * 100:
                results['details'].append(
                    f'✓ points_avg_last_10: Cached {cached_value:.2f} matches expected {expected_value:.2f}'
                )
                checks_passed += 1
            else:
                results['details'].append(
                    f'✗ points_avg_last_10: Cached {cached_value:.2f}, expected {expected_value:.2f} '
                    f'(diff: {diff_pct:.2f}%)'
                )
                results['errors'].append(f'points_avg_last_10 cache mismatch: {diff_pct:.2f}%')
                checks_failed += 1

        # Determine overall status
        if checks_failed > 0:
            results['status'] = 'FAIL'
        elif checks_passed > 0:
            results['status'] = 'PASS'
        else:
            results['status'] = 'SKIP'
            results['details'].append('No comparable cache fields found')

    except Exception as e:
        results['status'] = 'ERROR'
        results['errors'].append(f'Exception: {str(e)}')
        logger.error(f"Error checking player daily cache: {e}", exc_info=True)

    return results


def check_points_total(
    client,
    player_lookup: str,
    game_date: date,
    verbose: bool = False
) -> Dict:
    """
    Check F: Verify points total matches arithmetic formula.

    Validates that points = 2×(FG made - 3P made) + 3×(3P made) + FT made
    This catches data corruption in the points field.
    """
    project_id = client.project
    results = {
        'check_name': 'Points Total Arithmetic',
        'status': 'UNKNOWN',
        'details': [],
        'errors': []
    }

    try:
        # Get player stats
        query = f"""
        SELECT
            player_lookup,
            game_date,
            points,
            fg_makes,
            three_pt_makes,
            ft_makes
        FROM `{project_id}.nba_analytics.player_game_summary`
        WHERE player_lookup = @player_lookup
          AND game_date = @game_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        query_results = list(client.query(query, job_config=job_config).result(timeout=60))

        if not query_results:
            results['status'] = 'SKIP'
            results['details'].append('No data found for player-date combination')
            return results

        row = query_results[0]

        # Check if we have all required data
        if row.points is None:
            results['status'] = 'SKIP'
            results['details'].append('Points is NULL')
            return results

        if row.fg_makes is None or row.three_pt_makes is None or row.ft_makes is None:
            results['status'] = 'SKIP'
            results['details'].append('Missing field goal or free throw data')
            return results

        # Calculate expected points: 2×(FG - 3P) + 3×3P + FT
        two_pt_makes = row.fg_makes - row.three_pt_makes
        expected_points = 2 * two_pt_makes + 3 * row.three_pt_makes + row.ft_makes
        actual_points = row.points

        if expected_points == actual_points:
            results['status'] = 'PASS'
            results['details'].append(
                f'✓ points: {actual_points} matches calculated '
                f'(2×{two_pt_makes} + 3×{row.three_pt_makes} + {row.ft_makes})'
            )
        else:
            results['status'] = 'FAIL'
            diff = actual_points - expected_points
            results['errors'].append(f'Points mismatch: expected {expected_points}, got {actual_points} (diff: {diff})')
            results['details'].append(
                f'✗ Expected {expected_points} (2×{two_pt_makes} + 3×{row.three_pt_makes} + {row.ft_makes}), '
                f'Got {actual_points}'
            )

        if verbose:
            logger.info(f"  FG: {row.fg_makes}, 3P: {row.three_pt_makes}, FT: {row.ft_makes}")
            logger.info(f"  2P: {two_pt_makes}, Expected points: {expected_points}")

    except Exception as e:
        results['status'] = 'ERROR'
        results['errors'].append(f'Exception: {str(e)}')
        logger.error(f"Error checking points total: {e}", exc_info=True)

    return results


def run_spot_check(
    client,
    player_lookup: str,
    universal_player_id: str,
    game_date: date,
    checks_to_run: List[str],
    verbose: bool = False
) -> Dict:
    """Run all spot checks for a single player-date combination."""

    all_checks = {
        'rolling_avg': check_rolling_averages,
        'usage_rate': check_usage_rate,
        'minutes': check_minutes_parsing,
        'ml_features': check_ml_feature_consistency,
        'cache': check_player_daily_cache,
        'points_total': check_points_total
    }

    spot_check_result = {
        'player_lookup': player_lookup,
        'universal_player_id': universal_player_id,
        'game_date': str(game_date),
        'checks': [],
        'overall_status': 'UNKNOWN',
        'passed_count': 0,
        'failed_count': 0,
        'skipped_count': 0,
        'error_count': 0
    }

    for check_name in checks_to_run:
        if check_name not in all_checks:
            logger.warning(f"Unknown check: {check_name}, skipping")
            continue

        check_func = all_checks[check_name]
        check_result = check_func(client, player_lookup, game_date, verbose)
        spot_check_result['checks'].append(check_result)

        if check_result['status'] == 'PASS':
            spot_check_result['passed_count'] += 1
        elif check_result['status'] == 'FAIL':
            spot_check_result['failed_count'] += 1
        elif check_result['status'] == 'SKIP':
            spot_check_result['skipped_count'] += 1
        elif check_result['status'] == 'ERROR':
            spot_check_result['error_count'] += 1

    # Determine overall status
    if spot_check_result['error_count'] > 0:
        spot_check_result['overall_status'] = 'ERROR'
    elif spot_check_result['failed_count'] > 0:
        spot_check_result['overall_status'] = 'FAIL'
    elif spot_check_result['passed_count'] > 0:
        spot_check_result['overall_status'] = 'PASS'
    else:
        spot_check_result['overall_status'] = 'SKIP'

    return spot_check_result


def print_report(all_results: List[Dict], verbose: bool = False):
    """Print comprehensive spot check report."""

    status_emoji = {
        'PASS': '✅',
        'FAIL': '❌',
        'SKIP': '⏭️',
        'ERROR': '⚠️',
        'UNKNOWN': '❓'
    }

    print("\n" + "="*70)
    print("SPOT CHECK REPORT: Data Accuracy Verification")
    print("="*70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Samples: {len(all_results)} player-date combinations")

    # Calculate summary stats
    total_passed = sum(r['passed_count'] for r in all_results)
    total_failed = sum(r['failed_count'] for r in all_results)
    total_skipped = sum(r['skipped_count'] for r in all_results)
    total_errors = sum(r['error_count'] for r in all_results)
    total_checks = total_passed + total_failed + total_skipped + total_errors

    overall_pass_count = sum(1 for r in all_results if r['overall_status'] == 'PASS')
    overall_fail_count = sum(1 for r in all_results if r['overall_status'] == 'FAIL')

    print(f"\n{'='*70}")
    print("SUMMARY")
    print("="*70)
    print(f"Total checks: {total_checks}")
    print(f"  ✅ Passed:  {total_passed} ({total_passed/max(total_checks,1)*100:.1f}%)")
    print(f"  ❌ Failed:  {total_failed} ({total_failed/max(total_checks,1)*100:.1f}%)")
    print(f"  ⏭️  Skipped: {total_skipped} ({total_skipped/max(total_checks,1)*100:.1f}%)")
    print(f"  ⚠️  Errors:  {total_errors} ({total_errors/max(total_checks,1)*100:.1f}%)")
    print()
    print(f"Samples: {overall_pass_count}/{len(all_results)} passed ({overall_pass_count/max(len(all_results),1)*100:.1f}%)")

    # Print failures
    failures = [r for r in all_results if r['overall_status'] == 'FAIL']
    if failures:
        print(f"\n{'='*70}")
        print(f"FAILURES ({len(failures)})")
        print("="*70)

        for i, result in enumerate(failures, 1):
            print(f"\n{i}. Player: {result['player_lookup']} ({result['universal_player_id']})")
            print(f"   Date: {result['game_date']}")
            print(f"   Status: ❌ FAILED - {result['failed_count']} check(s) failed")

            for check in result['checks']:
                if check['status'] == 'FAIL':
                    print(f"\n   {status_emoji[check['status']]} {check['check_name']}:")
                    for error in check['errors']:
                        print(f"      - {error}")
                    if verbose:
                        for detail in check['details']:
                            print(f"      {detail}")

    # Print errors
    errors = [r for r in all_results if r['overall_status'] == 'ERROR']
    if errors:
        print(f"\n{'='*70}")
        print(f"ERRORS ({len(errors)})")
        print("="*70)

        for i, result in enumerate(errors, 1):
            print(f"\n{i}. Player: {result['player_lookup']} ({result['universal_player_id']})")
            print(f"   Date: {result['game_date']}")

            for check in result['checks']:
                if check['status'] == 'ERROR':
                    print(f"\n   ⚠️ {check['check_name']}:")
                    for error in check['errors']:
                        print(f"      - {error}")

    # Verbose: print all results
    if verbose:
        print(f"\n{'='*70}")
        print("ALL RESULTS (VERBOSE)")
        print("="*70)

        for result in all_results:
            emoji = status_emoji[result['overall_status']]
            print(f"\n{emoji} {result['player_lookup']} ({result['game_date']})")
            print(f"   Passed: {result['passed_count']} | Failed: {result['failed_count']} | "
                  f"Skipped: {result['skipped_count']} | Errors: {result['error_count']}")

            for check in result['checks']:
                print(f"\n   {status_emoji[check['status']]} {check['check_name']}:")
                for detail in check['details']:
                    print(f"      {detail}")

    print("\n" + "="*70)

    # Return exit code
    if total_failed > 0 or total_errors > 0:
        accuracy_pct = total_passed / max(total_checks, 1) * 100
        print(f"\n❌ SPOT CHECK FAILED - {accuracy_pct:.1f}% accuracy")
        return 1
    else:
        print("\n✅ ALL SPOT CHECKS PASSED")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description='Comprehensive Data Accuracy Spot Check System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run 20 random spot checks
    python scripts/spot_check_data_accuracy.py --samples 20

    # Check specific player and date
    python scripts/spot_check_data_accuracy.py --player-id 203566 --date 2025-12-15

    # Check specific date range
    python scripts/spot_check_data_accuracy.py --start-date 2025-11-01 --end-date 2025-11-30 --samples 50

    # Verbose output
    python scripts/spot_check_data_accuracy.py --samples 10 --verbose

    # Only run specific checks
    python scripts/spot_check_data_accuracy.py --samples 10 --checks rolling_avg,usage_rate
        """
    )

    parser.add_argument('--player-id', type=str, default=None,
                       help='Specific player ID to check (universal_player_id)')
    parser.add_argument('--player-lookup', type=str, default=None,
                       help='Specific player to check (player_lookup format)')
    parser.add_argument('--date', '-d', type=str, default=None,
                       help='Specific date to check (YYYY-MM-DD)')
    parser.add_argument('--start-date', type=str, default=None,
                       help='Start date for random sampling (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, default=None,
                       help='End date for random sampling (YYYY-MM-DD)')
    parser.add_argument('--samples', '-n', type=int, default=20,
                       help='Number of random samples (default: 20)')
    parser.add_argument('--checks', type=str, default='all',
                       help='Comma-separated list of checks to run (default: all). '
                            'Options: rolling_avg,usage_rate,minutes,ml_features,cache,points_total')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Verbose output with detailed results')

    args = parser.parse_args()

    # Parse checks
    if args.checks == 'all':
        checks_to_run = ['rolling_avg', 'usage_rate', 'minutes', 'ml_features', 'cache', 'points_total']
    else:
        checks_to_run = [c.strip() for c in args.checks.split(',')]

    # Initialize BigQuery client
    client = get_bq_client()

    # Determine samples to check
    samples = []

    if args.player_lookup and args.date:
        # Specific player and date
        game_date = datetime.strptime(args.date, '%Y-%m-%d').date()
        # Get universal_player_id for this player
        query = f"""
        SELECT DISTINCT universal_player_id
        FROM `{client.project}.nba_analytics.player_game_summary`
        WHERE player_lookup = '{args.player_lookup}'
        LIMIT 1
        """
        results = list(client.query(query).result(timeout=60))
        if results:
            universal_player_id = results[0].universal_player_id
            samples = [(args.player_lookup, universal_player_id, game_date)]
        else:
            print(f"Error: No data found for player {args.player_lookup}")
            sys.exit(1)

    elif args.player_id and args.date:
        # Specific player ID and date
        game_date = datetime.strptime(args.date, '%Y-%m-%d').date()
        # Get player_lookup for this ID
        query = f"""
        SELECT DISTINCT player_lookup
        FROM `{client.project}.nba_analytics.player_game_summary`
        WHERE universal_player_id = '{args.player_id}'
        LIMIT 1
        """
        results = list(client.query(query).result(timeout=60))
        if results:
            player_lookup = results[0].player_lookup
            samples = [(player_lookup, args.player_id, game_date)]
        else:
            print(f"Error: No data found for player ID {args.player_id}")
            sys.exit(1)

    else:
        # Random sampling
        if args.start_date:
            start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        else:
            start_date = date.today() - timedelta(days=30)

        if args.end_date:
            end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
        else:
            end_date = date.today() - timedelta(days=1)

        print(f"\nSelecting {args.samples} random samples from {start_date} to {end_date}...")
        samples = get_random_samples(client, start_date, end_date, args.samples)

        if not samples:
            print("Error: No samples found in date range")
            sys.exit(1)

        print(f"Found {len(samples)} samples")

    # Run spot checks
    print(f"\nRunning spot checks: {', '.join(checks_to_run)}")
    print("="*70)

    all_results = []

    for i, (player_lookup, universal_player_id, game_date) in enumerate(samples, 1):
        print(f"\n[{i}/{len(samples)}] Checking {player_lookup} on {game_date}...")

        result = run_spot_check(
            client,
            player_lookup,
            universal_player_id,
            game_date,
            checks_to_run,
            args.verbose
        )

        all_results.append(result)

        # Print quick summary
        emoji = {'PASS': '✅', 'FAIL': '❌', 'SKIP': '⏭️', 'ERROR': '⚠️'}[result['overall_status']]
        print(f"   {emoji} {result['overall_status']} - "
              f"Passed: {result['passed_count']}, Failed: {result['failed_count']}, "
              f"Skipped: {result['skipped_count']}")

    # Print comprehensive report
    exit_code = print_report(all_results, args.verbose)

    sys.exit(exit_code)


if __name__ == '__main__':
    main()
