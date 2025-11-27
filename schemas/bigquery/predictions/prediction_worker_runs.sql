-- ============================================================================
-- PREDICTION WORKER RUNS (Phase 5 Execution Tracking)
-- ============================================================================
-- Location: nba-stats-scraper/schemas/bigquery/predictions/prediction_worker_runs.sql
-- Purpose: Track Phase 5 prediction worker execution for monitoring, debugging,
--          and pattern support (circuit breakers, data quality tracking)
-- Updated: 2025-11-27 - Added tracing columns (trigger, Cloud Run metadata)
--
-- Usage: bq query --use_legacy_sql=false < schemas/bigquery/predictions/prediction_worker_runs.sql

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
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(), -- When record was created

  -- Trigger tracking (Added 2025-11-27)
  trigger_source STRING,                            -- What triggered: pubsub, scheduler, manual, api
  trigger_message_id STRING,                        -- Pub/Sub message ID for correlation

  -- Cloud Run metadata (Added 2025-11-27)
  cloud_run_service STRING,                         -- K_SERVICE environment variable
  cloud_run_revision STRING,                        -- K_REVISION environment variable

  -- Retry and batch tracking (Added 2025-11-27)
  retry_attempt INT64,                              -- Which retry attempt (1, 2, 3...)
  batch_id STRING                                   -- Batch ID if part of bulk prediction request
)
PARTITION BY DATE(run_date)
CLUSTER BY player_lookup, success, game_date
OPTIONS (
  description = "Phase 5 prediction worker execution logs for monitoring, debugging, and pattern support",
  partition_expiration_days = 365  -- 1 year retention
);

-- ============================================================================
-- VIEWS FOR MONITORING DASHBOARDS
-- ============================================================================

-- Worker performance by player
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.worker_performance_by_player` AS
SELECT
  player_lookup,
  DATE(run_date) as run_date,
  COUNT(*) as total_requests,
  COUNTIF(success) as successful_requests,
  COUNTIF(NOT success) as failed_requests,
  AVG(duration_seconds) as avg_duration_seconds,
  AVG(feature_quality_score) as avg_feature_quality,
  AVG(predictions_generated) as avg_predictions_per_request
FROM `nba-props-platform.nba_predictions.prediction_worker_runs`
WHERE run_date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY player_lookup, DATE(run_date)
ORDER BY run_date DESC, total_requests DESC;

-- System reliability (which prediction systems are failing)
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.system_reliability` AS
SELECT
  system_name,
  DATE(run_date) as run_date,
  COUNT(*) as attempts,
  COUNTIF(success_flag) as successes,
  COUNTIF(NOT success_flag) as failures,
  ROUND(COUNTIF(success_flag) / COUNT(*) * 100, 1) as success_rate_pct
FROM `nba-props-platform.nba_predictions.prediction_worker_runs`,
UNNEST(systems_attempted) as system_name
LEFT JOIN UNNEST(systems_succeeded) as success_system ON system_name = success_system
CROSS JOIN (SELECT system_name = success_system as success_flag)
WHERE run_date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY system_name, DATE(run_date)
ORDER BY run_date DESC, system_name;

-- Active circuit breakers (which systems are currently open)
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.active_circuit_breakers` AS
SELECT
  processor_name as system_name,
  state,
  failure_count,
  last_error_message,
  opened_at,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), opened_at, MINUTE) as minutes_open
FROM `nba-props-platform.nba_orchestration.circuit_breaker_state`
WHERE state IN ('OPEN', 'HALF_OPEN')
  AND processor_name LIKE '%_v1'  -- Phase 5 prediction systems
ORDER BY opened_at DESC;

-- Data quality issues (missing features)
CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.data_quality_issues` AS
SELECT
  DATE(run_date) as run_date,
  COUNTIF(feature_quality_score < 50) as low_quality_count,
  COUNTIF(feature_quality_score >= 50 AND feature_quality_score < 80) as medium_quality_count,
  COUNTIF(feature_quality_score >= 80) as high_quality_count,
  AVG(feature_quality_score) as avg_quality_score,
  APPROX_TOP_COUNT(ARRAY_TO_STRING(missing_features, ', '), 5) as top_missing_features
FROM `nba-props-platform.nba_predictions.prediction_worker_runs`
WHERE run_date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND feature_quality_score IS NOT NULL
GROUP BY DATE(run_date)
ORDER BY run_date DESC;

-- ============================================================================
-- VERIFICATION QUERY
-- ============================================================================
-- Run this to verify the table was created successfully:
--
-- SELECT
--   table_name,
--   ddl
-- FROM `nba-props-platform.nba_predictions.INFORMATION_SCHEMA.TABLES`
-- WHERE table_name = 'prediction_worker_runs';

-- ============================================================================
-- EXAMPLE QUERIES
-- ============================================================================
-- Find failed predictions for a specific player:
-- SELECT run_date, error_message, systems_failed, feature_quality_score
-- FROM `nba-props-platform.nba_predictions.prediction_worker_runs`
-- WHERE player_lookup = 'LeBron James'
--   AND success = FALSE
-- ORDER BY run_date DESC
-- LIMIT 10;
--
-- Identify which systems are most reliable:
-- SELECT
--   system,
--   COUNT(*) as attempts,
--   COUNTIF(system IN UNNEST(systems_succeeded)) as successes,
--   ROUND(COUNTIF(system IN UNNEST(systems_succeeded)) / COUNT(*) * 100, 1) as success_rate_pct
-- FROM `nba-props-platform.nba_predictions.prediction_worker_runs`,
-- UNNEST(systems_attempted) as system
-- WHERE run_date >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
-- GROUP BY system
-- ORDER BY success_rate_pct DESC;
