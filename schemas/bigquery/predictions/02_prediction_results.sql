-- Path: schemas/bigquery/predictions/02_prediction_results.sql
-- ============================================================================
-- Table: prediction_results
-- File: 02_prediction_results.sql
-- Purpose: Actual game outcomes compared to predictions (post-game analysis)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.prediction_results` (
  -- Identifiers (6 fields)
  prediction_id STRING NOT NULL,                    -- Links to player_prop_predictions
  system_id STRING NOT NULL,
  player_lookup STRING NOT NULL,
  universal_player_id STRING,
  prediction_date DATE NOT NULL,                    -- When prediction was made
  game_date DATE NOT NULL,                          -- When game occurred (partition key)
  
  -- Prediction vs Reality (6 fields)
  predicted_points NUMERIC(5,1) NOT NULL,           -- What we predicted
  actual_points INT64 NOT NULL,                     -- What actually happened
  predicted_recommendation STRING NOT NULL,         -- Our recommendation ('OVER', 'UNDER', 'PASS')
  actual_result STRING NOT NULL,                    -- Actual result ('OVER', 'UNDER', 'PUSH')
  prediction_line NUMERIC(4,1) NOT NULL,            -- Line at time of prediction
  actual_line NUMERIC(4,1),                         -- Final closing line (may differ)
  
  -- Accuracy Metrics (6 fields)
  prediction_error NUMERIC(5,2) NOT NULL,           -- |predicted - actual|
  prediction_correct BOOLEAN NOT NULL,              -- Whether OVER/UNDER call was correct
  within_3_points BOOLEAN NOT NULL,                 -- |error| <= 3
  within_5_points BOOLEAN NOT NULL,                 -- |error| <= 5
  line_margin NUMERIC(5,2) NOT NULL,                -- predicted - line
  actual_margin NUMERIC(5,2) NOT NULL,              -- actual - line
  
  -- Confidence Analysis (3 fields)
  confidence_score NUMERIC(5,2) NOT NULL,           -- Our confidence level
  confidence_calibrated BOOLEAN,                    -- Was confidence justified?
  confidence_tier STRING,                           -- 'HIGH', 'MEDIUM', 'LOW'
  
  -- Context Snapshot (4 fields)
  fatigue_score INT64,                              -- Player's fatigue at prediction time
  shot_zone_mismatch_score NUMERIC(4,1),            -- Matchup score at prediction time
  similar_games_count INT64,                        -- Sample size (rule-based)
  key_factors JSON,                                 -- Snapshot of important factors
  
  -- Processing (2 fields)
  processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  updated_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY system_id, prediction_date, prediction_correct
OPTIONS(
  description="Prediction outcomes vs actual results. Used for accuracy tracking, model improvement, and performance analysis.",
  partition_expiration_days=1095,
  require_partition_filter=TRUE
);
