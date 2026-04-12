-- ============================================================================
-- MLB Signal Best Bets Picks Table Schema (v1)
-- ============================================================================
-- Dataset: mlb_predictions
-- Table: signal_best_bets_picks
-- Purpose: Curated daily best bets for pitcher strikeout props from
--          the Signal Discovery Framework. Includes signal annotations,
--          cross-model consensus, and pick angles.
--          Modeled after nba_predictions.signal_best_bets_picks.
-- Created: 2026-03-06
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_predictions.signal_best_bets_picks` (
  -- Primary Keys
  pitcher_lookup STRING NOT NULL,               -- Pitcher identifier (e.g., 'gerrit_cole')
  game_pk INT64 NOT NULL,                       -- MLB game primary key (integer from MLB Stats API)
  game_date DATE NOT NULL,                      -- Game date (partition key)
  system_id STRING NOT NULL,                    -- Primary model (e.g., 'xgboost_v2_mae')

  -- Pitcher/Team Context
  pitcher_name STRING,                          -- Display name (e.g., 'Gerrit Cole')
  team_abbr STRING,                             -- Pitcher's team (e.g., 'NYY')
  opponent_team_abbr STRING,                    -- Opponent team (e.g., 'BOS')

  -- Prediction Snapshot
  predicted_strikeouts NUMERIC(5, 1),           -- Model's predicted strikeouts
  line_value NUMERIC(4, 1),                     -- The betting line (e.g., 6.5)
  recommendation STRING,                        -- OVER/UNDER
  edge NUMERIC(5, 1),                           -- predicted_strikeouts - line_value
  confidence_score NUMERIC(4, 3),               -- Confidence 0-1

  -- Signal Framework Fields
  signal_tags ARRAY<STRING>,                    -- ['high_k_rate', 'bullpen_fatigue', ...]
  signal_count INT64,                           -- Number of qualifying signals
  real_signal_count INT64,                      -- Non-base signal count (excludes inflators)
  composite_score NUMERIC(6, 4),                -- Aggregator ranking score
  rank INT64,                                   -- 1-based daily rank (1 = best pick)

  -- Combo registry fields
  matched_combo_id STRING,                      -- Best matching combo from registry
  combo_classification STRING,                  -- SYNERGISTIC | ANTI_PATTERN | NEUTRAL
  combo_hit_rate FLOAT64,                       -- Historical hit rate of matched combo
  warning_tags ARRAY<STRING>,                   -- ['redundancy_trap', 'contradictory_signals', ...]

  -- Cross-model consensus fields
  model_agreement_count INT64,                  -- How many models agree on direction
  feature_set_diversity INT64,                  -- Feature set diversity (1=same, 2+=diverse)
  consensus_bonus NUMERIC(5, 4),                -- Scoring adjustment from cross-model consensus
  quantile_consensus_under BOOLEAN,             -- All quantile models agree UNDER
  agreeing_model_ids ARRAY<STRING>,             -- System IDs of models that agree on direction

  -- Pick angles
  pick_angles ARRAY<STRING>,                    -- Human-readable pick reasoning

  -- Pick provenance
  qualifying_subsets STRING,                    -- JSON array of {subset_id, system_id} dicts
  qualifying_subset_count INT64,                -- Number of qualifying subsets
  algorithm_version STRING,                     -- Scoring algorithm version (e.g. 'mlb_v1_signal')

  -- Multi-source attribution
  source_model_id STRING,                       -- Which model's prediction won dedup
  source_model_family STRING,                   -- Family classification (e.g. 'v2_mae')
  n_models_eligible INT64,                      -- How many models had sufficient edge
  champion_edge NUMERIC(5, 1),                  -- Champion model edge for comparison
  direction_conflict BOOLEAN,                   -- True if models with edge disagreed on direction

  -- Signal rescue (picks rescued from edge floor by high-HR signals)
  signal_rescued BOOLEAN,                       -- True if pick bypassed edge floor via signal
  rescue_signal STRING,                         -- Which signal rescued the pick

  -- Filter summary
  filter_summary STRING,                        -- JSON: {total_candidates, passed_filters, rejected: {...}}

  -- Under signal quality
  under_signal_quality FLOAT64,                 -- UNDER signal quality score (weighted, NULL for OVER)

  -- Ultra tier classification (high-confidence picks)
  ultra_tier BOOLEAN,                           -- True if pick qualifies as ultra-high-confidence
  ultra_criteria ARRAY<STRING>,                 -- Criteria met for ultra classification
  staking_multiplier INT64,                     -- Bet sizing multiplier (1=normal, 2=ultra)

  -- Bet sizing (planned, not yet implemented)
  bet_size_units FLOAT64,
  bet_size_tier STRING,

  -- Outcome (populated after grading)
  actual_strikeouts INT64,                      -- Actual strikeouts
  prediction_correct BOOLEAN,                   -- Was the pick correct?

  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY system_id, pitcher_lookup
OPTIONS (
  require_partition_filter=TRUE,
  description='Curated daily MLB best bets for pitcher strikeout props from Signal Discovery Framework. '
              'Top picks ranked by composite score across multiple signal sources and models. '
              'Includes signal annotations, cross-model consensus, and human-readable pick angles.'
);
