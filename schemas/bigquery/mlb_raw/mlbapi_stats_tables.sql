-- ============================================================================
-- MLB Stats API Player Stats Tables (Pitcher + Batter)
-- Game-level box score stats from the official MLB Stats API
-- File: schemas/bigquery/mlb_raw/mlbapi_stats_tables.sql
-- ============================================================================
--
-- Source: MLB Stats API - /api/v1/game/{game_pk}/boxscore
-- Scraper: scrapers/mlb/mlbstatsapi/mlb_box_scores.py
-- Processors:
--   - data_processors/raw/mlb/mlbapi_pitcher_stats_processor.py
--   - data_processors/raw/mlb/mlbapi_batter_stats_processor.py
--
-- CRITICAL for Predictions:
-- - Pitcher strikeouts are the primary prediction target
-- - Batter strikeouts feed the bottom-up K model
--   (Pitcher K's ~ Sum of individual batter K probabilities)
-- - If batter K lines don't sum to pitcher K line -> market inefficiency
--
-- Processing Strategy: MERGE_UPDATE (delete by game_pk + game_date, then insert)
-- ============================================================================


-- ============================================================================
-- TABLE 1: mlbapi_pitcher_stats
-- Per-pitcher game stats from MLB box scores
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.mlbapi_pitcher_stats` (
  -- ============================================================================
  -- CORE IDENTIFIERS
  -- ============================================================================
  game_pk INT64 NOT NULL,                     -- MLB authoritative game ID
  game_date DATE NOT NULL,                    -- Game date (partition key)
  season_year INT64 NOT NULL,                 -- Season year (derived from game_date)

  -- ============================================================================
  -- PLAYER IDENTIFICATION
  -- ============================================================================
  player_id INT64 NOT NULL,                   -- MLB player ID
  player_name STRING NOT NULL,                -- Full name (e.g., "Gerrit Cole")
  player_lookup STRING NOT NULL,              -- Normalized name for joins (e.g., "gerrit_cole")
  team_abbr STRING NOT NULL,                  -- Pitcher's team abbreviation (e.g., "NYY")
  opponent_abbr STRING NOT NULL,              -- Opposing team abbreviation (e.g., "BOS")
  home_away STRING NOT NULL,                  -- "home" or "away"
  is_starter BOOL NOT NULL,                   -- TRUE if starting pitcher

  -- ============================================================================
  -- PITCHING STATS - CORE (strikeouts = prediction target)
  -- ============================================================================
  strikeouts INT64 NOT NULL,                  -- PREDICTION TARGET: total Ks in game
  innings_pitched STRING,                     -- MLB notation: "6.1" = 6 1/3 IP, "6.2" = 6 2/3 IP
  pitches_thrown INT64,                       -- Total pitches
  strikes INT64,                              -- Total strikes
  balls INT64,                                -- Total balls

  -- ============================================================================
  -- PITCHING STATS - EXTENDED
  -- ============================================================================
  hits_allowed INT64,                         -- Hits given up
  walks INT64,                                -- Walks (BB)
  earned_runs INT64,                          -- Earned runs
  runs INT64,                                 -- Total runs (earned + unearned)
  home_runs_allowed INT64,                    -- Home runs given up
  batters_faced INT64,                        -- Total batters faced (TBF)

  -- ============================================================================
  -- GAME RESULT
  -- ============================================================================
  win BOOL,                                   -- Credited with the win
  loss BOOL,                                  -- Credited with the loss
  save BOOL,                                  -- Credited with the save

  -- ============================================================================
  -- COMPUTED FIELDS (calculated by processor)
  -- ============================================================================
  k_per_9 FLOAT64,                            -- (strikeouts / innings_pitched) * 9; NULL if 0 IP
  pitch_efficiency FLOAT64,                   -- strikeouts / pitches_thrown; NULL if 0 pitches

  -- ============================================================================
  -- PROCESSING METADATA
  -- ============================================================================
  source_file_path STRING NOT NULL,           -- GCS path of source JSON
  data_hash STRING,                           -- SHA-256 hash for deduplication
  created_at TIMESTAMP NOT NULL,              -- Record creation time (UTC)
  processed_at TIMESTAMP NOT NULL             -- Processing time (UTC)
)
PARTITION BY game_date
CLUSTER BY player_lookup, team_abbr
OPTIONS (
  description = "MLB pitcher game stats from official MLB Stats API box scores. Strikeouts are the primary prediction target. Processed by mlbapi_pitcher_stats_processor.",
  require_partition_filter = true
);


-- ============================================================================
-- TABLE 2: mlbapi_batter_stats
-- Per-batter game stats from MLB box scores
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.mlbapi_batter_stats` (
  -- ============================================================================
  -- CORE IDENTIFIERS
  -- ============================================================================
  game_pk INT64 NOT NULL,                     -- MLB authoritative game ID
  game_date DATE NOT NULL,                    -- Game date (partition key)
  season_year INT64 NOT NULL,                 -- Season year (derived from game_date)

  -- ============================================================================
  -- PLAYER IDENTIFICATION
  -- ============================================================================
  player_id INT64 NOT NULL,                   -- MLB player ID
  player_name STRING NOT NULL,                -- Full name (e.g., "Aaron Judge")
  player_lookup STRING NOT NULL,              -- Normalized name for joins (e.g., "aaron_judge")
  team_abbr STRING NOT NULL,                  -- Batter's team abbreviation (e.g., "NYY")
  opponent_abbr STRING NOT NULL,              -- Opposing team abbreviation (e.g., "BOS")
  home_away STRING NOT NULL,                  -- "home" or "away"
  batting_order INT64,                        -- Lineup position (1-9, 0 if unknown/pinch hitter)

  -- ============================================================================
  -- BATTING STATS - CORE (strikeouts = bottom-up model input)
  -- ============================================================================
  strikeouts INT64 NOT NULL,                  -- BOTTOM-UP MODEL: batter Ks in game
  at_bats INT64 NOT NULL,                     -- At bats (denominator for K rate)
  hits INT64,                                 -- Total hits
  walks INT64,                                -- Walks (BB)

  -- ============================================================================
  -- BATTING STATS - EXTENDED
  -- ============================================================================
  home_runs INT64,                            -- Home runs
  rbis INT64,                                 -- Runs batted in
  runs INT64,                                 -- Runs scored

  -- ============================================================================
  -- COMPUTED FIELDS (calculated by processor)
  -- ============================================================================
  k_rate FLOAT64,                             -- strikeouts / at_bats; NULL if 0 AB

  -- ============================================================================
  -- PROCESSING METADATA
  -- ============================================================================
  source_file_path STRING NOT NULL,           -- GCS path of source JSON
  data_hash STRING,                           -- SHA-256 hash for deduplication
  created_at TIMESTAMP NOT NULL,              -- Record creation time (UTC)
  processed_at TIMESTAMP NOT NULL             -- Processing time (UTC)
)
PARTITION BY game_date
CLUSTER BY player_lookup, team_abbr
OPTIONS (
  description = "MLB batter game stats from official MLB Stats API box scores. Batter strikeouts feed the bottom-up K prediction model. Processed by mlbapi_batter_stats_processor.",
  require_partition_filter = true
);
