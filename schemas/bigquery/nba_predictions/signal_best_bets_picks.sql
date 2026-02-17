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

  -- Combo registry fields (Session 259)
  matched_combo_id STRING,               -- Best matching combo from registry
  combo_classification STRING,           -- SYNERGISTIC | ANTI_PATTERN | NEUTRAL
  combo_hit_rate FLOAT64,                -- Historical hit rate of matched combo
  warning_tags ARRAY<STRING>,            -- ['redundancy_trap', 'contradictory_signals', ...]

  -- Cross-model consensus fields (Session 277)
  model_agreement_count INT64,           -- How many models agree on direction (0-6)
  feature_set_diversity INT64,           -- Feature set diversity (1=same, 2=V9+V12)
  consensus_bonus NUMERIC(5, 4),         -- Scoring adjustment from cross-model consensus
  quantile_consensus_under BOOLEAN,      -- All 4 quantile models agree UNDER
  agreeing_model_ids ARRAY<STRING>,      -- System IDs of models that agree on direction

  -- Pick angles (Session 278)
  pick_angles ARRAY<STRING>,             -- Human-readable pick reasoning

  -- Pick provenance (Session 279)
  qualifying_subsets STRING,              -- JSON array of {subset_id, system_id} dicts
  qualifying_subset_count INT64,          -- Number of Level 1/2 subsets this pick appears in
  algorithm_version STRING,               -- Scoring algorithm version (e.g. 'v279_qualifying_subsets')

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
