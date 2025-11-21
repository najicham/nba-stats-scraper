-- ============================================================================
-- MIGRATION: Create prediction_worker_runs table
-- Phase 5 Worker Execution Tracking
-- ============================================================================
-- Purpose: Track Phase 5 prediction worker execution for monitoring, debugging,
--          and pattern support (circuit breakers, data quality tracking)
--
-- Usage: bq query --use_legacy_sql=false < monitoring/schemas/create_prediction_worker_runs_table.sql

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.prediction_worker_runs` (
  -- Execution identifiers
  request_id STRING NOT NULL,                       -- Unique request identifier (UUID)
  worker_id STRING,                                 -- Which worker instance handled this request
  run_date TIMESTAMP NOT NULL,                      -- When worker was invoked

  -- Request details (what we're predicting)
  player_lookup STRING NOT NULL,                    -- Player being predicted (e.g., "LeBron James")
  universal_player_id STRING,                       -- Universal player ID from registry
  game_date DATE NOT NULL,                          -- Game date
  game_id STRING,                                   -- Game ID (e.g., "20251108_LAL_GSW")
  line_values_requested ARRAY<FLOAT64>,            -- Betting lines requested (e.g., [23.5, 24.5, 25.5])

  -- Execution results
  success BOOLEAN NOT NULL,                         -- Overall success (at least 1 system succeeded)
  duration_seconds FLOAT64,                         -- Total execution time
  predictions_generated INT64,                      -- How many predictions created (systems × lines)

  -- Pattern support (Pattern #1: Smart Skip, Pattern #3: Early Exit)
  skip_reason STRING,                               -- Why skipped (e.g., 'no_features', 'circuit_open', 'player_inactive')

  -- System-specific results (which prediction systems ran)
  systems_attempted ARRAY<STRING>,                  -- Systems we tried (e.g., ['moving_average', 'zone_matchup', 'similarity', 'xgboost', 'ensemble'])
  systems_succeeded ARRAY<STRING>,                  -- Systems that succeeded
  systems_failed ARRAY<STRING>,                     -- Systems that failed
  system_errors JSON,                               -- Detailed errors by system: {"xgboost": "Model API timeout"}

  -- Data quality (features from Phase 4)
  feature_quality_score FLOAT64,                    -- Feature completeness score (0-100)
  missing_features ARRAY<STRING>,                   -- Which features were missing
  feature_load_time_seconds FLOAT64,                -- Time to load features from BigQuery

  -- Historical data (for similarity system)
  historical_games_count INT64,                     -- How many historical games loaded
  historical_load_time_seconds FLOAT64,             -- Time to load historical games

  -- Error tracking
  error_message STRING,                             -- Primary error message (if failure)
  error_system STRING,                              -- Which prediction system caused failure
  error_type STRING,                                -- Error classification (e.g., "FeatureLoadError", "ModelError", "CircuitOpen")

  -- Performance breakdown
  data_load_seconds FLOAT64,                        -- Time loading all data
  prediction_compute_seconds FLOAT64,               -- Time computing predictions
  write_bigquery_seconds FLOAT64,                   -- Time writing to BigQuery
  pubsub_publish_seconds FLOAT64,                   -- Time publishing completion event

  -- Circuit breaker reference (Pattern #5)
  circuit_breaker_triggered BOOLEAN DEFAULT FALSE,  -- TRUE if any system circuit breaker opened
  circuits_opened ARRAY<STRING>,                    -- Which systems opened circuit (e.g., ['xgboost'])

  -- Metadata
  worker_version STRING,                            -- Worker code version
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()  -- When record was created
)
PARTITION BY DATE(run_date)
CLUSTER BY player_lookup, success, game_date
OPTIONS (
  description = "Phase 5 prediction worker execution logs for monitoring, debugging, and pattern support",
  partition_expiration_days = 365  -- 1 year retention
);

-- ============================================================================
-- VERIFY
-- ============================================================================
SELECT
  table_name,
  CONCAT('Created at: ', CAST(creation_time AS STRING)) as status
FROM `nba-props-platform.nba_predictions.INFORMATION_SCHEMA.TABLES`
WHERE table_name = 'prediction_worker_runs';
