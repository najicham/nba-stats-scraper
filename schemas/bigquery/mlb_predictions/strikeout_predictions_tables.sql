-- ============================================================================
-- MLB Props Platform - Strikeout Prediction Tables
-- ML model predictions and accuracy tracking
-- File: schemas/bigquery/mlb_predictions/strikeout_predictions_tables.sql
-- ============================================================================
--
-- PHASE 5 PREDICTIONS
-- Stores model predictions for pitcher strikeout props
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_predictions.pitcher_strikeout_predictions` (
  -- ============================================================================
  -- IDENTIFIERS
  -- ============================================================================
  prediction_id STRING NOT NULL,              -- Unique prediction ID
  player_lookup STRING NOT NULL,              -- Pitcher identifier
  player_full_name STRING,                    -- Display name
  game_id STRING NOT NULL,                    -- Game identifier
  game_date DATE NOT NULL,                    -- Game date (partition key)
  team_abbr STRING NOT NULL,                  -- Pitcher's team
  opponent_team_abbr STRING NOT NULL,         -- Opponent team
  season_year INT64 NOT NULL,

  -- ============================================================================
  -- BETTING LINE
  -- ============================================================================
  strikeouts_line NUMERIC(4,1) NOT NULL,      -- Prop line (e.g., 6.5)
  over_odds INT64,                            -- Over odds (e.g., -110)
  under_odds INT64,                           -- Under odds (e.g., -110)
  line_source STRING,                         -- Source (odds_api, etc.)
  line_captured_at TIMESTAMP,                 -- When line was captured

  -- ============================================================================
  -- MODEL PREDICTIONS (Ensemble approach like NBA)
  -- ============================================================================
  -- Moving Average Model
  ma_prediction NUMERIC(5,2),                 -- Moving average prediction
  ma_confidence NUMERIC(4,3),                 -- Confidence 0-1

  -- Similarity Model (bucket-based)
  sim_prediction NUMERIC(5,2),                -- Similarity model prediction
  sim_confidence NUMERIC(4,3),
  sim_games_matched INT64,                    -- Number of similar games found

  -- XGBoost Model
  xgb_prediction NUMERIC(5,2),                -- XGBoost prediction
  xgb_confidence NUMERIC(4,3),

  -- Ensemble (Weighted Average)
  ensemble_prediction NUMERIC(5,2),           -- Final ensemble prediction
  ensemble_confidence NUMERIC(4,3),

  -- ============================================================================
  -- RECOMMENDATION
  -- ============================================================================
  recommended_bet STRING,                     -- 'OVER', 'UNDER', or 'NO_BET'
  edge_percentage NUMERIC(5,2),               -- Predicted edge over line
  bet_rating STRING,                          -- 'STRONG', 'MODERATE', 'LEAN', 'SKIP'

  -- ============================================================================
  -- KEY FACTORS
  -- ============================================================================
  k_avg_last_5 NUMERIC(4,2),                  -- Recent form
  season_k_per_9 NUMERIC(4,2),                -- Season baseline
  is_home BOOL,                               -- Home/away
  is_day_game BOOL,                           -- Day/night
  opponent_k_rate NUMERIC(4,3),               -- Opponent K tendency
  days_rest INT64,                            -- Rest factor

  -- ============================================================================
  -- ACTUAL RESULT (filled after game)
  -- ============================================================================
  actual_strikeouts INT64,                    -- Actual strikeouts
  actual_innings NUMERIC(4,1),                -- Actual innings
  result STRING,                              -- 'WIN', 'LOSS', 'PUSH', NULL
  prediction_error NUMERIC(5,2),              -- ensemble_prediction - actual

  -- ============================================================================
  -- GRADING (filled after settlement)
  -- ============================================================================
  is_correct BOOL,                            -- Prediction was correct
  graded_at TIMESTAMP,                        -- When graded

  -- ============================================================================
  -- METADATA
  -- ============================================================================
  model_version STRING NOT NULL,              -- Model version used
  created_at TIMESTAMP NOT NULL,
  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY player_lookup, team_abbr, season_year
OPTIONS (
  description = "MLB pitcher strikeout predictions with ensemble model outputs and accuracy tracking.",
  require_partition_filter = true
);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Today's predictions
CREATE OR REPLACE VIEW `nba-props-platform.mlb_predictions.todays_strikeout_picks` AS
SELECT
  player_full_name,
  team_abbr,
  opponent_team_abbr,
  is_home,
  strikeouts_line,
  ensemble_prediction,
  recommended_bet,
  edge_percentage,
  bet_rating,
  k_avg_last_5,
  season_k_per_9,
  days_rest
FROM `nba-props-platform.mlb_predictions.pitcher_strikeout_predictions`
WHERE game_date = CURRENT_DATE()
  AND recommended_bet IN ('OVER', 'UNDER')
ORDER BY ABS(edge_percentage) DESC;

-- Prediction accuracy summary
CREATE OR REPLACE VIEW `nba-props-platform.mlb_predictions.strikeout_accuracy_summary` AS
SELECT
  game_date,
  COUNT(*) as total_predictions,
  COUNT(CASE WHEN is_correct = TRUE THEN 1 END) as correct,
  COUNT(CASE WHEN is_correct = FALSE THEN 1 END) as incorrect,
  ROUND(COUNT(CASE WHEN is_correct = TRUE THEN 1 END) * 100.0 / NULLIF(COUNT(CASE WHEN is_correct IS NOT NULL THEN 1 END), 0), 1) as accuracy_pct,
  AVG(ABS(prediction_error)) as avg_error,
  COUNT(CASE WHEN bet_rating = 'STRONG' AND is_correct = TRUE THEN 1 END) as strong_bets_correct,
  COUNT(CASE WHEN bet_rating = 'STRONG' THEN 1 END) as strong_bets_total
FROM `nba-props-platform.mlb_predictions.pitcher_strikeout_predictions`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND is_correct IS NOT NULL
GROUP BY game_date
ORDER BY game_date DESC;

-- Model comparison
CREATE OR REPLACE VIEW `nba-props-platform.mlb_predictions.model_comparison` AS
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  -- Moving Average accuracy
  ROUND(AVG(CASE WHEN (ma_prediction > strikeouts_line AND actual_strikeouts > strikeouts_line)
                  OR (ma_prediction < strikeouts_line AND actual_strikeouts < strikeouts_line)
             THEN 1.0 ELSE 0.0 END) * 100, 1) as ma_accuracy,
  -- Similarity accuracy
  ROUND(AVG(CASE WHEN (sim_prediction > strikeouts_line AND actual_strikeouts > strikeouts_line)
                  OR (sim_prediction < strikeouts_line AND actual_strikeouts < strikeouts_line)
             THEN 1.0 ELSE 0.0 END) * 100, 1) as sim_accuracy,
  -- XGBoost accuracy
  ROUND(AVG(CASE WHEN (xgb_prediction > strikeouts_line AND actual_strikeouts > strikeouts_line)
                  OR (xgb_prediction < strikeouts_line AND actual_strikeouts < strikeouts_line)
             THEN 1.0 ELSE 0.0 END) * 100, 1) as xgb_accuracy,
  -- Ensemble accuracy
  ROUND(AVG(CASE WHEN is_correct = TRUE THEN 1.0 ELSE 0.0 END) * 100, 1) as ensemble_accuracy,
  COUNT(*) as sample_size
FROM `nba-props-platform.mlb_predictions.pitcher_strikeout_predictions`
WHERE actual_strikeouts IS NOT NULL
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY week
ORDER BY week DESC;
