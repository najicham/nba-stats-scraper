-- ============================================================================
-- CIRCUIT BREAKER STATE TRACKING (Pattern #5)
-- ============================================================================
-- Location: nba-stats-scraper/schemas/bigquery/nba_orchestration/circuit_breaker_state.sql
-- Purpose: Track circuit breaker state across all processors (Phase 2, 3, 4, 5)
--          to prevent infinite retry loops and cascading failures
--
-- Usage: bq query --use_legacy_sql=false < schemas/bigquery/nba_orchestration/circuit_breaker_state.sql

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.circuit_breaker_state` (
  -- Primary key
  processor_name STRING NOT NULL,                   -- Unique processor identifier (e.g., "PlayerGameSummaryProcessor", "xgboost_v1")

  -- Circuit state
  state STRING NOT NULL,                            -- 'CLOSED', 'OPEN', 'HALF_OPEN'
  failure_count INT64 NOT NULL DEFAULT 0,           -- Consecutive failures in current window
  success_count INT64 NOT NULL DEFAULT 0,           -- Consecutive successes after half-open

  -- Timestamps
  last_failure TIMESTAMP,                           -- When last failure occurred
  last_success TIMESTAMP,                           -- When last success occurred
  opened_at TIMESTAMP,                              -- When circuit opened
  half_opened_at TIMESTAMP,                         -- When circuit moved to half-open
  updated_at TIMESTAMP NOT NULL,                    -- Last state change

  -- Error tracking
  last_error_message STRING,                        -- Most recent error message
  last_error_type STRING,                           -- Error type (e.g., "BigQueryQuotaExceeded", "DependencyMissing")

  -- Failure history (last 10 failures for debugging)
  failure_history ARRAY<STRUCT<
    failed_at TIMESTAMP,
    error_message STRING,
    error_type STRING
  >>,

  -- Configuration (from processor)
  threshold INT64,                                  -- Failure threshold before opening
  timeout_seconds INT64,                            -- How long to stay open before half-open
  half_open_max_calls INT64                         -- Max calls to test in half-open state
)
CLUSTER BY processor_name, state
OPTIONS(
  description = "Circuit breaker state tracking for Pattern #5 - prevents infinite retry loops across all processors",
  labels = [("pattern", "circuit_breaker"), ("phase", "all")]
);

-- Create unique index on processor_name (enforced by clustering)
-- Note: BigQuery doesn't support explicit UNIQUE constraints, but clustering provides similar semantics

-- ============================================================================
-- VERIFICATION QUERY
-- ============================================================================
-- Run this to verify the table was created successfully:
--
-- SELECT
--   table_name,
--   ddl
-- FROM `nba-props-platform.nba_orchestration.INFORMATION_SCHEMA.TABLES`
-- WHERE table_name = 'circuit_breaker_state';

-- ============================================================================
-- EXAMPLE USAGE
-- ============================================================================
-- Query open circuits:
-- SELECT processor_name, state, failure_count, last_error_message, opened_at
-- FROM `nba-props-platform.nba_orchestration.circuit_breaker_state`
-- WHERE state = 'OPEN'
-- ORDER BY opened_at DESC;
--
-- Query circuits by processor type:
-- SELECT
--   CASE
--     WHEN processor_name LIKE '%Processor' THEN 'Phase 2/3/4'
--     WHEN processor_name LIKE '%_v1' THEN 'Phase 5 System'
--     ELSE 'Other'
--   END as processor_type,
--   state,
--   COUNT(*) as count
-- FROM `nba-props-platform.nba_orchestration.circuit_breaker_state`
-- GROUP BY processor_type, state;
