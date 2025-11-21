-- ============================================================================
-- MIGRATION: Create circuit_breaker_state table
-- Pattern #5 (Circuit Breaker)
-- ============================================================================
-- Purpose: Track circuit breaker state across all processors (Phase 2, 3, 4, 5)
--          to prevent infinite retry loops and cascading failures
--
-- Usage: bq query --use_legacy_sql=false < monitoring/schemas/circuit_breaker_state_table.sql

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.circuit_breaker_state` (
  -- Primary key
  processor_name STRING NOT NULL,                   -- Unique processor identifier (e.g., "PlayerGameSummaryProcessor", "xgboost_v1")

  -- Circuit state
  state STRING NOT NULL,                            -- 'CLOSED', 'OPEN', 'HALF_OPEN'
  failure_count INT64,                              -- Consecutive failures in current window
  success_count INT64,                              -- Consecutive successes after half-open

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

-- Note: BigQuery doesn't support explicit UNIQUE constraints or indexes
-- Clustering on processor_name provides efficient lookups

-- ============================================================================
-- VERIFY
-- ============================================================================
SELECT
  table_name,
  CONCAT('Created at: ', CAST(creation_time AS STRING)) as status
FROM `nba-props-platform.nba_orchestration.INFORMATION_SCHEMA.TABLES`
WHERE table_name = 'circuit_breaker_state';
