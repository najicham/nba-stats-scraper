-- ============================================================================
-- SERVICE ERRORS TABLE - CENTRALIZED ERROR LOGGING
-- ============================================================================
-- Location: nba-stats-scraper/schemas/bigquery/nba_orchestration/service_errors.sql
-- Purpose: Centralized error persistence for all 53+ services (Cloud Run + Cloud Functions)
--          across all phases (Phase 2, 3, 4, 5) and orchestration components
--
-- Context: Part of validation-coverage-improvements project
--          Investigation findings: docs/08-projects/current/validation-coverage-improvements/05-INVESTIGATION-FINDINGS.md
--
-- Usage: bq query --use_legacy_sql=false < schemas/bigquery/nba_orchestration/service_errors.sql
--
-- Design:
-- - Streaming insert for immediate visibility (low volume: 10-42 errors/day normal, 220-450 during incidents)
-- - Hash-based deduplication via error_id (service + error_type + message + timestamp_minute)
-- - Partitioned by error_timestamp for cost-effective queries
-- - Clustered by service_name, error_category, severity for fast filtering
-- - 90-day retention (minimal cost: <$0.01/month)
--
-- Integration Points:
-- - TransformProcessorBase.report_error() - Phase 3 & 4 processors
-- - Cloud Function decorator - All functions
-- - processor_alerting.send_error_alert() - All processors

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.service_errors` (
  -- Primary identification
  error_id STRING NOT NULL,                             -- Hash(service + error_type + message + timestamp_minute) for deduplication
  service_name STRING NOT NULL,                         -- Service name (e.g., "PlayerGameSummaryProcessor", "phase3_to_phase4")

  -- Temporal tracking
  error_timestamp TIMESTAMP NOT NULL,                   -- When error occurred
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),     -- When record was inserted

  -- Error classification
  error_type STRING NOT NULL,                           -- Exception type (e.g., "ValueError", "BigQueryError", "TimeoutError")
  error_category STRING NOT NULL,                       -- From failure_categorization.py: no_data_available, upstream_failure, processing_error, timeout, configuration_error, unknown
  severity STRING NOT NULL,                             -- 'critical', 'warning', 'info' (derived from error_category)

  -- Error details
  error_message STRING NOT NULL,                        -- Human-readable error message
  stack_trace STRING,                                   -- Full stack trace for debugging

  -- Context tracking
  game_date DATE,                                       -- Game date being processed (if applicable)
  processor_name STRING,                                -- Specific processor name (for Phase 3/4)
  phase STRING,                                         -- Pipeline phase (e.g., "phase_3_analytics", "phase_4_precompute")
  correlation_id STRING,                                -- Correlation ID for distributed tracing

  -- Recovery tracking
  recovery_attempted BOOLEAN,                           -- Whether automatic recovery was attempted
  recovery_successful BOOLEAN                           -- Whether recovery succeeded
)
PARTITION BY DATE(error_timestamp)
CLUSTER BY service_name, error_category, severity
OPTIONS(
  description = "Centralized error logging for all services - Phase 2, 3, 4, 5 processors and orchestration functions",
  labels = [("project", "validation_coverage_improvements"), ("phase", "all"), ("priority", "p1")]
);

-- ============================================================================
-- VERIFICATION QUERY
-- ============================================================================
-- Run this to verify the table was created successfully:
--
-- SELECT
--   table_name,
--   ddl
-- FROM `nba-props-platform.nba_orchestration.INFORMATION_SCHEMA.TABLES`
-- WHERE table_name = 'service_errors';

-- ============================================================================
-- EXAMPLE QUERIES
-- ============================================================================

-- Query 1: Recent processing errors (alertable)
-- SELECT
--   service_name,
--   error_category,
--   severity,
--   error_message,
--   error_timestamp,
--   COUNT(*) as occurrences
-- FROM `nba-props-platform.nba_orchestration.service_errors`
-- WHERE error_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
--   AND error_category IN ('processing_error', 'configuration_error', 'unknown')
-- GROUP BY service_name, error_category, severity, error_message, error_timestamp
-- ORDER BY error_timestamp DESC;

-- Query 2: Error volume by service (last 24 hours)
-- SELECT
--   service_name,
--   error_category,
--   COUNT(*) as error_count,
--   COUNT(DISTINCT error_type) as unique_error_types
-- FROM `nba-props-platform.nba_orchestration.service_errors`
-- WHERE error_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
-- GROUP BY service_name, error_category
-- ORDER BY error_count DESC;

-- Query 3: Burst detection (>10 errors in 5 minutes)
-- SELECT
--   service_name,
--   TIMESTAMP_TRUNC(error_timestamp, MINUTE, 'America/Los_Angeles') as minute_bucket,
--   COUNT(*) as errors_per_minute
-- FROM `nba-props-platform.nba_orchestration.service_errors`
-- WHERE error_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
-- GROUP BY service_name, minute_bucket
-- HAVING errors_per_minute >= 10
-- ORDER BY minute_bucket DESC, errors_per_minute DESC;

-- Query 4: Novel errors (new error_type not seen in 7 days)
-- WITH recent_errors AS (
--   SELECT DISTINCT error_type
--   FROM `nba-props-platform.nba_orchestration.service_errors`
--   WHERE error_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
-- ),
-- historical_errors AS (
--   SELECT DISTINCT error_type
--   FROM `nba-props-platform.nba_orchestration.service_errors`
--   WHERE error_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
--     AND error_timestamp < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
-- )
-- SELECT
--   r.error_type,
--   s.service_name,
--   s.error_message,
--   s.error_timestamp
-- FROM recent_errors r
-- LEFT JOIN historical_errors h ON r.error_type = h.error_type
-- JOIN `nba-props-platform.nba_orchestration.service_errors` s
--   ON r.error_type = s.error_type
--   AND s.error_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
-- WHERE h.error_type IS NULL
-- ORDER BY s.error_timestamp DESC;

-- Query 5: Recovery success rate
-- SELECT
--   service_name,
--   error_category,
--   COUNT(*) as total_errors,
--   COUNTIF(recovery_attempted) as recovery_attempts,
--   COUNTIF(recovery_successful) as recovery_successes,
--   SAFE_DIVIDE(COUNTIF(recovery_successful), COUNTIF(recovery_attempted)) * 100 as recovery_rate_pct
-- FROM `nba-props-platform.nba_orchestration.service_errors`
-- WHERE error_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
-- GROUP BY service_name, error_category
-- HAVING recovery_attempts > 0
-- ORDER BY recovery_rate_pct ASC;

-- Query 6: Error timeline for specific game_date
-- SELECT
--   service_name,
--   phase,
--   error_category,
--   error_message,
--   error_timestamp
-- FROM `nba-props-platform.nba_orchestration.service_errors`
-- WHERE game_date = '2024-11-15'
-- ORDER BY error_timestamp ASC;

-- ============================================================================
-- RECOMMENDED MONITORING ALERTS
-- ============================================================================
-- 1. Burst Alert: >10 errors from same service in 5 minutes
-- 2. Novel Error Alert: New error_type not seen in 7 days
-- 3. Recurring Error Alert: Same error >5 times in 1 hour
-- 4. Service Down Alert: >50% of services reporting errors
-- 5. Phase Failure Alert: All processors in a phase failing
-- 6. Critical Error Alert: Any error_category = 'processing_error' or 'configuration_error'
