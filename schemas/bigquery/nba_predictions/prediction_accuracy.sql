-- ============================================================================
-- Prediction Accuracy Table Schema (v5)
-- ============================================================================
-- Dataset: nba_predictions
-- Table: prediction_accuracy
-- Purpose: Grade predictions against actual results for ML training
-- Updated: 2026-06-05 - v6: Regenerated from live BQ; added 13 columns
-- History:
--   v2: Added system_id, signed_error, margin fields, thresholds
--   v3: Added team_abbr, opponent_team_abbr, minutes_played, confidence_decile
--   v4: Added is_voided, void_reason, pre_game_injury_flag, injury tracking
--   v5: Added line_bookmaker, line_source_api for per-bookmaker hit rate analysis
--   v6: Synced with live BQ — added feature_version, feature_count,
--       feature_data_source, early_season_flag, raw_confidence_score,
--       calibration_method, shot_zones_source, feature_completeness_pct,
--       bdb_available_at_prediction, is_superseded_prediction,
--       original_prediction_id, build_commit_sha, critical_features
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.prediction_accuracy` (
  -- Primary Keys
  player_lookup STRING NOT NULL,
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,
  system_id STRING NOT NULL,  -- Grade each prediction system separately

  -- Team Context (for opponent analysis, home/away analysis)
  team_abbr STRING,              -- Player's team (e.g., 'LAL')
  opponent_team_abbr STRING,     -- Opponent team (e.g., 'BOS')

  -- Prediction Snapshot (what we predicted)
  predicted_points NUMERIC(5, 1),
  confidence_score NUMERIC(4, 3),
  confidence_decile INTEGER,      -- 1-10 bucket for calibration curves
  recommendation STRING,  -- OVER/UNDER/PASS
  line_value NUMERIC(5, 1),  -- The betting line

  -- Feature Inputs (for ML analysis of what helped)
  referee_adjustment NUMERIC(5, 1),
  pace_adjustment NUMERIC(5, 1),
  similarity_sample_size INTEGER,

  -- Actual Result
  actual_points INTEGER,
  minutes_played NUMERIC(5, 1),   -- Actual minutes (explains low scoring games)

  -- Core Accuracy Metrics
  absolute_error NUMERIC(5, 1),  -- |predicted - actual|
  signed_error NUMERIC(5, 1),    -- predicted - actual (bias direction)
  prediction_correct BOOLEAN,     -- Was OVER/UNDER recommendation correct?

  -- Margin Analysis (for betting evaluation)
  predicted_margin NUMERIC(5, 1),  -- predicted - line
  actual_margin NUMERIC(5, 1),     -- actual - line

  -- Threshold Accuracy (was prediction within N points?)
  within_3_points BOOLEAN,
  within_5_points BOOLEAN,

  -- Line Source Tracking (added v3.x)
  has_prop_line BOOLEAN,                  -- TRUE if player had a real betting line
  line_source STRING,                     -- 'ACTUAL_PROP', 'NO_PROP_LINE', 'ESTIMATED_AVG'
  estimated_line_value NUMERIC(5, 1),     -- Estimated line if no prop line available
  is_actionable BOOLEAN,                  -- TRUE if pick passed confidence tier filter
  filter_reason STRING,                   -- Reason if filtered (low_confidence, etc.)

  -- Bookmaker Tracking (v5) - For per-bookmaker hit rate analysis
  line_bookmaker STRING,                  -- Sportsbook: DRAFTKINGS, FANDUEL, etc.
  line_source_api STRING,                 -- API source: ODDS_API, BETTINGPROS

  -- DNP/Injury Voiding (v4) - Treat DNP like voided bets
  is_voided BOOLEAN,                    -- TRUE = exclude from accuracy metrics (like sportsbook void)
  void_reason STRING,                   -- 'dnp_injury_confirmed', 'dnp_late_scratch', 'dnp_unknown'
  pre_game_injury_flag BOOLEAN,         -- TRUE if player was flagged with injury concern pre-game
  pre_game_injury_status STRING,        -- Injury status at prediction time: 'OUT', 'DOUBTFUL', 'QUESTIONABLE', 'PROBABLE'
  injury_confirmed_postgame BOOLEAN,    -- TRUE if DNP matched a pre-game injury flag

  -- Data Quality Tracking (Session 125/319 - enables hit rate by quality analysis)
  feature_quality_score FLOAT64,          -- Feature quality score from prediction (0-100)
  data_quality_tier STRING,               -- HIGH/MEDIUM/LOW computed from quality score

  -- Feature Provenance (v6 — added 2026-06-05 from live BQ regen)
  feature_version STRING,
  feature_count INT64,
  feature_data_source STRING,
  feature_completeness_pct FLOAT64,
  critical_features JSON,
  shot_zones_source STRING,
  bdb_available_at_prediction BOOL,

  -- Calibration + Raw Scoring (v6)
  raw_confidence_score NUMERIC,
  calibration_method STRING,
  early_season_flag BOOL,

  -- Re-prediction Provenance (v6)
  is_superseded_prediction BOOL,
  original_prediction_id STRING,
  build_commit_sha STRING,

  -- Metadata
  model_version STRING,
  graded_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY system_id, player_lookup
OPTIONS (
  require_partition_filter=TRUE
);
