-- BigQuery Retry Metrics Table
--
-- Tracks BigQuery serialization conflict retry attempts, successes, and failures.
-- This table can be populated via:
--   1. Cloud Logging export (log sink) - Recommended for automatic collection
--   2. Direct inserts from code - For more control
--
-- Usage:
--   bq mk --table nba-props-platform:nba_orchestration.bigquery_retry_metrics sql/orchestration/bigquery_retry_metrics_schema.sql
--
-- Analytics queries are in: sql/orchestration/bigquery_retry_analytics.sql

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.bigquery_retry_metrics` (
  -- Event metadata
  timestamp TIMESTAMP NOT NULL OPTIONS(description="When the event occurred (UTC)"),
  event_type STRING NOT NULL OPTIONS(description="Type of event: bigquery_serialization_conflict, bigquery_retry_success, bigquery_retry_exhausted, bigquery_operation_failed"),

  -- Operation context
  function_name STRING OPTIONS(description="Name of the function that was executing"),
  processor_name STRING OPTIONS(description="Name of the processor (if applicable)"),
  service_name STRING OPTIONS(description="Cloud Run service name (e.g., nba-phase2-raw-processors)"),

  -- BigQuery table info
  table_name STRING OPTIONS(description="BigQuery table that had the conflict (e.g., nba_raw.br_rosters_current)"),
  dataset STRING OPTIONS(description="BigQuery dataset (extracted from table_name)"),
  table STRING(description="BigQuery table (extracted from table_name)"),

  -- Performance metrics
  duration_ms INT64 OPTIONS(description="Operation duration in milliseconds"),

  -- Outcome
  success BOOLEAN OPTIONS(description="Whether the operation ultimately succeeded (after retries)"),
  retry_triggered BOOLEAN OPTIONS(description="Whether retry logic was triggered"),

  -- Error details
  error_message STRING OPTIONS(description="Truncated error message (first 200 chars)"),

  -- Additional context
  game_date DATE OPTIONS(description="Game date if applicable to the operation"),
  metadata JSON OPTIONS(description="Additional structured metadata")
)
PARTITION BY DATE(timestamp)
CLUSTER BY event_type, table_name, service_name
OPTIONS(
  description="Tracks BigQuery serialization conflict retry metrics for monitoring and analysis",
  labels=[("purpose", "observability"), ("category", "retry_metrics")]
);

-- Create a view for easy querying
CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.bigquery_retry_summary` AS
SELECT
  DATE(timestamp) as date,
  event_type,
  table_name,
  COUNT(*) as event_count,
  COUNTIF(success) as success_count,
  COUNTIF(NOT success) as failure_count,
  AVG(duration_ms) as avg_duration_ms,
  MAX(duration_ms) as max_duration_ms,
  MIN(duration_ms) as min_duration_ms
FROM `nba-props-platform.nba_orchestration.bigquery_retry_metrics`
GROUP BY date, event_type, table_name
ORDER BY date DESC, event_count DESC;
