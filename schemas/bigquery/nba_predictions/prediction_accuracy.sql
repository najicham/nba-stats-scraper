-- ============================================================================
-- Prediction Accuracy Table Schema (v3)
-- ============================================================================
-- Dataset: nba_predictions
-- Table: prediction_accuracy
-- Purpose: Grade predictions against actual results for ML training
-- Updated: 2025-12-10 - v3: Added team context, minutes, confidence_decile
-- History:
--   v2: Added system_id, signed_error, margin fields, thresholds
--   v3: Added team_abbr, opponent_team_abbr, minutes_played, confidence_decile
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

  -- Metadata
  model_version STRING,
  graded_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY system_id, player_lookup;
