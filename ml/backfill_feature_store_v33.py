#!/usr/bin/env python3
"""
Backfill ML Feature Store with 33 features (add 8 missing features).

Adds these features to ml_feature_store_v2:
1. vegas_points_line - Vegas consensus points line
2. vegas_opening_line - Vegas opening line
3. vegas_line_move - Line movement (current - opening)
4. has_vegas_line - Boolean (1.0 or 0.0)
5. avg_points_vs_opponent - Player's avg points vs this opponent
6. games_vs_opponent - Number of games vs this opponent
7. minutes_avg_last_10 - Average minutes last 10 games
8. ppm_avg_last_10 - Points per minute last 10 games

Usage:
    PYTHONPATH=. python ml/backfill_feature_store_v33.py

    # Dry run
    PYTHONPATH=. python ml/backfill_feature_store_v33.py --dry-run
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('backfill_features_v33.log')
    ]
)
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent.parent))

from google.cloud import bigquery

PROJECT_ID = 'nba-props-platform'


def create_extra_features_table(client: bigquery.Client):
    """
    Create a temporary table with the 8 extra features for all player/dates.
    """
    logger.info("Creating extra features table...")

    query = """
    CREATE OR REPLACE TABLE `nba_predictions.ml_feature_store_v33_extra` AS

    WITH
    -- Get Vegas lines (consensus = average across books)
    vegas_lines AS (
        SELECT
            player_lookup,
            game_date,
            AVG(points_line) as vegas_points_line,
            AVG(opening_line) as vegas_opening_line,
            1.0 as has_vegas_line
        FROM `nba_raw.bettingpros_player_points_props`
        WHERE bet_side = 'over'
          AND points_line IS NOT NULL
          AND game_date BETWEEN '2021-01-01' AND '2026-12-31'
        GROUP BY player_lookup, game_date
    ),

    -- Get opponent history (avg points vs each opponent before each game)
    opponent_history AS (
        SELECT
            f.player_lookup,
            f.game_date,
            f.opponent_team_abbr,
            -- Count games vs this opponent BEFORE this game
            COUNT(g.game_date) as games_vs_opponent,
            -- Average points vs this opponent BEFORE this game
            AVG(g.points) as avg_points_vs_opponent
        FROM `nba_predictions.ml_feature_store_v2` f
        LEFT JOIN `nba_analytics.player_game_summary` g
            ON f.player_lookup = g.player_lookup
            AND g.opponent_team_abbr = f.opponent_team_abbr
            AND g.game_date < f.game_date  -- Only games BEFORE current
            AND g.game_date >= DATE_SUB(f.game_date, INTERVAL 3 YEAR)  -- Last 3 years
        GROUP BY f.player_lookup, f.game_date, f.opponent_team_abbr
    ),

    -- Get minutes and PPM history (last 10 games before each game)
    minutes_history AS (
        SELECT
            f.player_lookup,
            f.game_date,
            AVG(g.minutes_played) as minutes_avg_last_10,
            AVG(SAFE_DIVIDE(g.points, NULLIF(g.minutes_played, 0))) as ppm_avg_last_10
        FROM `nba_predictions.ml_feature_store_v2` f
        LEFT JOIN (
            SELECT
                player_lookup,
                game_date,
                minutes_played,
                points,
                ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn
            FROM `nba_analytics.player_game_summary`
            WHERE minutes_played > 0
        ) g
            ON f.player_lookup = g.player_lookup
            AND g.game_date < f.game_date  -- Only games BEFORE current
            AND g.rn <= 10  -- Last 10 games
        GROUP BY f.player_lookup, f.game_date
    )

    -- Combine all features
    SELECT
        f.player_lookup,
        f.game_date,

        -- Vegas features (with fallbacks)
        COALESCE(v.vegas_points_line,
            -- Fallback: use points_avg_season from existing features (index 2)
            f.features[OFFSET(2)]) as vegas_points_line,
        COALESCE(v.vegas_opening_line,
            f.features[OFFSET(2)]) as vegas_opening_line,
        COALESCE(v.vegas_points_line - v.vegas_opening_line, 0.0) as vegas_line_move,
        COALESCE(v.has_vegas_line, 0.0) as has_vegas_line,

        -- Opponent history (with fallbacks)
        COALESCE(o.avg_points_vs_opponent,
            f.features[OFFSET(2)]) as avg_points_vs_opponent,
        COALESCE(CAST(o.games_vs_opponent AS FLOAT64), 0.0) as games_vs_opponent,

        -- Minutes/PPM history (with fallbacks)
        COALESCE(m.minutes_avg_last_10, 28.0) as minutes_avg_last_10,
        COALESCE(m.ppm_avg_last_10, 0.4) as ppm_avg_last_10

    FROM `nba_predictions.ml_feature_store_v2` f
    LEFT JOIN vegas_lines v
        ON f.player_lookup = v.player_lookup AND f.game_date = v.game_date
    LEFT JOIN opponent_history o
        ON f.player_lookup = o.player_lookup AND f.game_date = o.game_date
    LEFT JOIN minutes_history m
        ON f.player_lookup = m.player_lookup AND f.game_date = m.game_date
    """

    job = client.query(query)
    job.result()  # Wait for completion

    logger.info("Extra features table created")

    # Check row count
    count_query = "SELECT COUNT(*) as cnt FROM `nba_predictions.ml_feature_store_v33_extra`"
    result = list(client.query(count_query).result())[0]
    logger.info(f"Extra features table has {result.cnt:,} rows")

    return result.cnt


def update_feature_store(client: bigquery.Client, dry_run: bool = False):
    """
    Update ml_feature_store_v2 by appending the 8 extra features.
    """
    logger.info("Updating feature store with extra features...")

    if dry_run:
        logger.info("DRY RUN - would update feature store")
        return

    # BigQuery doesn't allow direct UPDATE of ARRAY columns easily,
    # so we'll create a new table and swap

    query = """
    CREATE OR REPLACE TABLE `nba_predictions.ml_feature_store_v2_backup` AS
    SELECT * FROM `nba_predictions.ml_feature_store_v2`;
    """
    client.query(query).result()
    logger.info("Created backup table")

    # Create new feature store with 33 features
    query = """
    CREATE OR REPLACE TABLE `nba_predictions.ml_feature_store_v2_new` AS
    SELECT
        f.player_lookup,
        f.universal_player_id,
        f.game_date,
        f.game_id,
        -- Append 8 new features to existing 25
        ARRAY_CONCAT(
            f.features,
            [
                e.vegas_points_line,
                e.vegas_opening_line,
                e.vegas_line_move,
                e.has_vegas_line,
                e.avg_points_vs_opponent,
                e.games_vs_opponent,
                e.minutes_avg_last_10,
                e.ppm_avg_last_10
            ]
        ) as features,
        -- Append new feature names
        ARRAY_CONCAT(
            f.feature_names,
            [
                'vegas_points_line',
                'vegas_opening_line',
                'vegas_line_move',
                'has_vegas_line',
                'avg_points_vs_opponent',
                'games_vs_opponent',
                'minutes_avg_last_10',
                'ppm_avg_last_10'
            ]
        ) as feature_names,
        33 as feature_count,  -- Updated from 25
        'v2_33features' as feature_version,  -- Updated version
        f.feature_generation_time_ms,
        f.feature_quality_score,
        f.opponent_team_abbr,
        f.is_home,
        f.days_rest,
        f.data_source,
        f.source_daily_cache_last_updated,
        f.source_daily_cache_rows_found,
        f.source_daily_cache_completeness_pct,
        f.source_daily_cache_hash,
        f.source_composite_last_updated,
        f.source_composite_rows_found,
        f.source_composite_completeness_pct,
        f.source_composite_hash,
        f.source_shot_zones_last_updated,
        f.source_shot_zones_rows_found,
        f.source_shot_zones_completeness_pct,
        f.source_shot_zones_hash,
        f.source_team_defense_last_updated,
        f.source_team_defense_rows_found,
        f.source_team_defense_completeness_pct,
        f.source_team_defense_hash,
        f.early_season_flag,
        f.insufficient_data_reason,
        f.data_hash,
        CURRENT_TIMESTAMP() as created_at,
        CURRENT_TIMESTAMP() as updated_at,
        f.expected_games_count,
        f.actual_games_count,
        f.completeness_percentage,
        f.missing_games_count,
        f.is_production_ready,
        f.data_quality_issues,
        f.last_reprocess_attempt_at,
        f.reprocess_attempt_count,
        f.circuit_breaker_active,
        f.circuit_breaker_until,
        f.manual_override_required,
        f.season_boundary_detected,
        f.backfill_bootstrap_mode,
        f.processing_decision_reason,
        f.quality_tier
    FROM `nba_predictions.ml_feature_store_v2` f
    JOIN `nba_predictions.ml_feature_store_v33_extra` e
        ON f.player_lookup = e.player_lookup AND f.game_date = e.game_date
    """

    job = client.query(query)
    job.result()
    logger.info("Created new feature store with 33 features")

    # Verify counts match
    old_count = list(client.query("SELECT COUNT(*) as cnt FROM `nba_predictions.ml_feature_store_v2`").result())[0].cnt
    new_count = list(client.query("SELECT COUNT(*) as cnt FROM `nba_predictions.ml_feature_store_v2_new`").result())[0].cnt

    logger.info(f"Old table: {old_count:,} rows, New table: {new_count:,} rows")

    if old_count != new_count:
        logger.error(f"Row count mismatch! Aborting swap.")
        return False

    # Swap tables
    logger.info("Swapping tables...")
    client.query("DROP TABLE `nba_predictions.ml_feature_store_v2`").result()
    client.query("ALTER TABLE `nba_predictions.ml_feature_store_v2_new` RENAME TO ml_feature_store_v2").result()

    logger.info("Feature store updated successfully!")
    return True


def verify_features(client: bigquery.Client):
    """Verify the updated feature store."""
    query = """
    SELECT
        feature_count,
        feature_version,
        feature_names,
        ARRAY_LENGTH(features) as actual_feature_count
    FROM `nba_predictions.ml_feature_store_v2`
    WHERE game_date = '2025-12-01'
    LIMIT 1
    """
    result = list(client.query(query).result())[0]

    logger.info(f"Feature count: {result.feature_count}")
    logger.info(f"Feature version: {result.feature_version}")
    logger.info(f"Actual features: {result.actual_feature_count}")
    logger.info(f"Feature names: {result.feature_names}")

    return result.feature_count == 33


def main():
    parser = argparse.ArgumentParser(description='Backfill feature store with 33 features')
    parser.add_argument('--dry-run', action='store_true', help='Dry run (no writes)')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Feature Store V33 Backfill Starting")
    logger.info("=" * 60)

    client = bigquery.Client(project=PROJECT_ID)

    start_time = time.time()

    # Step 1: Create extra features table
    row_count = create_extra_features_table(client)

    # Step 2: Update feature store
    success = update_feature_store(client, args.dry_run)

    if not args.dry_run and success:
        # Step 3: Verify
        verify_features(client)

        # Cleanup temp table
        client.query("DROP TABLE IF EXISTS `nba_predictions.ml_feature_store_v33_extra`").result()
        logger.info("Cleaned up temp table")

    duration = time.time() - start_time
    logger.info("=" * 60)
    logger.info(f"COMPLETE in {duration/60:.1f} minutes")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
