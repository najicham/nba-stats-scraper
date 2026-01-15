-- BettingPros Historical MLB Props Tables
-- Created: 2026-01-15
--
-- Tables for storing historical prop data from BettingPros API.
-- Includes actual outcomes, projections, and performance trends.
--
-- Usage:
--   bq query --use_legacy_sql=false < schemas/bigquery/mlb_raw/bp_props_tables.sql

-- =============================================================================
-- Pitcher Props Table
-- =============================================================================
-- Markets: pitcher-strikeouts (285), pitcher-earned-runs-allowed (290)
-- ~28,880 records (740 days × 2 markets × ~20 props/day)

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.bp_pitcher_props` (
  -- Identifiers
  game_date DATE NOT NULL,
  market_id INT64 NOT NULL,
  market_name STRING,
  event_id INT64,

  -- Player info
  player_id STRING,
  player_name STRING,
  player_lookup STRING NOT NULL,  -- Normalized for joins
  team STRING,
  position STRING,

  -- Over line
  over_line FLOAT64,
  over_odds INT64,
  over_book_id INT64,
  over_consensus_line FLOAT64,

  -- Under line
  under_line FLOAT64,
  under_odds INT64,
  under_book_id INT64,
  under_consensus_line FLOAT64,

  -- BettingPros projections (KEY FEATURES!)
  projection_value FLOAT64,        -- Their model's prediction
  projection_side STRING,          -- 'over' or 'under'
  projection_ev FLOAT64,           -- Expected value
  projection_rating INT64,         -- 1-5 rating

  -- Actual outcome (KEY FOR TRAINING!)
  actual_value INT64,              -- What actually happened
  is_scored BOOL,                  -- Was outcome recorded
  is_push BOOL,                    -- Was it a push

  -- Performance trends (FEATURES!)
  perf_last_5_over INT64,          -- O/U record last 5 games
  perf_last_5_under INT64,
  perf_last_10_over INT64,         -- O/U record last 10 games
  perf_last_10_under INT64,
  perf_season_over INT64,          -- Season O/U record
  perf_season_under INT64,

  -- Context
  opposing_pitcher STRING,         -- Opponent's pitcher
  opposition_rank INT64,           -- Opponent K rate rank

  -- Metadata
  source_file_path STRING NOT NULL,
  scraped_at TIMESTAMP,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY player_lookup, market_id
OPTIONS (
  description = 'BettingPros historical pitcher props with outcomes (2022-2025)',
  require_partition_filter = true
);


-- =============================================================================
-- Batter Props Table
-- =============================================================================
-- Markets: 9 batter markets (hits, runs, rbis, doubles, triples, total-bases, stolen-bases, singles, home-runs)
-- ~1,111,000 records (740 days × 9 markets × ~170 props/day)

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.bp_batter_props` (
  -- Identifiers
  game_date DATE NOT NULL,
  market_id INT64 NOT NULL,
  market_name STRING,
  event_id INT64,

  -- Player info
  player_id STRING,
  player_name STRING,
  player_lookup STRING NOT NULL,
  team STRING,
  position STRING,

  -- Over line
  over_line FLOAT64,
  over_odds INT64,
  over_book_id INT64,
  over_consensus_line FLOAT64,

  -- Under line
  under_line FLOAT64,
  under_odds INT64,
  under_book_id INT64,
  under_consensus_line FLOAT64,

  -- BettingPros projections
  projection_value FLOAT64,
  projection_side STRING,
  projection_ev FLOAT64,
  projection_rating INT64,

  -- Actual outcome
  actual_value INT64,
  is_scored BOOL,
  is_push BOOL,

  -- Performance trends
  perf_last_5_over INT64,
  perf_last_5_under INT64,
  perf_last_10_over INT64,
  perf_last_10_under INT64,
  perf_season_over INT64,
  perf_season_under INT64,

  -- Context
  opposing_pitcher STRING,
  opposition_rank INT64,

  -- Metadata
  source_file_path STRING NOT NULL,
  scraped_at TIMESTAMP,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY player_lookup, market_id
OPTIONS (
  description = 'BettingPros historical batter props with outcomes (2022-2025)',
  require_partition_filter = true
);


-- =============================================================================
-- Useful Views
-- =============================================================================

-- Pitcher strikeouts only (for K model)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bp_pitcher_strikeouts` AS
SELECT *
FROM `nba-props-platform.mlb_raw.bp_pitcher_props`
WHERE market_id = 285
  AND is_scored = TRUE;


-- Scored props with grading
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.bp_pitcher_props_graded` AS
SELECT
  *,
  -- Calculate over/under result
  CASE
    WHEN actual_value > over_line THEN 'OVER'
    WHEN actual_value < over_line THEN 'UNDER'
    WHEN actual_value = over_line THEN 'PUSH'
    ELSE NULL
  END AS result,
  -- Calculate projection accuracy
  ABS(projection_value - actual_value) AS projection_error,
  -- Did projection predict correctly?
  CASE
    WHEN projection_side = 'over' AND actual_value > over_line THEN TRUE
    WHEN projection_side = 'under' AND actual_value < over_line THEN TRUE
    WHEN actual_value = over_line THEN NULL  -- Push
    ELSE FALSE
  END AS projection_correct
FROM `nba-props-platform.mlb_raw.bp_pitcher_props`
WHERE is_scored = TRUE;
