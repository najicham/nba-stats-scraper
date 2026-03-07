-- ============================================================================
-- MLB Prediction Accuracy Table Schema (v1)
-- ============================================================================
-- Dataset: mlb_predictions
-- Table: prediction_accuracy
-- Purpose: Grade pitcher strikeout predictions against actual results for
--          ML training, model evaluation, and betting performance tracking.
--          Modeled after nba_predictions.prediction_accuracy.
-- Created: 2026-03-06
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_predictions.prediction_accuracy` (
  -- Primary Keys
  pitcher_lookup STRING NOT NULL,           -- Pitcher identifier (e.g., 'gerrit_cole')
  game_pk INT64 NOT NULL,                   -- MLB game primary key (integer from MLB Stats API)
  game_date DATE NOT NULL,                  -- Game date (partition key)
  system_id STRING NOT NULL,                -- Prediction system (e.g., 'xgboost_v2', 'catboost_v1')

  -- Team Context
  team_abbr STRING,                         -- Pitcher's team (e.g., 'NYY')
  opponent_team_abbr STRING,                -- Opponent team (e.g., 'BOS')

  -- Prediction Snapshot (what we predicted)
  predicted_strikeouts NUMERIC(5, 1),       -- Model's predicted strikeouts
  confidence_score NUMERIC(4, 3),           -- Confidence 0-1
  confidence_decile INTEGER,                -- 1-10 bucket for calibration curves
  recommendation STRING,                    -- OVER/UNDER/PASS
  line_value NUMERIC(4, 1),                 -- The betting line (e.g., 6.5)
  edge NUMERIC(5, 1),                       -- predicted_strikeouts - line_value

  -- Actual Result
  actual_strikeouts INTEGER,                -- Actual strikeouts recorded
  innings_pitched NUMERIC(4, 1),            -- Actual innings pitched (explains early pulls)

  -- Core Accuracy Metrics
  absolute_error NUMERIC(5, 1),             -- |predicted - actual|
  signed_error NUMERIC(5, 1),               -- predicted - actual (bias direction)
  prediction_correct BOOLEAN,               -- Was OVER/UNDER recommendation correct?

  -- Margin Analysis (for betting evaluation)
  predicted_margin NUMERIC(5, 1),           -- predicted - line
  actual_margin NUMERIC(5, 1),              -- actual - line

  -- Threshold Accuracy (was prediction within N strikeouts?)
  within_1_strikeout BOOLEAN,               -- |predicted - actual| <= 1
  within_2_strikeouts BOOLEAN,              -- |predicted - actual| <= 2

  -- Line Source Tracking
  has_prop_line BOOLEAN,                    -- TRUE if pitcher had a real betting line
  line_source STRING,                       -- 'ACTUAL_PROP', 'NO_PROP_LINE', 'ESTIMATED_AVG'
  estimated_line_value NUMERIC(4, 1),       -- Estimated line if no prop line available
  is_actionable BOOLEAN,                    -- TRUE if pick passed confidence/edge filters
  filter_reason STRING,                     -- Reason if filtered (low_confidence, etc.)

  -- Bookmaker Tracking
  line_bookmaker STRING,                    -- Sportsbook: DRAFTKINGS, FANDUEL, etc.
  line_source_api STRING,                   -- API source: ODDS_API, BETTINGPROS

  -- Voiding (DNP equivalent: pitcher scratched, rain delay, etc.)
  is_voided BOOLEAN,                        -- TRUE = exclude from accuracy metrics
  void_reason STRING,                       -- 'scratched', 'rain_delay', 'injury', 'short_start'

  -- Data Quality Tracking
  feature_quality_score FLOAT64,            -- Feature quality score from prediction (0-100)
  data_quality_tier STRING,                 -- HIGH/MEDIUM/LOW computed from quality score

  -- Metadata
  model_version STRING,
  graded_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY system_id, pitcher_lookup
OPTIONS (
  require_partition_filter=TRUE,
  description='MLB pitcher strikeout prediction accuracy. Grades predictions against actual results. '
              'Use has_prop_line = TRUE AND recommendation IN (OVER, UNDER) AND prediction_correct IS NOT NULL '
              'for actionable accuracy queries. Edge = predicted_strikeouts - line_value.'
);
