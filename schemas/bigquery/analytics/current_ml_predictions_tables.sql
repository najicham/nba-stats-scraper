-- ============================================================================
-- NBA Props Platform - Current ML Predictions Analytics Table
-- ML model predictions for upcoming games with NBA-focused context adjustments
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_analytics.current_ml_predictions` (
  -- Identifiers (4 fields)
  player_lookup STRING NOT NULL,                    -- Normalized player identifier
  game_id STRING NOT NULL,                          -- Unique game identifier
  prediction_date DATE NOT NULL,                    -- Date prediction was made
  game_date DATE NOT NULL,                          -- Game date
  
  -- Core predictions (3 fields)
  ml_points_prediction NUMERIC(5,1),                -- Model's point prediction
  ml_over_probability NUMERIC(5,3),                 -- Probability of over (0-1)
  ml_prediction_confidence NUMERIC(5,2),            -- Confidence (0-100)
  
  -- Decision support (2 fields)
  recommendation STRING,                            -- 'OVER', 'UNDER', 'PASS'
  confidence_tier STRING,                           -- 'HIGH', 'MEDIUM', 'LOW'
  
  -- Context adjustments (3 fields)
  referee_adjustment_applied NUMERIC(5,1),          -- Referee impact
  pace_adjustment_applied NUMERIC(5,1),             -- Pace impact  
  similarity_sample_size INT64,                     -- Historical games used
  
  -- Model metadata (2 fields)
  model_version STRING NOT NULL,                    -- Model version used
  data_quality_tier STRING,                        -- Input data quality
  
  -- Processing metadata (2 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  processed_at TIMESTAMP
)
PARTITION BY prediction_date
CLUSTER BY player_lookup, ml_prediction_confidence, game_date
OPTIONS(
  description="ML model predictions for upcoming games with NBA-focused context adjustments"
);