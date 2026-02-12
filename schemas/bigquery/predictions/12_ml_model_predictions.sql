-- @quality-filter: exempt
-- Reason: Historical raw predictions table, preserves all data for analysis

-- ============================================================================
-- Table: ml_model_predictions
-- File: 12_ml_model_predictions.sql
-- Purpose: Predictions from ML experimentation pipeline (separate from production)
-- ============================================================================
--
-- This table stores predictions from all ML models being experimented with.
-- It's separate from player_prop_predictions to:
-- 1. Keep experiments isolated from production
-- 2. Enable clean model-to-model comparison
-- 3. Allow running many experimental models without cluttering production
--
-- After games complete, actual results are joined to calculate accuracy metrics.
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.ml_model_predictions` (
  -- Identity
  prediction_id STRING NOT NULL,               -- UUID for this prediction
  model_id STRING NOT NULL,                    -- FK to ml_model_registry.model_id

  -- Game Context
  player_lookup STRING NOT NULL,
  game_date DATE NOT NULL,                     -- Partition key
  game_id STRING NOT NULL,
  team_abbr STRING,
  opponent_team_abbr STRING,

  -- Prediction
  predicted_points FLOAT64 NOT NULL,
  confidence_score FLOAT64,                    -- 0-100 scale
  recommendation STRING,                       -- 'OVER', 'UNDER', 'PASS', 'NO_LINE'

  -- Betting Context
  betting_line FLOAT64,                        -- Vegas prop line (NULL if no line)
  edge_vs_line FLOAT64,                        -- predicted_points - betting_line
  vegas_opening_line FLOAT64,                  -- Opening line (for line movement analysis)

  -- Injury Context
  injury_status STRING,                        -- Player's injury status at prediction time
  injury_warning BOOL,                         -- TRUE if QUESTIONABLE/DOUBTFUL

  -- Feature Metadata (for debugging/reproducibility)
  feature_version STRING,                      -- Which feature set was used
  feature_count INT64,                         -- Number of features used
  features_hash STRING,                        -- Hash of feature vector (for reproducibility)

  -- Results (filled after game completes)
  actual_points FLOAT64,                       -- Actual points scored
  actual_minutes FLOAT64,                      -- Actual minutes played (for DNP detection)
  prediction_error FLOAT64,                    -- |predicted - actual|
  bet_outcome STRING,                          -- 'WIN', 'LOSS', 'PUSH', NULL

  -- Comparison Flags
  beat_baseline BOOL,                          -- TRUE if this model beat the baseline model
  beat_vegas BOOL,                             -- TRUE if prediction was closer than Vegas line

  -- Timestamps
  prediction_time TIMESTAMP NOT NULL,          -- When prediction was made
  result_updated_at TIMESTAMP,                 -- When actual results were filled
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL
)
PARTITION BY game_date
CLUSTER BY model_id, player_lookup
OPTIONS(
  description="ML model experiment predictions. Separate from production predictions for clean A/B comparison.",
  partition_expiration_days=365,
  require_partition_filter=TRUE
);

-- ============================================================================
-- Comparison View: Daily Model Performance
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_ml_model_daily_performance` AS
SELECT
  game_date,
  model_id,
  COUNT(*) as total_predictions,
  COUNTIF(actual_points IS NOT NULL) as graded_predictions,

  -- Accuracy Metrics
  AVG(prediction_error) as mae,
  APPROX_QUANTILES(prediction_error, 100)[OFFSET(50)] as median_error,
  APPROX_QUANTILES(prediction_error, 100)[OFFSET(90)] as p90_error,

  -- Distribution
  COUNTIF(prediction_error <= 3) as within_3pts,
  COUNTIF(prediction_error <= 5) as within_5pts,
  SAFE_DIVIDE(COUNTIF(prediction_error <= 3), COUNTIF(actual_points IS NOT NULL)) as within_3pts_pct,
  SAFE_DIVIDE(COUNTIF(prediction_error <= 5), COUNTIF(actual_points IS NOT NULL)) as within_5pts_pct,

  -- Betting Performance
  COUNTIF(betting_line IS NOT NULL) as predictions_with_line,
  COUNTIF(bet_outcome = 'WIN') as bet_wins,
  COUNTIF(bet_outcome = 'LOSS') as bet_losses,
  SAFE_DIVIDE(COUNTIF(bet_outcome = 'WIN'), COUNTIF(bet_outcome IN ('WIN', 'LOSS'))) as bet_accuracy,

  -- Baseline Comparison
  COUNTIF(beat_baseline = TRUE) as beat_baseline_count,
  SAFE_DIVIDE(COUNTIF(beat_baseline = TRUE), COUNTIF(beat_baseline IS NOT NULL)) as beat_baseline_pct,

  -- Vegas Comparison
  COUNTIF(beat_vegas = TRUE) as beat_vegas_count,
  SAFE_DIVIDE(COUNTIF(beat_vegas = TRUE), COUNTIF(beat_vegas IS NOT NULL)) as beat_vegas_pct

FROM `nba-props-platform.nba_predictions.ml_model_predictions`
WHERE actual_points IS NOT NULL
GROUP BY game_date, model_id;

-- ============================================================================
-- Comparison View: Model Leaderboard (All Time)
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_ml_model_leaderboard` AS
SELECT
  model_id,
  COUNT(DISTINCT game_date) as days_active,
  COUNT(*) as total_predictions,
  COUNTIF(actual_points IS NOT NULL) as graded_predictions,

  -- Overall Accuracy
  AVG(prediction_error) as mae,
  APPROX_QUANTILES(prediction_error, 100)[OFFSET(50)] as median_error,
  STDDEV(prediction_error) as error_stddev,

  -- Consistency
  SAFE_DIVIDE(COUNTIF(prediction_error <= 3), COUNTIF(actual_points IS NOT NULL)) as within_3pts_pct,
  SAFE_DIVIDE(COUNTIF(prediction_error <= 5), COUNTIF(actual_points IS NOT NULL)) as within_5pts_pct,

  -- Betting
  SAFE_DIVIDE(COUNTIF(bet_outcome = 'WIN'), COUNTIF(bet_outcome IN ('WIN', 'LOSS'))) as bet_accuracy,

  -- vs Baseline
  SAFE_DIVIDE(COUNTIF(beat_baseline = TRUE), COUNTIF(beat_baseline IS NOT NULL)) as beat_baseline_pct,

  -- vs Vegas
  SAFE_DIVIDE(COUNTIF(beat_vegas = TRUE), COUNTIF(beat_vegas IS NOT NULL)) as beat_vegas_pct,

  -- Recency
  MIN(game_date) as first_prediction,
  MAX(game_date) as last_prediction

FROM `nba-props-platform.nba_predictions.ml_model_predictions`
WHERE actual_points IS NOT NULL
GROUP BY model_id
ORDER BY mae ASC;

-- ============================================================================
-- Comparison View: Head-to-Head Model Comparison
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_ml_model_head_to_head` AS
WITH model_pairs AS (
  SELECT
    a.game_date,
    a.player_lookup,
    a.model_id as model_a,
    b.model_id as model_b,
    a.prediction_error as error_a,
    b.prediction_error as error_b,
    CASE
      WHEN a.prediction_error < b.prediction_error THEN 'model_a'
      WHEN b.prediction_error < a.prediction_error THEN 'model_b'
      ELSE 'tie'
    END as winner
  FROM `nba-props-platform.nba_predictions.ml_model_predictions` a
  JOIN `nba-props-platform.nba_predictions.ml_model_predictions` b
    ON a.game_date = b.game_date
    AND a.player_lookup = b.player_lookup
    AND a.model_id < b.model_id  -- Avoid duplicates
  WHERE a.actual_points IS NOT NULL
    AND b.actual_points IS NOT NULL
)
SELECT
  model_a,
  model_b,
  COUNT(*) as comparisons,
  COUNTIF(winner = 'model_a') as model_a_wins,
  COUNTIF(winner = 'model_b') as model_b_wins,
  COUNTIF(winner = 'tie') as ties,
  SAFE_DIVIDE(COUNTIF(winner = 'model_a'), COUNT(*)) as model_a_win_pct,
  AVG(error_a) as model_a_mae,
  AVG(error_b) as model_b_mae,
  AVG(error_a) - AVG(error_b) as mae_diff  -- Negative = model_a is better
FROM model_pairs
GROUP BY model_a, model_b
ORDER BY comparisons DESC;

-- ============================================================================
-- Usage Examples
-- ============================================================================

-- Get today's predictions from all models
-- SELECT model_id, player_lookup, predicted_points, betting_line, edge_vs_line
-- FROM `nba-props-platform.nba_predictions.ml_model_predictions`
-- WHERE game_date = CURRENT_DATE()
-- ORDER BY model_id, player_lookup;

-- Compare model accuracy for yesterday
-- SELECT *
-- FROM `nba-props-platform.nba_predictions.v_ml_model_daily_performance`
-- WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
-- ORDER BY mae ASC;

-- Get the current leaderboard
-- SELECT model_id, mae, bet_accuracy, beat_baseline_pct, graded_predictions
-- FROM `nba-props-platform.nba_predictions.v_ml_model_leaderboard`
-- ORDER BY mae ASC;

-- Head-to-head: v8 vs v9
-- SELECT *
-- FROM `nba-props-platform.nba_predictions.v_ml_model_head_to_head`
-- WHERE 'catboost_v8' IN (model_a, model_b)
--   AND 'catboost_v9' IN (model_a, model_b);
