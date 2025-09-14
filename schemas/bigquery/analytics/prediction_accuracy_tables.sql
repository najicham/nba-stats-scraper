-- ============================================================================
-- NBA Props Platform - Prediction Accuracy Analytics Table
-- ML model accuracy tracking with NBA-focused context adjustment analysis
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_analytics.prediction_accuracy` (
  -- Identifiers (4 fields)
  player_lookup STRING NOT NULL,                    -- Normalized player identifier
  game_id STRING NOT NULL,                          -- Unique game identifier
  prediction_date DATE NOT NULL,                    -- Date prediction was made
  game_date DATE NOT NULL,                          -- Game date
  
  -- Prediction vs reality (4 fields)
  predicted_points NUMERIC(5,1),                    -- What model predicted
  actual_points INT64,                              -- What actually happened
  predicted_over_prob NUMERIC(5,3),                 -- Predicted probability of over
  actual_result STRING,                             -- Actual result: 'OVER' or 'UNDER'
  
  -- Accuracy metrics (3 fields)
  absolute_error NUMERIC(5,1),                      -- |predicted - actual| points
  prediction_correct BOOLEAN,                       -- Whether over/under prediction was correct
  confidence_level NUMERIC(5,2),                    -- Model's confidence level
  
  -- Context tracking (4 fields)
  referee_adjustment NUMERIC(5,1),                  -- Referee adjustment used
  pace_adjustment NUMERIC(5,1),                     -- Pace adjustment used
  similarity_sample_size INT64,                     -- Historical sample
  chief_referee STRING,                             -- Referee for analysis
  
  -- Model tracking (1 field)
  model_version STRING,                             -- Model version used
  
  -- Processing metadata (1 field)
  processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY prediction_date, model_version
OPTIONS(
  description="ML model accuracy tracking with NBA-focused context adjustment analysis"
);