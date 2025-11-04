-- ============================================================================
-- Table: prediction_systems
-- File: 00_prediction_systems.sql
-- Purpose: Registry of all prediction systems (rule-based, ML, ensemble)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.prediction_systems` (
  -- Identifiers (4 fields)
  system_id STRING NOT NULL,                        -- e.g., "similarity_balanced_v1"
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
  
  -- System Metadata (5 fields) - Added in migration
  system_category STRING,                           -- 'rule_based', 'ml', 'ensemble', 'baseline'
  requires_similarity BOOLEAN DEFAULT FALSE,        -- Needs similarity matching
  requires_ml_model BOOLEAN DEFAULT FALSE,          -- Needs ML model
  min_required_data_points INT64,                   -- Minimum data needed to make prediction
  expected_latency_ms INT64,                        -- Expected prediction time in ms
  
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
-- Initial System Registration
-- ============================================================================

-- System 1: Moving Average Baseline
INSERT INTO `nba-props-platform.nba_predictions.prediction_systems`
(system_id, system_name, system_type, version, active, is_champion, config, 
 system_category, requires_similarity, requires_ml_model, min_required_data_points, expected_latency_ms,
 created_at, created_by, notes)
VALUES (
  'moving_average_baseline',
  'Moving Average Baseline',
  'baseline',
  '1.0.0',
  TRUE,
  FALSE,
  JSON '{"weights": {"last_5": 0.5, "last_10": 0.3, "season": 0.2}, "fatigue_thresholds": {"high": 70, "medium": 50}}',
  'baseline',
  FALSE,
  FALSE,
  5,
  50,
  CURRENT_TIMESTAMP(),
  'system',
  'Simple baseline using weighted recent averages with fatigue/rest adjustments'
)
ON CONFLICT (system_id) DO NOTHING;

-- System 2: Zone Matchup V1
INSERT INTO `nba-props-platform.nba_predictions.prediction_systems`
(system_id, system_name, system_type, version, active, is_champion, config,
 system_category, requires_similarity, requires_ml_model, min_required_data_points, expected_latency_ms,
 created_at, created_by, notes)
VALUES (
  'zone_matchup_v1',
  'Zone Matchup V1',
  'rule_based',
  '1.0.0',
  TRUE,
  FALSE,
  JSON '{"zone_threshold": 0.15, "adjustment_weights": {"pace": 0.8, "usage": 0.6, "zone": 1.2}}',
  'rule_based',
  FALSE,
  FALSE,
  10,
  100,
  CURRENT_TIMESTAMP(),
  'system',
  'Rule-based system using shot zone matchups and pace/usage adjustments'
)
ON CONFLICT (system_id) DO NOTHING;

-- System 3: Similarity Balanced V1
INSERT INTO `nba-props-platform.nba_predictions.prediction_systems`
(system_id, system_name, system_type, version, active, is_champion, config,
 system_category, requires_similarity, requires_ml_model, min_required_data_points, expected_latency_ms,
 created_at, created_by, notes)
VALUES (
  'similarity_balanced_v1',
  'Similarity Balanced V1',
  'similarity_based',
  '1.0.0',
  TRUE,
  FALSE,
  JSON '{"similarity_weights": {"fatigue": 0.25, "opponent_def": 0.20, "pace": 0.15, "zone_matchup": 0.15, "rest": 0.10, "recent_form": 0.10, "usage": 0.05}, "min_similarity": 0.6, "max_matches": 50}',
  'rule_based',
  TRUE,
  FALSE,
  20,
  1500,
  CURRENT_TIMESTAMP(),
  'system',
  'Hybrid system finding similar historical games and averaging results'
)
ON CONFLICT (system_id) DO NOTHING;

-- System 4: XGBoost V1
INSERT INTO `nba-props-platform.nba_predictions.prediction_systems`
(system_id, system_name, system_type, version, active, is_champion, config,
 system_category, requires_similarity, requires_ml_model, min_required_data_points, expected_latency_ms,
 created_at, created_by, notes)
VALUES (
  'xgboost_v1',
  'XGBoost V1',
  'ml',
  '1.0.0',
  TRUE,
  FALSE,
  JSON '{"n_estimators": 100, "max_depth": 6, "learning_rate": 0.1, "objective": "reg:squarederror"}',
  'ml',
  FALSE,
  TRUE,
  10000,
  200,
  CURRENT_TIMESTAMP(),
  'system',
  'ML model using XGBoost with 25 features'
)
ON CONFLICT (system_id) DO NOTHING;

-- System 5: Meta Ensemble V1
INSERT INTO `nba-props-platform.nba_predictions.prediction_systems`
(system_id, system_name, system_type, version, active, is_champion, config,
 system_category, requires_similarity, requires_ml_model, min_required_data_points, expected_latency_ms,
 created_at, created_by, notes)
VALUES (
  'meta_ensemble_v1',
  'Meta Ensemble V1',
  'ensemble',
  '1.0.0',
  TRUE,
  TRUE,  -- This is the champion system
  JSON '{"system_weights": {"moving_average": 0.20, "zone_matchup": 0.25, "similarity": 0.30, "xgboost": 0.25}, "agreement_thresholds": {"high": 2.0, "moderate": 4.0}}',
  'ensemble',
  FALSE,
  FALSE,
  4,
  50,
  CURRENT_TIMESTAMP(),
  'system',
  'Ensemble combining all 4 systems with agreement-based confidence'
)
ON CONFLICT (system_id) DO NOTHING;

-- ============================================================================
-- Usage Examples
-- ============================================================================

-- Get all active systems
-- SELECT system_id, system_name, system_category, is_champion 
-- FROM `nba-props-platform.nba_predictions.prediction_systems`
-- WHERE active = TRUE
-- ORDER BY is_champion DESC, system_category;

-- Get champion system
-- SELECT * FROM `nba-props-platform.nba_predictions.prediction_systems`
-- WHERE is_champion = TRUE AND active = TRUE;

-- Get systems that need ML models
-- SELECT system_id, system_name, model_id, model_file_path
-- FROM `nba-props-platform.nba_predictions.prediction_systems`
-- WHERE requires_ml_model = TRUE AND active = TRUE;
