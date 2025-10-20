-- ============================================================================
-- NBA Props Platform - Phase 5 Prediction Tables
-- File: schemas/bigquery/predictions/prediction_tables.sql
-- Purpose: Multi-system prediction framework with ML integration
-- Update: Daily (6-8 AM) + real-time when context/lines change
-- 
-- Related Documents:
-- - Document 2: Similarity Matching Engine
-- - Document 3: Composite Factor Calculations
-- - Document 4: Prediction System Framework
-- - Document 11: ML Integration Guide
-- ============================================================================

-- ============================================================================
-- Table 1: prediction_systems
-- ============================================================================
-- Registry of all prediction systems (rule-based, ML, ensemble)
-- Updated: When new systems deployed or configurations changed
-- Used by: Orchestrator to load and run systems
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.prediction_systems` (
  -- Identifiers (4 fields)
  system_id STRING PRIMARY KEY NOT NULL,            -- e.g., "similarity_balanced_v1"
  system_name STRING NOT NULL,                      -- Human-readable name
  system_type STRING NOT NULL,                      -- 'similarity_based', 'ml', 'ensemble'
  version STRING NOT NULL,                          -- Semantic version: "1.2.3"
  
  -- Status (2 fields)
  active BOOLEAN NOT NULL DEFAULT TRUE,             -- Whether system runs in production
  is_champion BOOLEAN NOT NULL DEFAULT FALSE,       -- Designated as primary recommendation system
  
  -- Configuration (stored as JSON) (1 field)
  config JSON NOT NULL,                             -- Full system configuration (weights, thresholds, features)
  
  -- Performance Tracking (4 fields)
  lifetime_predictions INT64 DEFAULT 0,             -- Total predictions made
  lifetime_accuracy NUMERIC(5,3),                   -- Overall accuracy (0-1)
  last_7_days_accuracy NUMERIC(5,3),                -- Recent accuracy
  last_30_days_accuracy NUMERIC(5,3),               -- Monthly accuracy
  
  -- ML Model Reference (2 fields) - Only populated for ML systems
  model_id STRING,                                  -- Links to ml_models table
  model_file_path STRING,                           -- GCS path to model file
  
  -- Metadata (5 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  last_updated TIMESTAMP,
  last_prediction_at TIMESTAMP,                     -- When system last ran
  created_by STRING,                                -- Who created/deployed system
  notes STRING                                      -- Deployment notes, change history
)
OPTIONS(
  description="Registry of all prediction systems. Rule-based, ML, and ensemble systems with configurations and performance tracking."
);

-- ============================================================================
-- Table 2: player_prop_predictions
-- ============================================================================
-- All predictions from all systems for all players
-- Updated: Daily (6-8 AM) + when context changes
-- Used by: Reports, performance analysis, system comparison
-- CRITICAL TABLE - Stores every prediction from every system
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.player_prop_predictions` (
  -- Identifiers (7 fields)
  prediction_id STRING PRIMARY KEY NOT NULL,        -- Unique prediction ID
  system_id STRING NOT NULL,                        -- Which system made this prediction
  player_lookup STRING NOT NULL,
  universal_player_id STRING,
  game_date DATE NOT NULL,                          -- Partition key
  game_id STRING NOT NULL,
  prediction_version INT64 NOT NULL DEFAULT 1,      -- Version (increments on updates)
  
  -- Core Prediction (3 fields)
  predicted_points NUMERIC(5,1) NOT NULL,           -- Predicted points
  confidence_score NUMERIC(5,2) NOT NULL,           -- Confidence (0-100)
  recommendation STRING NOT NULL,                   -- 'OVER', 'UNDER', 'PASS'
  
  -- Prediction Components (9 fields)
  -- What went into this prediction
  similarity_baseline NUMERIC(5,1),                 -- Baseline from similar games (rule-based only)
  fatigue_adjustment NUMERIC(5,2),                  -- Points adjustment from fatigue
  shot_zone_adjustment NUMERIC(5,2),                -- Points adjustment from matchup
  referee_adjustment NUMERIC(5,2),                  -- Points adjustment from referee
  look_ahead_adjustment NUMERIC(5,2),               -- Points adjustment from schedule
  pace_adjustment NUMERIC(5,2),                     -- Points adjustment from pace
  usage_spike_adjustment NUMERIC(5,2),              -- Points adjustment from role changes
  home_away_adjustment NUMERIC(5,2),                -- Points adjustment from venue
  other_adjustments NUMERIC(5,2),                   -- Sum of matchup_history + momentum
  
  -- Supporting Metadata (6 fields)
  similar_games_count INT64,                        -- Sample size (rule-based only)
  avg_similarity_score NUMERIC(5,2),                -- Quality of matches (rule-based only)
  min_similarity_score NUMERIC(5,2),                -- Minimum match quality
  current_points_line NUMERIC(4,1),                 -- Line at time of prediction
  line_margin NUMERIC(5,2),                         -- predicted_points - current_points_line
  ml_model_id STRING,                               -- Model used (ML systems only)
  
  -- Key Factors & Warnings (2 fields stored as JSON)
  key_factors JSON,                                 -- Important factors: {"extreme_fatigue": true, "paint_mismatch": +6.2}
  warnings JSON,                                    -- Warnings: ["low_sample_size", "high_variance"]
  
  -- Status (2 fields)
  is_active BOOLEAN NOT NULL DEFAULT TRUE,          -- FALSE when superseded by newer version
  superseded_by STRING,                             -- prediction_id that replaced this one
  
  -- Timestamps (2 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  updated_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY system_id, player_lookup, confidence_score DESC, game_date
OPTIONS(
  description="All predictions from all systems. Multiple systems predict for same player, enabling comparison. Versioned for real-time updates.",
  partition_expiration_days=365
);

-- ============================================================================
-- Table 3: prediction_results
-- ============================================================================
-- Actual game outcomes compared to predictions
-- Updated: After games complete (next day)
-- Used by: Performance analysis, model improvement, backtesting
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.prediction_results` (
  -- Identifiers (6 fields)
  prediction_id STRING PRIMARY KEY NOT NULL,        -- Links to player_prop_predictions
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
  -- Capture key factors for analysis
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
  partition_expiration_days=1095  -- Keep 3 years for long-term analysis
);

-- ============================================================================
-- Table 4: system_daily_performance
-- ============================================================================
-- Daily performance summary for each system
-- Updated: Nightly after games complete
-- Used by: System comparison, champion selection, monitoring
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.system_daily_performance` (
  -- Identifiers (3 fields)
  system_id STRING NOT NULL,
  performance_date DATE NOT NULL,                   -- Date of games analyzed (partition key)
  calculated_at TIMESTAMP NOT NULL,
  
  -- Volume Metrics (4 fields)
  total_predictions INT64 NOT NULL,                 -- Total predictions made
  over_recommendations INT64 NOT NULL,              -- OVER calls
  under_recommendations INT64 NOT NULL,             -- UNDER calls
  pass_recommendations INT64 NOT NULL,              -- PASS calls
  
  -- Accuracy Metrics (8 fields)
  overall_accuracy NUMERIC(5,3) NOT NULL,           -- % correct OVER/UNDER calls
  avg_prediction_error NUMERIC(5,2) NOT NULL,       -- Mean absolute error
  rmse NUMERIC(5,2) NOT NULL,                       -- Root mean squared error
  within_3_points_rate NUMERIC(5,3) NOT NULL,       -- % within 3 points
  within_5_points_rate NUMERIC(5,3) NOT NULL,       -- % within 5 points
  over_accuracy NUMERIC(5,3),                       -- Accuracy on OVER calls
  under_accuracy NUMERIC(5,3),                      -- Accuracy on UNDER calls
  avg_confidence NUMERIC(5,2),                      -- Average confidence score
  
  -- Confidence Calibration (3 fields)
  high_conf_predictions INT64,                      -- Predictions with conf >= 85
  high_conf_accuracy NUMERIC(5,3),                  -- Accuracy of high confidence predictions
  confidence_calibration_score NUMERIC(5,3),        -- How well confidence matches accuracy
  
  -- Performance Trends (3 fields)
  performance_vs_7day_avg NUMERIC(6,3),             -- Today vs 7-day average (relative)
  performance_vs_30day_avg NUMERIC(6,3),            -- Today vs 30-day average (relative)
  trend_direction STRING,                           -- 'IMPROVING', 'STABLE', 'DECLINING'
  
  -- Best/Worst (2 fields)
  best_prediction_id STRING,                        -- Most accurate prediction today
  worst_prediction_id STRING,                       -- Least accurate prediction today
  
  -- System Info (2 fields)
  system_version STRING,                            -- Version used this day
  system_config_snapshot JSON                       -- Config snapshot for this day
)
PARTITION BY performance_date
CLUSTER BY system_id, performance_date DESC
OPTIONS(
  description="Daily performance metrics for each prediction system. Used for system comparison and champion selection.",
  partition_expiration_days=1095
);

-- ============================================================================
-- Table 5: weight_adjustment_log
-- ============================================================================
-- History of configuration changes to systems
-- Updated: When system configs are modified
-- Used by: Auditing, A/B testing analysis, rollback
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.weight_adjustment_log` (
  -- Identifiers (4 fields)
  adjustment_id STRING PRIMARY KEY NOT NULL,
  system_id STRING NOT NULL,
  adjustment_date DATE NOT NULL,                    -- Partition key
  adjustment_type STRING NOT NULL,                  -- 'WEIGHTS', 'THRESHOLDS', 'FEATURES', 'VERSION'
  
  -- Changes (3 fields)
  previous_config JSON NOT NULL,                    -- Config before change
  new_config JSON NOT NULL,                         -- Config after change
  changes_summary STRING NOT NULL,                  -- Human-readable summary
  
  -- Rationale (3 fields)
  reason STRING NOT NULL,                           -- Why change was made
  triggered_by STRING NOT NULL,                     -- 'MANUAL', 'AUTOMATIC', 'BACKTEST'
  approved_by STRING,                               -- Who approved (if manual)
  
  -- Performance Impact (4 fields)
  performance_before_7d NUMERIC(5,3),               -- Accuracy in 7 days before change
  performance_after_7d NUMERIC(5,3),                -- Accuracy in 7 days after change
  performance_delta NUMERIC(6,3),                   -- Improvement/decline
  rollback_flag BOOLEAN DEFAULT FALSE,              -- TRUE if change was rolled back
  
  -- Metadata (2 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  notes STRING
)
PARTITION BY adjustment_date
CLUSTER BY system_id, adjustment_date DESC
OPTIONS(
  description="History of system configuration changes. Tracks adjustments, performance impact, and enables rollback.",
  partition_expiration_days=1095
);

-- ============================================================================
-- ML-SPECIFIC TABLES
-- ============================================================================

-- ============================================================================
-- Table 6: ml_models
-- ============================================================================
-- Registry of trained ML models
-- Updated: When models are trained or retrained
-- Used by: ML prediction systems, model management
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.ml_models` (
  -- Identifiers (5 fields)
  model_id STRING PRIMARY KEY NOT NULL,             -- e.g., "xgboost_lebron_v1"
  model_name STRING NOT NULL,
  model_type STRING NOT NULL,                       -- 'xgboost', 'random_forest', 'linear', 'neural_network'
  version STRING NOT NULL,                          -- Semantic version
  model_scope STRING NOT NULL,                      -- 'player_specific', 'universal', 'position_based'
  
  -- Scope Details (2 fields)
  player_lookup STRING,                             -- If player_specific
  position STRING,                                  -- If position_based
  
  -- Model Storage (2 fields)
  model_file_path STRING NOT NULL,                  -- GCS path to model file
  model_size_bytes INT64,                           -- File size
  
  -- Training Performance (6 fields)
  training_mae NUMERIC(5,2),                        -- Mean absolute error on training set
  validation_mae NUMERIC(5,2),                      -- MAE on validation set
  test_mae NUMERIC(5,2),                            -- MAE on held-out test set
  training_samples INT64,                           -- Games used for training
  validation_samples INT64,                         -- Games used for validation
  test_samples INT64,                               -- Games used for testing
  
  -- Features (2 fields)
  features_used JSON NOT NULL,                      -- Array of feature names
  feature_importance JSON,                          -- Feature importance scores
  
  -- Hyperparameters (1 field)
  hyperparameters JSON NOT NULL,                    -- Model hyperparameters
  
  -- Status (3 fields)
  active BOOLEAN NOT NULL DEFAULT TRUE,
  production_ready BOOLEAN NOT NULL DEFAULT FALSE,  -- Passed validation for production
  trained_on_date DATE NOT NULL,                    -- When model was trained
  
  -- Performance Tracking (3 fields)
  last_retrained DATE,                              -- Most recent retraining
  production_predictions INT64 DEFAULT 0,           -- Predictions made in production
  production_accuracy NUMERIC(5,3),                 -- Accuracy in production
  
  -- Retraining Triggers (2 fields)
  needs_retraining BOOLEAN DEFAULT FALSE,           -- Flag for retraining needed
  retraining_reason STRING,                         -- Why retraining is needed
  
  -- Metadata (3 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  updated_at TIMESTAMP,
  notes STRING
)
OPTIONS(
  description="Registry of trained ML models with performance metrics and metadata. Tracks training, validation, and production performance."
);

-- ============================================================================
-- Table 7: ml_feature_store
-- ============================================================================
-- Features for ML predictions (historical + upcoming)
-- Updated: Nightly for historical, daily for upcoming games
-- Used by: ML training and prediction
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.ml_feature_store` (
  -- Identifiers (4 fields)
  player_lookup STRING NOT NULL,
  universal_player_id STRING,
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,                          -- Partition key
  
  -- Player Fatigue Features (6 fields)
  days_rest INT64,
  games_in_last_7_days INT64,
  games_in_last_14_days INT64,
  minutes_in_last_7_days INT64,
  fatigue_score INT64,
  back_to_back BOOLEAN,
  
  -- Player Performance Features (5 fields)
  points_avg_last_5 NUMERIC(5,1),
  points_avg_last_10 NUMERIC(5,1),
  points_std_dev_last_10 NUMERIC(5,2),
  shooting_pct_last_5 NUMERIC(5,3),
  usage_rate_last_7 NUMERIC(5,2),
  
  -- Shot Zone Features (6 fields)
  paint_rate_last_10 NUMERIC(5,2),
  paint_efficiency_last_10 NUMERIC(5,3),
  mid_range_rate_last_10 NUMERIC(5,2),
  three_pt_rate_last_10 NUMERIC(5,2),
  paint_attempts_per_game NUMERIC(4,1),
  assisted_rate_last_10 NUMERIC(5,2),
  
  -- Opponent Features (5 fields)
  opponent_def_rating_last_10 NUMERIC(6,2),
  opponent_pace_last_10 NUMERIC(5,1),
  opponent_paint_pct_allowed NUMERIC(5,3),
  opponent_three_pt_pct_allowed NUMERIC(5,3),
  opponent_days_rest INT64,
  
  -- Game Context Features (4 fields)
  home_game BOOLEAN,
  game_pace_projected NUMERIC(5,1),
  game_total NUMERIC(5,1),
  current_points_line NUMERIC(4,1),
  
  -- Shot Zone Matchup Features (3 fields)
  paint_mismatch_score NUMERIC(5,2),
  mid_range_mismatch_score NUMERIC(5,2),
  three_pt_mismatch_score NUMERIC(5,2),
  
  -- Referee Features (2 fields)
  chief_avg_total_points NUMERIC(5,1),
  chief_avg_fouls_per_game NUMERIC(4,1),
  
  -- Look-Ahead Features (2 fields)
  next_game_days_rest INT64,
  games_in_next_7_days INT64,
  
  -- Player Characteristics (2 fields)
  player_age INT64,
  years_in_league INT64,
  
  -- Career vs Opponent (2 fields)
  career_games_vs_opponent INT64,
  career_avg_vs_opponent NUMERIC(5,1),
  
  -- Derived Interaction Features (3 fields)
  fatigue_x_opponent_def NUMERIC(8,2),              -- fatigue_score × opponent_def_rating
  rest_advantage INT64,                             -- days_rest - opponent_days_rest
  paint_rate_x_paint_defense NUMERIC(7,4),          -- paint_rate × paint_pct_allowed
  
  -- Target Variable (1 field)
  actual_points INT64,                              -- NULL for upcoming games, populated for historical
  
  -- Metadata (3 fields)
  feature_version STRING NOT NULL,                  -- Version of feature calculation
  is_training_data BOOLEAN NOT NULL,                -- TRUE if used for training
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY player_lookup, game_date, is_training_data
OPTIONS(
  description="Features for ML model training and prediction. Contains all features needed for ML models.",
  partition_expiration_days=1825  -- Keep 5 years for model training
);

-- ============================================================================
-- Table 8: ml_training_runs
-- ============================================================================
-- History of model training runs
-- Updated: Each time a model is trained
-- Used by: Model management, performance tracking, debugging
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.ml_training_runs` (
  -- Identifiers (4 fields)
  run_id STRING PRIMARY KEY NOT NULL,
  model_id STRING NOT NULL,
  run_date DATE NOT NULL,                           -- Partition key
  run_type STRING NOT NULL,                         -- 'INITIAL', 'RETRAIN', 'HYPERPARAMETER_TUNING'
  
  -- Training Details (4 fields)
  training_start_date DATE NOT NULL,                -- First game in training data
  training_end_date DATE NOT NULL,                  -- Last game in training data
  training_duration_seconds INT64,                  -- How long training took
  training_completed_at TIMESTAMP,
  
  -- Data Splits (4 fields)
  total_samples INT64 NOT NULL,
  training_samples INT64 NOT NULL,
  validation_samples INT64 NOT NULL,
  test_samples INT64 NOT NULL,
  
  -- Performance Metrics (6 fields)
  train_mae NUMERIC(5,2) NOT NULL,
  validation_mae NUMERIC(5,2) NOT NULL,
  test_mae NUMERIC(5,2) NOT NULL,
  train_rmse NUMERIC(5,2),
  validation_rmse NUMERIC(5,2),
  test_rmse NUMERIC(5,2),
  
  -- Over/Under Accuracy (3 fields)
  validation_ou_accuracy NUMERIC(5,3),              -- % correct OVER/UNDER calls
  validation_within_3_pts NUMERIC(5,3),             -- % predictions within 3 points
  validation_within_5_pts NUMERIC(5,3),             -- % predictions within 5 points
  
  -- Hyperparameters (2 fields)
  hyperparameters_tested JSON,                      -- All configs tested (if tuning)
  best_hyperparameters JSON NOT NULL,               -- Best config found
  
  -- Feature Importance (1 field)
  feature_importance JSON NOT NULL,                 -- Feature importance from this run
  
  -- Comparison to Previous (2 fields)
  previous_model_version STRING,                    -- Previous model (if retraining)
  improvement_over_previous NUMERIC(6,3),           -- MAE improvement (can be negative)
  
  -- Status (2 fields)
  training_status STRING NOT NULL,                  -- 'SUCCESS', 'FAILED', 'RUNNING'
  error_message STRING,                             -- If failed
  
  -- Deployment Decision (3 fields)
  deployed_to_production BOOLEAN DEFAULT FALSE,
  deployment_reason STRING,                         -- Why deployed or not
  deployed_at TIMESTAMP,
  
  -- Metadata (2 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  notes STRING
)
PARTITION BY run_date
CLUSTER BY model_id, run_date DESC
OPTIONS(
  description="History of ML model training runs with performance metrics and deployment decisions.",
  partition_expiration_days=1095
);

-- ============================================================================
-- Table 9: ml_prediction_metadata
-- ============================================================================
-- Additional ML-specific prediction details
-- Updated: When ML predictions are made
-- Used by: Debugging, explainability, confidence calibration
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.ml_prediction_metadata` (
  -- Identifiers (4 fields)
  prediction_id STRING PRIMARY KEY NOT NULL,        -- Links to player_prop_predictions
  model_id STRING NOT NULL,
  player_lookup STRING NOT NULL,
  game_date DATE NOT NULL,                          -- Partition key
  
  -- Prediction Details (3 fields)
  raw_prediction NUMERIC(5,2),                      -- Raw model output before post-processing
  prediction_std_dev NUMERIC(5,2),                  -- Uncertainty estimate (if available)
  prediction_confidence_score NUMERIC(5,2),         -- ML-specific confidence
  
  -- Feature Values (1 field)
  feature_values JSON NOT NULL,                     -- All input features for this prediction
  
  -- Feature Contributions (2 fields)
  top_positive_features JSON,                       -- Features pushing prediction UP
  top_negative_features JSON,                       -- Features pushing prediction DOWN
  
  -- Model Diagnostics (3 fields)
  out_of_distribution_flag BOOLEAN,                 -- TRUE if inputs differ significantly from training
  out_of_distribution_score NUMERIC(5,3),           -- How different from training distribution
  feature_warnings JSON,                            -- Any feature-level warnings
  
  -- Metadata (2 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL,
  ml_framework_version STRING                       -- XGBoost/scikit-learn version used
)
PARTITION BY game_date
CLUSTER BY model_id, player_lookup, game_date
OPTIONS(
  description="ML-specific prediction metadata for explainability and debugging. Links to player_prop_predictions.",
  partition_expiration_days=365
);

-- ============================================================================
-- Helper Views for Prediction Tables
-- ============================================================================

-- View: Today's predictions with champion system highlighted
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.todays_predictions_summary` AS
SELECT 
  p.player_lookup,
  p.game_id,
  s.system_name,
  s.is_champion,
  p.predicted_points,
  p.confidence_score,
  p.recommendation,
  p.current_points_line,
  p.line_margin,
  p.similar_games_count,
  p.key_factors
FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
JOIN `nba-props-platform.nba_predictions.prediction_systems` s 
  ON p.system_id = s.system_id
WHERE p.game_date = CURRENT_DATE()
  AND p.is_active = TRUE
  AND s.active = TRUE
ORDER BY s.is_champion DESC, p.confidence_score DESC;

-- View: System comparison for today
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.system_comparison_today` AS
SELECT 
  s.system_name,
  s.system_type,
  s.is_champion,
  COUNT(*) as predictions_made,
  AVG(p.confidence_score) as avg_confidence,
  AVG(p.predicted_points) as avg_predicted_points,
  SUM(CASE WHEN p.recommendation = 'OVER' THEN 1 ELSE 0 END) as over_count,
  SUM(CASE WHEN p.recommendation = 'UNDER' THEN 1 ELSE 0 END) as under_count,
  SUM(CASE WHEN p.recommendation = 'PASS' THEN 1 ELSE 0 END) as pass_count
FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
JOIN `nba-props-platform.nba_predictions.prediction_systems` s 
  ON p.system_id = s.system_id
WHERE p.game_date = CURRENT_DATE()
  AND p.is_active = TRUE
  AND s.active = TRUE
GROUP BY s.system_name, s.system_type, s.is_champion
ORDER BY s.is_champion DESC, predictions_made DESC;

-- View: System accuracy leaderboard (last 30 days)
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.system_accuracy_leaderboard` AS
SELECT 
  s.system_name,
  s.system_type,
  s.is_champion,
  COUNT(*) as total_predictions,
  AVG(CASE WHEN r.prediction_correct THEN 1.0 ELSE 0.0 END) as accuracy,
  AVG(r.prediction_error) as avg_error,
  AVG(r.confidence_score) as avg_confidence,
  AVG(CASE WHEN r.within_3_points THEN 1.0 ELSE 0.0 END) as within_3_rate,
  AVG(CASE WHEN r.within_5_points THEN 1.0 ELSE 0.0 END) as within_5_rate,
  -- High confidence performance
  AVG(CASE 
    WHEN r.confidence_score >= 85 AND r.prediction_correct THEN 1.0 
    WHEN r.confidence_score >= 85 THEN 0.0 
    ELSE NULL 
  END) as high_conf_accuracy
FROM `nba-props-platform.nba_predictions.prediction_results` r
JOIN `nba-props-platform.nba_predictions.prediction_systems` s 
  ON r.system_id = s.system_id
WHERE r.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY s.system_name, s.system_type, s.is_champion
HAVING total_predictions >= 30  -- Minimum sample size
ORDER BY accuracy DESC;

-- View: Recent prediction errors for debugging
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.recent_large_errors` AS
SELECT 
  r.system_id,
  r.player_lookup,
  r.game_date,
  r.predicted_points,
  r.actual_points,
  r.prediction_error,
  r.confidence_score,
  r.fatigue_score,
  r.shot_zone_mismatch_score,
  r.similar_games_count,
  r.key_factors
FROM `nba-props-platform.nba_predictions.prediction_results` r
WHERE r.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND r.prediction_error >= 8  -- 8+ point errors
ORDER BY r.prediction_error DESC, r.game_date DESC
LIMIT 50;

-- View: ML model performance tracking
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.ml_model_performance` AS
SELECT 
  m.model_id,
  m.model_name,
  m.model_type,
  m.active,
  m.production_predictions,
  m.production_accuracy,
  m.validation_mae,
  m.trained_on_date,
  m.last_retrained,
  m.needs_retraining,
  -- Recent performance from prediction_results
  (
    SELECT AVG(r.prediction_error)
    FROM `nba-props-platform.nba_predictions.prediction_results` r
    JOIN `nba-props-platform.nba_predictions.player_prop_predictions` p 
      ON r.prediction_id = p.prediction_id
    WHERE p.ml_model_id = m.model_id
      AND r.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  ) as last_30_days_mae,
  (
    SELECT COUNT(*)
    FROM `nba-props-platform.nba_predictions.prediction_results` r
    JOIN `nba-props-platform.nba_predictions.player_prop_predictions` p 
      ON r.prediction_id = p.prediction_id
    WHERE p.ml_model_id = m.model_id
      AND r.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  ) as last_30_days_predictions
FROM `nba-props-platform.nba_predictions.ml_models` m
WHERE m.active = TRUE
ORDER BY m.production_accuracy DESC;

-- ============================================================================
-- Usage Notes
-- ============================================================================
-- 
-- PREDICTION WORKFLOW:
-- 1. Daily (6-8 AM): Run all active systems, store predictions in player_prop_predictions
-- 2. Real-time (9 AM - Game Time): Re-run when context/lines change, increment version
-- 3. Post-game (Next Day 2 AM): Compare predictions to results, populate prediction_results
-- 4. Performance Analysis (Next Day 3 AM): Update system_daily_performance
--
-- MULTI-SYSTEM ARCHITECTURE:
-- - Each system creates one prediction per player per game
-- - Multiple systems = multiple predictions for comparison
-- - Champion system designated as primary recommendation
-- - All predictions stored for analysis and A/B testing
--
-- ML INTEGRATION:
-- - ML systems use ml_feature_store for input features
-- - ML models registered in ml_models table
-- - Training history in ml_training_runs
-- - ML predictions link to player_prop_predictions via prediction_id
--
-- VERSIONING:
-- - prediction_version increments when predictions updated
-- - Only latest version has is_active = TRUE
-- - Previous versions kept for audit trail
--
-- RELATED DOCUMENTS:
-- - Document 2: Similarity Matching Engine
-- - Document 3: Composite Factor Calculations
-- - Document 4: Prediction System Framework
-- - Document 11: ML Integration Guide
-- ============================================================================
