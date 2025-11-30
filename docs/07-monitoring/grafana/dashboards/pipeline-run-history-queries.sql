-- ============================================================================
-- PIPELINE RUN HISTORY MONITORING DASHBOARD
-- ============================================================================
-- Purpose: BigQuery queries for monitoring processor runs across Phases 2-5
-- Table: nba_reference.processor_run_history (unified logging table)
-- Last Updated: 2025-11-30
-- ============================================================================

-- ============================================================================
-- QUERY 1: Pipeline Health Status (Today)
-- ============================================================================
-- Returns: HEALTHY, DEGRADED, UNHEALTHY, or NO DATA
-- Use for: Main health indicator stat panel
-- ============================================================================

WITH today_stats AS (
  SELECT
    COUNT(*) as total_runs,
    COUNTIF(status = 'success') as success_count,
    COUNTIF(status = 'failed') as failed_count,
    COUNTIF(status = 'running') as running_count
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE data_date = CURRENT_DATE()
)
SELECT
  CASE
    WHEN total_runs = 0 THEN 'NO DATA'
    WHEN failed_count = 0 AND success_count > 0 THEN 'HEALTHY'
    WHEN success_count * 1.0 / NULLIF(success_count + failed_count, 0) >= 0.9 THEN 'HEALTHY'
    WHEN success_count * 1.0 / NULLIF(success_count + failed_count, 0) >= 0.7 THEN 'DEGRADED'
    ELSE 'UNHEALTHY'
  END as health_status
FROM today_stats;


-- ============================================================================
-- QUERY 2: Success Rate (Today)
-- ============================================================================
-- Returns: Percentage of successful runs
-- Use for: Stat panel with thresholds
-- ============================================================================

SELECT
  ROUND(COUNTIF(status = 'success') * 100.0 / NULLIF(COUNTIF(status IN ('success', 'failed')), 0), 1) as success_rate
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date = CURRENT_DATE();


-- ============================================================================
-- QUERY 3: Pipeline Health by Phase (Last 7 Days)
-- ============================================================================
-- Shows breakdown by phase: phase_2_raw, phase_3, phase_4_precompute, phase_5_predictions
-- Use for: Table panel with color-coded success rates
-- ============================================================================

SELECT
  COALESCE(phase, 'unknown') as phase,
  COUNT(*) as total_runs,
  COUNTIF(status = 'success') as success,
  COUNTIF(status = 'failed') as failed,
  COUNTIF(status = 'running') as running,
  ROUND(COUNTIF(status = 'success') * 100.0 / NULLIF(COUNTIF(status IN ('success', 'failed')), 0), 1) as success_rate,
  ROUND(AVG(duration_seconds), 1) as avg_duration_sec
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY phase
ORDER BY phase;


-- ============================================================================
-- QUERY 4: Processor Success Rates (Worst First)
-- ============================================================================
-- Identifies problematic processors
-- Use for: Table panel sorted by success_rate ASC
-- ============================================================================

SELECT
  processor_name,
  phase,
  COUNT(*) as total_runs,
  COUNTIF(status = 'success') as success,
  COUNTIF(status = 'failed') as failed,
  ROUND(COUNTIF(status = 'success') * 100.0 / NULLIF(COUNTIF(status IN ('success', 'failed')), 0), 1) as success_rate,
  ROUND(AVG(duration_seconds), 1) as avg_duration_sec,
  MAX(started_at) as last_run
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY processor_name, phase
HAVING total_runs >= 3
ORDER BY success_rate ASC, total_runs DESC
LIMIT 20;


-- ============================================================================
-- QUERY 5: Success Rate Trend by Phase (Last 30 Days)
-- ============================================================================
-- Time series for trend visualization
-- Use for: Line chart with phase as series
-- ============================================================================

SELECT
  TIMESTAMP(data_date) as time,
  COALESCE(phase, 'unknown') as metric,
  ROUND(COUNTIF(status = 'success') * 100.0 / NULLIF(COUNTIF(status IN ('success', 'failed')), 0), 1) as value
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY data_date, phase
ORDER BY time, phase;


-- ============================================================================
-- QUERY 6: Recent Failed Runs (Last 7 Days)
-- ============================================================================
-- Shows failed processor runs with error details
-- Use for: Table panel sorted by started_at DESC
-- ============================================================================

SELECT
  started_at,
  processor_name,
  phase,
  data_date,
  status,
  ROUND(duration_seconds, 1) as duration_sec,
  trigger_source,
  SUBSTR(COALESCE(JSON_VALUE(errors, '$[0].error_message'), errors, 'N/A'), 1, 100) as error_preview
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE status = 'failed'
  AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY started_at DESC
LIMIT 25;


-- ============================================================================
-- QUERY 7: Processing Duration by Processor
-- ============================================================================
-- Identifies slow processors
-- Use for: Bar chart
-- ============================================================================

SELECT
  processor_name,
  ROUND(AVG(duration_seconds), 1) as avg_duration,
  ROUND(APPROX_QUANTILES(duration_seconds, 100)[OFFSET(95)], 1) as p95_duration
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE status = 'success'
  AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND duration_seconds IS NOT NULL
GROUP BY processor_name
HAVING COUNT(*) >= 3
ORDER BY avg_duration DESC
LIMIT 15;


-- ============================================================================
-- QUERY 8: Phase 5 Prediction Coordinator Runs
-- ============================================================================
-- Tracks prediction batch executions
-- Use for: Table panel
-- ============================================================================

SELECT
  started_at,
  data_date as game_date,
  status,
  records_processed as predictions,
  ROUND(duration_seconds, 1) as duration_sec,
  trigger_source,
  JSON_VALUE(summary, '$.correlation_id') as correlation_id
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE phase = 'phase_5_predictions'
  AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
ORDER BY started_at DESC
LIMIT 20;


-- ============================================================================
-- QUERY 9: Daily Run Volume by Phase (Last 30 Days)
-- ============================================================================
-- Time series of run counts
-- Use for: Stacked bar chart
-- ============================================================================

SELECT
  TIMESTAMP(data_date) as time,
  COALESCE(phase, 'unknown') as metric,
  COUNT(*) as value
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY data_date, phase
ORDER BY time, phase;


-- ============================================================================
-- QUERY 10: Today's Processor Runs (Latest First)
-- ============================================================================
-- Real-time view of today's processing
-- Use for: Table panel with status color coding
-- ============================================================================

SELECT
  started_at,
  processor_name,
  phase,
  status,
  records_processed,
  ROUND(duration_seconds, 1) as duration_sec,
  trigger_source,
  parent_processor
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date = CURRENT_DATE()
ORDER BY started_at DESC
LIMIT 50;


-- ============================================================================
-- QUERY 11: End-to-End Pipeline Tracing (by correlation_id)
-- ============================================================================
-- Trace a single pipeline execution across all phases
-- Replace 'YOUR_CORRELATION_ID' with actual ID
-- ============================================================================

SELECT
  started_at,
  processor_name,
  phase,
  status,
  records_processed,
  ROUND(duration_seconds, 1) as duration_sec,
  trigger_source,
  parent_processor
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE JSON_VALUE(summary, '$.correlation_id') = 'YOUR_CORRELATION_ID'
   OR run_id LIKE '%YOUR_CORRELATION_ID%'
ORDER BY started_at;


-- ============================================================================
-- QUERY 12: Stale "Running" Processors (Potential Issues)
-- ============================================================================
-- Finds processors stuck in 'running' status for >1 hour
-- Use for: Alert query
-- ============================================================================

SELECT
  started_at,
  processor_name,
  phase,
  data_date,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) as minutes_running
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE status = 'running'
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) > 60
ORDER BY started_at;


-- ============================================================================
-- GRAFANA ALERT CONFIGURATIONS
-- ============================================================================
--
-- Alert 1: Pipeline Unhealthy
--   Query: Use Query 1, alert if health_status = 'UNHEALTHY' for > 15 min
--   Severity: Critical
--
-- Alert 2: High Failure Rate
--   Query: Use Query 2, alert if success_rate < 80% for > 30 min
--   Severity: Warning
--
-- Alert 3: Stale Running Processors
--   Query: Use Query 12, alert if any rows returned
--   Severity: Critical
--
-- Alert 4: Phase 5 Predictions Failed
--   Query: Use Query 8 filtered by status = 'failed', alert if count > 0
--   Severity: Warning
--
-- ============================================================================


-- ============================================================================
-- EXPECTED PATTERNS
-- ============================================================================
--
-- Normal Day (with games):
--   - Phase 2: 20-50 runs (one per scraper output file)
--   - Phase 3: 5-10 runs (analytics processors)
--   - Phase 4: 5-10 runs (precompute processors)
--   - Phase 5: 1-3 runs (prediction batches)
--   - Overall success rate: >95%
--
-- Off-Season / No Games:
--   - Minimal runs across all phases
--   - "NO DATA" health status is expected
--
-- Warning Signs:
--   - Success rate < 90%
--   - Any processor stuck in 'running' > 1 hour
--   - Same processor failing repeatedly
--   - Phase 5 failing (no predictions generated)
--
-- ============================================================================


-- ============================================================================
-- QUERY 13: End-to-End Pipeline Latency (Phase 2 → Phase 5)
-- ============================================================================
-- Shows time from first Phase 2 run to Phase 5 completion for each date
-- Helps identify stalled pipelines and latency issues
-- ============================================================================

WITH phase_times AS (
  SELECT
    data_date,
    phase,
    MIN(started_at) as first_start,
    MAX(processed_at) as last_complete,
    COUNTIF(status = 'success') as success_count,
    COUNTIF(status = 'failed') as failed_count
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  GROUP BY data_date, phase
),
phase2 AS (
  SELECT data_date, first_start as phase2_start, last_complete as phase2_complete
  FROM phase_times WHERE phase = 'phase_2_raw'
),
phase5 AS (
  SELECT data_date, first_start as phase5_start, last_complete as phase5_complete,
         success_count, failed_count
  FROM phase_times WHERE phase = 'phase_5_predictions'
)
SELECT
  p2.data_date,
  p2.phase2_start,
  p2.phase2_complete,
  p5.phase5_start,
  p5.phase5_complete,
  ROUND(TIMESTAMP_DIFF(COALESCE(p5.phase5_complete, CURRENT_TIMESTAMP()), p2.phase2_start, SECOND) / 60.0, 1) as pipeline_latency_min,
  CASE
    WHEN p5.success_count > 0 THEN 'COMPLETE'
    WHEN p5.failed_count > 0 THEN 'FAILED'
    ELSE 'PENDING'
  END as phase5_status
FROM phase2 p2
LEFT JOIN phase5 p5 ON p2.data_date = p5.data_date
ORDER BY p2.data_date DESC;


-- ============================================================================
-- QUERY 14: Pipeline Flow Trace (Chronological for Today)
-- ============================================================================
-- Shows all processor runs for today in chronological order
-- Useful for understanding pipeline flow and debugging
-- ============================================================================

SELECT
  started_at,
  phase,
  processor_name,
  status,
  records_processed,
  ROUND(duration_seconds, 1) as duration_sec,
  trigger_source,
  parent_processor,
  JSON_VALUE(summary, '$.correlation_id') as correlation_id
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date = CURRENT_DATE()
ORDER BY started_at ASC
LIMIT 100;


-- ============================================================================
-- QUERY 15: Trace by Correlation ID
-- ============================================================================
-- Find all processor runs associated with a specific correlation_id
-- Replace 'YOUR_CORRELATION_ID' with the actual correlation ID
-- ============================================================================

SELECT
  started_at,
  phase,
  processor_name,
  status,
  records_processed,
  ROUND(duration_seconds, 1) as duration_sec,
  data_date
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE JSON_VALUE(summary, '$.correlation_id') = 'YOUR_CORRELATION_ID'
ORDER BY started_at ASC;


-- ============================================================================
-- QUERY 16: Stalled Pipeline Detection
-- ============================================================================
-- Find dates where Phase 2 ran but Phase 5 never completed
-- Indicates potential pipeline failures
-- ============================================================================

WITH phase2_dates AS (
  SELECT DISTINCT data_date
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE phase = 'phase_2_raw'
    AND status = 'success'
    AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
),
phase5_dates AS (
  SELECT DISTINCT data_date
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE phase = 'phase_5_predictions'
    AND status = 'success'
    AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
)
SELECT
  p2.data_date,
  'Phase 2 complete but Phase 5 missing' as issue
FROM phase2_dates p2
LEFT JOIN phase5_dates p5 ON p2.data_date = p5.data_date
WHERE p5.data_date IS NULL
ORDER BY p2.data_date DESC;
