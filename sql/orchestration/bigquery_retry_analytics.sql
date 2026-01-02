-- BigQuery Retry Analytics Queries
--
-- Queries to analyze BigQuery serialization conflict retry patterns and success rates.
-- Can be used with either:
--   1. nba_orchestration.bigquery_retry_metrics table (if populated)
--   2. Cloud Logging queries (see: docs/monitoring/bigquery-retry-cloud-logging-queries.md)
--
-- Quick Start:
--   - View overall success rate: Query #1
--   - Find problem tables: Query #2
--   - Analyze retry patterns by time: Query #3

-- =============================================================================
-- QUERY 1: Overall Retry Success Rate (Last 7 Days)
-- =============================================================================
-- Shows how often retries successfully resolve conflicts vs exhaust retries

SELECT
  DATE(timestamp) as date,
  COUNTIF(event_type = 'bigquery_serialization_conflict') as conflicts_detected,
  COUNTIF(event_type = 'bigquery_retry_success') as operations_succeeded,
  COUNTIF(event_type = 'bigquery_retry_exhausted') as retries_exhausted,
  SAFE_DIVIDE(
    COUNTIF(event_type = 'bigquery_retry_success'),
    COUNTIF(event_type = 'bigquery_serialization_conflict')
  ) * 100 as success_rate_percent
FROM `nba-props-platform.nba_orchestration.bigquery_retry_metrics`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY date
ORDER BY date DESC;

-- =============================================================================
-- QUERY 2: Tables with Most Conflicts (Last 7 Days)
-- =============================================================================
-- Identifies which tables are experiencing the most serialization conflicts

SELECT
  table_name,
  COUNTIF(event_type = 'bigquery_serialization_conflict') as total_conflicts,
  COUNTIF(event_type = 'bigquery_retry_success') as successful_retries,
  COUNTIF(event_type = 'bigquery_retry_exhausted') as failed_retries,
  SAFE_DIVIDE(
    COUNTIF(event_type = 'bigquery_retry_success'),
    COUNTIF(event_type = 'bigquery_serialization_conflict')
  ) * 100 as success_rate_percent,
  AVG(IF(event_type = 'bigquery_retry_success', duration_ms, NULL)) as avg_duration_ms
FROM `nba-props-platform.nba_orchestration.bigquery_retry_metrics`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND table_name IS NOT NULL
GROUP BY table_name
ORDER BY total_conflicts DESC
LIMIT 20;

-- =============================================================================
-- QUERY 3: Retry Patterns by Hour of Day
-- =============================================================================
-- Shows when conflicts are most likely to occur (helps identify peak concurrency times)

SELECT
  EXTRACT(HOUR FROM timestamp) as hour_utc,
  COUNTIF(event_type = 'bigquery_serialization_conflict') as conflicts,
  COUNTIF(event_type = 'bigquery_retry_success') as successes,
  COUNTIF(event_type = 'bigquery_retry_exhausted') as exhausted,
  SAFE_DIVIDE(
    COUNTIF(event_type = 'bigquery_retry_success'),
    COUNTIF(event_type = 'bigquery_serialization_conflict')
  ) * 100 as success_rate_percent
FROM `nba-props-platform.nba_orchestration.bigquery_retry_metrics`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY hour_utc
ORDER BY hour_utc;

-- =============================================================================
-- QUERY 4: Recent Retry Exhaustions (Last 24 Hours)
-- =============================================================================
-- Lists operations that failed even after retries (need investigation)

SELECT
  timestamp,
  table_name,
  function_name,
  processor_name,
  duration_ms,
  error_message
FROM `nba-props-platform.nba_orchestration.bigquery_retry_metrics`
WHERE event_type = 'bigquery_retry_exhausted'
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY timestamp DESC;

-- =============================================================================
-- QUERY 5: Retry Performance Metrics
-- =============================================================================
-- Analyzes how long operations take when retries are needed vs no retries

WITH retry_events AS (
  SELECT
    table_name,
    timestamp,
    duration_ms,
    event_type,
    -- Group events within 10 seconds as same operation
    TIMESTAMP_DIFF(
      timestamp,
      LAG(timestamp) OVER (PARTITION BY table_name ORDER BY timestamp),
      SECOND
    ) > 10 as is_new_operation
  FROM `nba-props-platform.nba_orchestration.bigquery_retry_metrics`
  WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
)
SELECT
  table_name,
  AVG(IF(event_type = 'bigquery_retry_success', duration_ms, NULL)) as avg_duration_with_retry_ms,
  MAX(IF(event_type = 'bigquery_retry_success', duration_ms, NULL)) as max_duration_with_retry_ms,
  COUNT(DISTINCT IF(event_type = 'bigquery_retry_success', timestamp, NULL)) as operations_with_retry,
  COUNT(DISTINCT IF(event_type = 'bigquery_serialization_conflict', timestamp, NULL)) as total_conflicts
FROM retry_events
WHERE table_name IS NOT NULL
GROUP BY table_name
HAVING operations_with_retry > 0
ORDER BY total_conflicts DESC;

-- =============================================================================
-- QUERY 6: Daily Summary View
-- =============================================================================
-- Pre-aggregated daily summary (uses the view created in schema)

SELECT *
FROM `nba-props-platform.nba_orchestration.bigquery_retry_summary`
WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY date DESC, event_count DESC;

-- =============================================================================
-- QUERY 7: Conflict Frequency by Service
-- =============================================================================
-- Shows which Cloud Run services are experiencing conflicts

SELECT
  service_name,
  table_name,
  COUNTIF(event_type = 'bigquery_serialization_conflict') as conflicts,
  COUNTIF(event_type = 'bigquery_retry_success') as successes,
  SAFE_DIVIDE(
    COUNTIF(event_type = 'bigquery_retry_success'),
    COUNTIF(event_type = 'bigquery_serialization_conflict')
  ) * 100 as success_rate_percent
FROM `nba-props-platform.nba_orchestration.bigquery_retry_metrics`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND service_name IS NOT NULL
GROUP BY service_name, table_name
ORDER BY conflicts DESC;

-- =============================================================================
-- QUERY 8: Retry Success Rate Trend (Last 30 Days)
-- =============================================================================
-- 7-day rolling average of retry success rate

WITH daily_stats AS (
  SELECT
    DATE(timestamp) as date,
    COUNTIF(event_type = 'bigquery_serialization_conflict') as conflicts,
    COUNTIF(event_type = 'bigquery_retry_success') as successes
  FROM `nba-props-platform.nba_orchestration.bigquery_retry_metrics`
  WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  GROUP BY date
)
SELECT
  date,
  conflicts,
  successes,
  SAFE_DIVIDE(successes, conflicts) * 100 as daily_success_rate_percent,
  AVG(SAFE_DIVIDE(successes, conflicts) * 100)
    OVER (ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) as rolling_7day_success_rate_percent
FROM daily_stats
WHERE conflicts > 0
ORDER BY date DESC;

-- =============================================================================
-- MONITORING ALERTS
-- =============================================================================
-- Use these queries for monitoring dashboards and alerts

-- Alert 1: Low Success Rate (< 80%)
-- Run every hour, alert if success rate drops below 80%
SELECT
  'LOW_RETRY_SUCCESS_RATE' as alert_type,
  COUNTIF(event_type = 'bigquery_serialization_conflict') as conflicts,
  COUNTIF(event_type = 'bigquery_retry_success') as successes,
  SAFE_DIVIDE(
    COUNTIF(event_type = 'bigquery_retry_success'),
    COUNTIF(event_type = 'bigquery_serialization_conflict')
  ) * 100 as success_rate_percent
FROM `nba-props-platform.nba_orchestration.bigquery_retry_metrics`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
HAVING success_rate_percent < 80 AND conflicts > 5;

-- Alert 2: High Conflict Volume
-- Run every hour, alert if more than 50 conflicts in an hour
SELECT
  'HIGH_CONFLICT_VOLUME' as alert_type,
  table_name,
  COUNTIF(event_type = 'bigquery_serialization_conflict') as conflicts_last_hour
FROM `nba-props-platform.nba_orchestration.bigquery_retry_metrics`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
GROUP BY table_name
HAVING conflicts_last_hour > 50
ORDER BY conflicts_last_hour DESC;

-- Alert 3: Retry Exhaustion Pattern
-- Run every hour, alert if retries are being exhausted (indicates need for Phase 2: distributed locking)
SELECT
  'RETRY_EXHAUSTION_DETECTED' as alert_type,
  table_name,
  COUNTIF(event_type = 'bigquery_retry_exhausted') as exhausted_count,
  ARRAY_AGG(error_message LIMIT 3) as sample_errors
FROM `nba-props-platform.nba_orchestration.bigquery_retry_metrics`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  AND event_type = 'bigquery_retry_exhausted'
GROUP BY table_name
HAVING exhausted_count > 0
ORDER BY exhausted_count DESC;
