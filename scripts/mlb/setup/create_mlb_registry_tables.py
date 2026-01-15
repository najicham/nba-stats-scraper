#!/usr/bin/env python3
"""
Create MLB Registry Tables in BigQuery

Creates the following tables:
1. mlb_reference.mlb_players_registry - Main player registry
2. mlb_reference.mlb_player_aliases - Name aliases for resolution

Usage:
    python scripts/mlb/setup/create_mlb_registry_tables.py

    # Dry run (show SQL only)
    python scripts/mlb/setup/create_mlb_registry_tables.py --dry-run

Created: 2026-01-13
"""

import argparse
import logging
import sys

from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
DATASET_ID = 'mlb_reference'


REGISTRY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.mlb_players_registry` (
    -- PLAYER IDENTIFICATION
    player_lookup STRING NOT NULL,             -- Normalized lookup key (lowercase, no spaces)
    universal_player_id STRING,                -- Universal ID (e.g., loganwebb_001)
    bdl_player_id INT64,                       -- Ball Don't Lie player ID
    statcast_player_id INT64,                  -- Baseball Savant player ID
    player_full_name STRING NOT NULL,          -- Display name
    first_name STRING,                         -- First name
    last_name STRING,                          -- Last name
    team_abbr STRING NOT NULL,                 -- Current team abbreviation
    season_year INT64 NOT NULL,                -- Season year (2024, 2025, etc.)

    -- PLAYER TYPE (Critical for model)
    player_type STRING NOT NULL,               -- 'PITCHER' or 'BATTER'
    position STRING,                           -- Detailed position (SP, RP, C, 1B, etc.)
    is_starter BOOL,                           -- For pitchers: starting pitcher
    throws STRING,                             -- 'L' or 'R' (for pitchers)
    bats STRING,                               -- 'L', 'R', or 'S' (for batters)

    -- GAME PARTICIPATION
    first_game_date DATE,                      -- First game this season
    last_game_date DATE,                       -- Most recent game
    games_played INT64,                        -- Total games this season

    -- SEASON STATS SUMMARY (for quick lookups)
    -- Pitcher stats
    season_strikeouts INT64,                   -- Season K total (pitchers)
    season_innings NUMERIC(6,1),               -- Season IP (pitchers)
    season_k_per_9 NUMERIC(4,2),               -- K/9 rate (pitchers)

    -- Batter stats
    season_at_bats INT64,                      -- Season AB (batters)
    season_batter_ks INT64,                    -- Season strikeouts (batters)
    season_k_rate NUMERIC(4,3),                -- K rate (batters)

    -- DATA SOURCE TRACKING
    source_priority STRING,                    -- 'bdl_stats', 'odds_api', 'active_players'
    confidence_score NUMERIC(3,2),             -- Data quality confidence (0.0-1.0)

    -- PROCESSING METADATA
    last_updated_by STRING,                    -- Which processor last updated
    update_count INT64 DEFAULT 0,              -- Number of times updated
    created_at TIMESTAMP NOT NULL,
    processed_at TIMESTAMP NOT NULL
)
CLUSTER BY player_lookup, team_abbr, season_year, player_type
OPTIONS (
  description = "MLB players registry for authoritative player validation. Key for joining pitcher and batter data across sources."
)
""".format(project=PROJECT_ID, dataset=DATASET_ID)


ALIAS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.mlb_player_aliases` (
    -- Alias mapping
    alias_lookup STRING NOT NULL,              -- The alias (normalized)
    canonical_lookup STRING NOT NULL,          -- The canonical player_lookup
    universal_player_id STRING,                -- Resolved universal ID

    -- Metadata
    alias_type STRING,                         -- 'spelling', 'nickname', 'source_variation'
    source STRING,                             -- Where this alias was found
    is_active BOOL DEFAULT TRUE,               -- Is this alias active
    confidence NUMERIC(3,2) DEFAULT 1.0,       -- Confidence in mapping

    -- Tracking
    created_at TIMESTAMP NOT NULL,
    processed_at TIMESTAMP NOT NULL
)
CLUSTER BY alias_lookup, canonical_lookup
OPTIONS (
  description = "MLB player name aliases for resolving variations across data sources."
)
""".format(project=PROJECT_ID, dataset=DATASET_ID)


UNRESOLVED_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.mlb_unresolved_players` (
    -- Player info
    player_lookup STRING NOT NULL,             -- Normalized lookup that failed
    player_name STRING,                        -- Original name if available
    player_type STRING,                        -- 'PITCHER', 'BATTER', or 'UNKNOWN'

    -- Context
    source STRING NOT NULL,                    -- Which processor encountered this
    game_date DATE,                            -- Game date if available
    team_abbr STRING,                          -- Team if available

    -- Tracking
    occurrence_count INT64 DEFAULT 1,          -- How many times seen
    first_seen TIMESTAMP NOT NULL,
    last_seen TIMESTAMP NOT NULL,

    -- Resolution
    is_resolved BOOL DEFAULT FALSE,            -- Has this been resolved
    resolved_to STRING,                        -- What it was resolved to
    resolved_at TIMESTAMP,
    resolved_by STRING
)
PARTITION BY DATE(first_seen)
CLUSTER BY player_lookup, source, is_resolved
OPTIONS (
  description = "Tracks MLB player lookups that couldn't be resolved, for manual review."
)
""".format(project=PROJECT_ID, dataset=DATASET_ID)


def create_dataset_if_not_exists(client: bigquery.Client) -> None:
    """Create the mlb_reference dataset if it doesn't exist."""
    dataset_ref = f"{PROJECT_ID}.{DATASET_ID}"

    try:
        client.get_dataset(dataset_ref)
        logger.info(f"Dataset {DATASET_ID} already exists")
    except Exception:
        logger.info(f"Creating dataset {DATASET_ID}")
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = "US"
        dataset.description = "MLB reference data for player identification and validation"
        client.create_dataset(dataset)
        logger.info(f"Created dataset {DATASET_ID}")


def create_tables(client: bigquery.Client, dry_run: bool = False) -> None:
    """Create all registry tables."""
    tables = [
        ("mlb_players_registry", REGISTRY_TABLE_SQL),
        ("mlb_player_aliases", ALIAS_TABLE_SQL),
        ("mlb_unresolved_players", UNRESOLVED_TABLE_SQL),
    ]

    for table_name, sql in tables:
        logger.info(f"\n{'='*60}")
        logger.info(f"Creating table: {table_name}")
        logger.info('='*60)

        if dry_run:
            logger.info(f"DRY RUN - Would execute:\n{sql}")
            continue

        try:
            job = client.query(sql)
            job.result()
            logger.info(f"Successfully created/verified table: {table_name}")
        except Exception as e:
            logger.error(f"Failed to create table {table_name}: {e}")
            raise


def create_views(client: bigquery.Client, dry_run: bool = False) -> None:
    """Create useful views."""
    views = [
        # Active pitchers view
        (
            "mlb_active_pitchers",
            f"""
            CREATE OR REPLACE VIEW `{PROJECT_ID}.{DATASET_ID}.mlb_active_pitchers` AS
            SELECT *
            FROM `{PROJECT_ID}.{DATASET_ID}.mlb_players_registry`
            WHERE player_type = 'PITCHER'
              AND season_year = EXTRACT(YEAR FROM CURRENT_DATE())
              AND last_game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
            """
        ),
        # Active batters view
        (
            "mlb_active_batters",
            f"""
            CREATE OR REPLACE VIEW `{PROJECT_ID}.{DATASET_ID}.mlb_active_batters` AS
            SELECT *
            FROM `{PROJECT_ID}.{DATASET_ID}.mlb_players_registry`
            WHERE player_type = 'BATTER'
              AND season_year = EXTRACT(YEAR FROM CURRENT_DATE())
              AND last_game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
            """
        ),
        # High-K pitchers view
        (
            "mlb_high_k_pitchers",
            f"""
            CREATE OR REPLACE VIEW `{PROJECT_ID}.{DATASET_ID}.mlb_high_k_pitchers` AS
            SELECT
              player_lookup,
              player_full_name,
              team_abbr,
              season_strikeouts,
              season_innings,
              season_k_per_9,
              games_played
            FROM `{PROJECT_ID}.{DATASET_ID}.mlb_players_registry`
            WHERE player_type = 'PITCHER'
              AND season_year = EXTRACT(YEAR FROM CURRENT_DATE())
              AND season_innings >= 50.0
              AND season_k_per_9 >= 8.0
            ORDER BY season_k_per_9 DESC
            """
        ),
    ]

    for view_name, sql in views:
        logger.info(f"\nCreating view: {view_name}")

        if dry_run:
            logger.info(f"DRY RUN - Would execute:\n{sql}")
            continue

        try:
            job = client.query(sql)
            job.result()
            logger.info(f"Successfully created view: {view_name}")
        except Exception as e:
            logger.error(f"Failed to create view {view_name}: {e}")


def main():
    parser = argparse.ArgumentParser(
        description='Create MLB registry tables in BigQuery'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show SQL without executing'
    )

    args = parser.parse_args()

    logger.info("MLB Registry Tables Setup")
    logger.info("=" * 60)

    try:
        client = bigquery.Client(project=PROJECT_ID)

        # Create dataset
        create_dataset_if_not_exists(client)

        # Create tables
        create_tables(client, dry_run=args.dry_run)

        # Create views
        create_views(client, dry_run=args.dry_run)

        logger.info("\n" + "=" * 60)
        logger.info("SETUP COMPLETE")
        logger.info("=" * 60)

        if not args.dry_run:
            logger.info(f"\nCreated tables in {PROJECT_ID}.{DATASET_ID}:")
            logger.info("  - mlb_players_registry")
            logger.info("  - mlb_player_aliases")
            logger.info("  - mlb_unresolved_players")
            logger.info("\nCreated views:")
            logger.info("  - mlb_active_pitchers")
            logger.info("  - mlb_active_batters")
            logger.info("  - mlb_high_k_pitchers")

    except Exception as e:
        logger.exception(f"Setup failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
