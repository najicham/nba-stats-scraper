-- ============================================================================
-- Current Ml Predictions Table Schema
-- ============================================================================
-- Dataset: nba_predictions
-- Table: current_ml_predictions
-- Auto-generated from deployed BigQuery table
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.current_ml_predictions` (
  player_lookup STRING NOT NULL,
  game_id STRING NOT NULL,
  prediction_date DATE NOT NULL,
  game_date DATE NOT NULL,
  ml_points_prediction NUMERIC(5, 1),
  ml_over_probability NUMERIC(5, 3),
  ml_prediction_confidence NUMERIC(5, 2),
  recommendation STRING,
  confidence_tier STRING,
  referee_adjustment_applied NUMERIC(5, 1),
  pace_adjustment_applied NUMERIC(5, 1),
  similarity_sample_size INTEGER,
  model_version STRING NOT NULL,
  data_quality_tier STRING,
  created_at TIMESTAMP,
  processed_at TIMESTAMP
)
PARTITION BY DAY(prediction_date)
CLUSTER BY player_lookup, ml_prediction_confidence, game_date;
