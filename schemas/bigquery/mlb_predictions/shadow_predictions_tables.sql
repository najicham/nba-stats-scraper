-- ============================================================================
-- MLB Shadow Mode Predictions Table
-- Stores V1.4 vs V1.6 model comparison predictions
-- Created: 2026-01-15
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_predictions.shadow_mode_predictions` (
  -- Identifiers
  pitcher_lookup STRING NOT NULL,
  game_date DATE NOT NULL,
  game_id STRING,
  team_abbr STRING,
  opponent_team_abbr STRING,
  strikeouts_line FLOAT64,

  -- V1.4 (Champion) Predictions
  v1_4_predicted FLOAT64,
  v1_4_confidence FLOAT64,
  v1_4_recommendation STRING,
  v1_4_edge FLOAT64,

  -- V1.6 (Challenger) Predictions
  v1_6_predicted FLOAT64,
  v1_6_confidence FLOAT64,
  v1_6_recommendation STRING,
  v1_6_edge FLOAT64,

  -- Comparison Metrics
  prediction_diff FLOAT64,          -- v1_6 - v1_4
  recommendation_agrees BOOL,       -- Same OVER/UNDER/PASS recommendation

  -- Actual Results (filled after game)
  actual_strikeouts INT64,
  v1_4_error FLOAT64,               -- v1_4_predicted - actual
  v1_6_error FLOAT64,               -- v1_6_predicted - actual
  v1_4_correct BOOL,                -- v1_4 recommendation was correct
  v1_6_correct BOOL,                -- v1_6 recommendation was correct
  closer_prediction STRING,         -- 'v1_4', 'v1_6', or 'tie'

  -- Metadata
  v1_4_model_version STRING,
  v1_6_model_version STRING,
  timestamp TIMESTAMP,
  graded_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY pitcher_lookup, team_abbr
OPTIONS (
  description = "MLB shadow mode predictions comparing V1.4 champion vs V1.6 challenger models",
  require_partition_filter = true
);


-- ============================================================================
-- VIEWS
-- ============================================================================

-- Model performance comparison (graded predictions only)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_predictions.shadow_model_comparison` AS
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as predictions,
  -- V1.4 stats
  COUNTIF(v1_4_correct) as v1_4_correct,
  ROUND(COUNTIF(v1_4_correct) * 100.0 / NULLIF(COUNT(*), 0), 1) as v1_4_accuracy,
  ROUND(AVG(ABS(v1_4_error)), 2) as v1_4_mae,
  -- V1.6 stats
  COUNTIF(v1_6_correct) as v1_6_correct,
  ROUND(COUNTIF(v1_6_correct) * 100.0 / NULLIF(COUNT(*), 0), 1) as v1_6_accuracy,
  ROUND(AVG(ABS(v1_6_error)), 2) as v1_6_mae,
  -- Which model was better
  COUNTIF(closer_prediction = 'v1_6') as v1_6_closer,
  COUNTIF(closer_prediction = 'v1_4') as v1_4_closer,
  COUNTIF(closer_prediction = 'tie') as ties
FROM `nba-props-platform.mlb_predictions.shadow_mode_predictions`
WHERE actual_strikeouts IS NOT NULL
GROUP BY week
ORDER BY week DESC;


-- Daily comparison
CREATE OR REPLACE VIEW `nba-props-platform.mlb_predictions.shadow_daily_comparison` AS
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNTIF(v1_4_correct) as v1_4_correct,
  COUNTIF(v1_6_correct) as v1_6_correct,
  ROUND(AVG(prediction_diff), 2) as avg_diff,
  COUNTIF(recommendation_agrees) as same_rec,
  COUNTIF(NOT recommendation_agrees) as diff_rec
FROM `nba-props-platform.mlb_predictions.shadow_mode_predictions`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date
ORDER BY game_date DESC;


-- Ungraded predictions (need results)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_predictions.shadow_pending_grading` AS
SELECT
  game_date,
  COUNT(*) as pending_count
FROM `nba-props-platform.mlb_predictions.shadow_mode_predictions`
WHERE actual_strikeouts IS NULL
  AND game_date < CURRENT_DATE()
GROUP BY game_date
ORDER BY game_date DESC;
