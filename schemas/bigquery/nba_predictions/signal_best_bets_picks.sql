-- ============================================================================
-- Signal Best Bets Picks Table Schema
-- ============================================================================
-- Dataset: nba_predictions
-- Table: signal_best_bets_picks
-- Purpose: Curated daily picks from Signal Discovery Framework
-- Created: 2026-02-14
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.signal_best_bets_picks` (
  -- Primary Keys
  player_lookup STRING NOT NULL,
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,
  system_id STRING NOT NULL,           -- Primary model (e.g., 'catboost_v9')

  -- Player/Team Context
  player_name STRING,
  team_abbr STRING,
  opponent_team_abbr STRING,

  -- Prediction Snapshot
  predicted_points NUMERIC(5, 1),
  line_value NUMERIC(5, 1),
  recommendation STRING,               -- OVER/UNDER
  edge NUMERIC(5, 1),                   -- predicted_points - line_value
  confidence_score NUMERIC(4, 3),

  -- Signal Framework Fields
  signal_tags ARRAY<STRING>,            -- ['high_edge', 'dual_agree', ...]
  signal_count INT64,                   -- Number of qualifying signals
  composite_score NUMERIC(6, 4),        -- Aggregator ranking score
  rank INT64,                           -- 1-based daily rank (1 = best pick)

  -- Outcome (populated after grading)
  actual_points INT64,
  prediction_correct BOOLEAN,

  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY system_id, player_lookup
OPTIONS (
  require_partition_filter=TRUE,
  description='Curated daily best bets from Signal Discovery Framework. '
              'Top 5 picks/day ranked by composite score across multiple signal sources.'
);
