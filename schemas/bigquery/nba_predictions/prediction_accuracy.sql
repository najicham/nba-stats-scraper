-- ============================================================================
-- Prediction Accuracy Table Schema
-- ============================================================================
-- Dataset: nba_predictions
-- Table: prediction_accuracy
-- Auto-generated from deployed BigQuery table
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.prediction_accuracy` (
  player_lookup STRING NOT NULL,
  game_id STRING NOT NULL,
  prediction_date DATE NOT NULL,
  game_date DATE NOT NULL,
  predicted_points NUMERIC(5, 1),
  actual_points INTEGER,
  predicted_over_prob NUMERIC(5, 3),
  actual_result STRING,
  absolute_error NUMERIC(5, 1),
  prediction_correct BOOLEAN,
  confidence_level NUMERIC(5, 2),
  referee_adjustment NUMERIC(5, 1),
  pace_adjustment NUMERIC(5, 1),
  similarity_sample_size INTEGER,
  chief_referee STRING,
  model_version STRING,
  processed_at TIMESTAMP
)
PARTITION BY DAY(game_date)
CLUSTER BY prediction_date, model_version;
