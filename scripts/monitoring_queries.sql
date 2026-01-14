-- Processor Run History Monitoring Queries
-- Project: nba-props-platform
-- Dataset: nba_reference
-- Table: processor_run_history
-- Created: 2026-01-13

-- =============================================================================
-- SECTION 1: REAL-TIME ALERTS
-- =============================================================================

-- ALERT 1: Stuck Processors (>15 minutes in "running" state)
-- Severity: P0
-- Schedule: Every 5 minutes
-- Action: Send Slack alert + consider killing process

SELECT
  processor_name,
  run_id,
  phase,
  started_at,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) as minutes_stuck,
  execution_host,
  cloud_run_service
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE status = 'running'
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, MINUTE) > 15
ORDER BY minutes_stuck DESC;


-- ALERT 2: Recent Failures with Context (Last Hour)
-- Severity: P1
-- Schedule: Every 15 minutes
-- Action: Review errors, check if pattern
-- NOTE: Filters out expected failures (no_data_available) to reduce alert noise by 90%+

SELECT
  processor_name,
  run_id,
  phase,
  started_at,
  duration_seconds,
  failure_category,
  JSON_VALUE(errors, '$[0]') as first_error,
  dependency_check_passed,
  JSON_VALUE(missing_dependencies, '$[0]') as first_missing_dep
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE status = 'failed'
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  -- Filter out expected failures (no data available, upstream issues)
  AND COALESCE(failure_category, 'unknown') NOT IN ('no_data_available')
ORDER BY started_at DESC
LIMIT 50;


-- ALERT 3: Phase Health Check (Last Hour)
-- Severity: P1
-- Schedule: Every 15 minutes
-- Action: Alert if any phase <50% success rate (based on real failures)
-- NOTE: Distinguishes between real failures and expected failures (no_data_available)

SELECT
  phase,
  COUNT(*) as total_runs,
  COUNTIF(status = 'success') as successes,
  COUNTIF(status = 'failed') as all_failures,
  -- Real failures: exclude expected scenarios (no_data_available)
  COUNTIF(status = 'failed' AND COALESCE(failure_category, 'unknown') NOT IN ('no_data_available')) as real_failures,
  -- Expected failures: no data available (don't alert on these)
  COUNTIF(status = 'failed' AND failure_category = 'no_data_available') as expected_failures,
  -- Success rate based on total (original metric)
  ROUND(COUNTIF(status = 'success') / COUNT(*) * 100, 2) as success_rate_pct,
  -- Effective success rate (excluding expected failures from denominator)
  ROUND(
    COUNTIF(status = 'success') /
    NULLIF(COUNT(*) - COUNTIF(status = 'failed' AND failure_category = 'no_data_available'), 0) * 100,
    2
  ) as effective_success_rate_pct,
  ROUND(AVG(duration_seconds), 2) as avg_duration_sec
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
GROUP BY phase
ORDER BY real_failures DESC;


-- ALERT 4: Slow Query Alert (Duration > 2x P95 Baseline)
-- Severity: P1
-- Schedule: Every 15 minutes
-- Action: Alert on anomalously slow runs

WITH p95_baselines AS (
  SELECT
    processor_name,
    APPROX_QUANTILES(duration_seconds, 100)[OFFSET(95)] as p95_duration
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    AND status = 'success'
    AND duration_seconds IS NOT NULL
  GROUP BY processor_name
)
SELECT
  h.processor_name,
  h.run_id,
  h.duration_seconds,
  b.p95_duration as baseline_p95,
  ROUND(h.duration_seconds / b.p95_duration, 2) as multiplier_of_p95,
  h.started_at
FROM `nba-props-platform.nba_reference.processor_run_history` h
JOIN p95_baselines b ON h.processor_name = b.processor_name
WHERE h.started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  AND h.status IN ('success', 'running')
  AND h.duration_seconds > 2 * b.p95_duration
ORDER BY multiplier_of_p95 DESC;


-- ALERT 5: Dependency Cascade Detection
-- Severity: P1
-- Schedule: Every 15 minutes
-- Action: Alert if >3 processors blocked by same dependency

SELECT
  JSON_VALUE(missing_dependencies, '$[0]') as missing_dependency,
  COUNT(DISTINCT processor_name) as blocked_processor_count,
  ARRAY_AGG(DISTINCT processor_name LIMIT 10) as blocked_processors,
  MIN(started_at) as first_failure_at
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  AND dependency_check_passed = false
  AND missing_dependencies IS NOT NULL
GROUP BY missing_dependency
HAVING COUNT(DISTINCT processor_name) > 3
ORDER BY blocked_processor_count DESC;


-- ALERT 6: Zero-Record Anomaly Detection
-- Severity: P2
-- Schedule: Every 30 minutes
-- Action: Alert for processors that normally produce data

WITH zero_record_baselines AS (
  SELECT
    processor_name,
    COUNTIF(records_created = 0) / COUNT(*) as expected_zero_rate
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    AND status = 'success'
  GROUP BY processor_name
  HAVING expected_zero_rate < 0.10  -- Processors that should usually produce data
)
SELECT
  h.processor_name,
  COUNT(*) as runs_last_hour,
  COUNTIF(h.records_created = 0) as zero_record_runs,
  ROUND(COUNTIF(h.records_created = 0) / COUNT(*), 2) as zero_rate,
  b.expected_zero_rate as baseline_zero_rate
FROM `nba-props-platform.nba_reference.processor_run_history` h
JOIN zero_record_baselines b ON h.processor_name = b.processor_name
WHERE h.started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  AND h.status = 'success'
GROUP BY h.processor_name, b.expected_zero_rate
HAVING COUNTIF(h.records_created = 0) / COUNT(*) > 0.50  -- >50% zero-record rate
ORDER BY zero_rate DESC;


-- =============================================================================
-- SECTION 2: DAILY HEALTH REPORTS
-- =============================================================================

-- REPORT 1: Daily Processor Summary (Last 24 Hours)
-- Schedule: Daily at 9am
-- Action: Email/Slack summary
-- NOTE: Now includes failure categorization to distinguish real vs expected failures

SELECT
  processor_name,
  phase,
  COUNT(*) as total_runs,
  COUNTIF(status = 'success') as successes,
  COUNTIF(status = 'failed') as all_failures,
  -- Real failures (should investigate)
  COUNTIF(status = 'failed' AND COALESCE(failure_category, 'unknown') NOT IN ('no_data_available')) as real_failures,
  -- Expected failures (no need to investigate)
  COUNTIF(status = 'failed' AND failure_category = 'no_data_available') as expected_failures,
  ROUND(COUNTIF(status = 'success') / COUNT(*) * 100, 2) as success_rate_pct,
  ROUND(AVG(duration_seconds), 2) as avg_duration_sec,
  ROUND(AVG(records_created), 2) as avg_records_created,
  COUNTIF(records_created = 0) as zero_record_runs,
  COUNTIF(dependency_check_passed = false) as dep_failures
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY processor_name, phase
ORDER BY real_failures DESC, total_runs DESC;


-- REPORT 2: Top 10 Real Errors (Last 24 Hours)
-- Schedule: Daily at 9am
-- Action: Review and categorize errors
-- NOTE: Filters out expected failures (no_data_available) to focus on real issues

SELECT
  failure_category,
  JSON_VALUE(errors, '$[0]') as error_message,
  COUNT(*) as occurrence_count,
  COUNT(DISTINCT processor_name) as affected_processors,
  ARRAY_AGG(DISTINCT processor_name LIMIT 10) as processors
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  AND status = 'failed'
  AND errors IS NOT NULL
  AND JSON_VALUE(errors, '$[0]') IS NOT NULL
  -- Filter out expected failures
  AND COALESCE(failure_category, 'unknown') NOT IN ('no_data_available')
GROUP BY failure_category, error_message
ORDER BY occurrence_count DESC
LIMIT 10;


-- REPORT 3: Phase Performance Trends (Last 7 Days)
-- Schedule: Weekly on Monday
-- Action: Identify degradation trends

WITH daily_stats AS (
  SELECT
    DATE(started_at) as run_date,
    phase,
    COUNT(*) as total_runs,
    COUNTIF(status = 'success') as successes,
    ROUND(AVG(duration_seconds), 2) as avg_duration_sec
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  GROUP BY run_date, phase
)
SELECT
  run_date,
  phase,
  total_runs,
  successes,
  ROUND(successes / total_runs * 100, 2) as success_rate_pct,
  avg_duration_sec,
  LAG(avg_duration_sec) OVER (PARTITION BY phase ORDER BY run_date) as prev_day_duration,
  ROUND(avg_duration_sec - LAG(avg_duration_sec) OVER (PARTITION BY phase ORDER BY run_date), 2) as duration_change
FROM daily_stats
ORDER BY run_date DESC, phase;


-- REPORT 4: Processor Performance Leaderboard (Last 7 Days)
-- Schedule: Weekly on Monday
-- Action: Recognize good performers, investigate poor ones

WITH processor_stats AS (
  SELECT
    processor_name,
    COUNT(*) as total_runs,
    COUNTIF(status = 'success') as successes,
    ROUND(AVG(duration_seconds), 2) as avg_duration,
    ROUND(STDDEV(duration_seconds), 2) as stddev_duration,
    ROUND(AVG(records_created), 2) as avg_records
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    AND status = 'success'
  GROUP BY processor_name
  HAVING total_runs > 10
)
SELECT
  processor_name,
  total_runs,
  successes,
  avg_duration,
  stddev_duration,
  ROUND(stddev_duration / NULLIF(avg_duration, 0), 2) as coefficient_of_variation,
  avg_records,
  -- Performance score (lower is better): combines reliability + speed + stability
  ROUND(
    (1 - successes / total_runs) * 100 +  -- Failure penalty
    avg_duration / 10 +                    -- Duration penalty (scaled)
    (stddev_duration / NULLIF(avg_duration, 0)) * 10  -- Variance penalty
  , 2) as performance_score
FROM processor_stats
ORDER BY performance_score ASC
LIMIT 20;


-- =============================================================================
-- SECTION 3: DEEP DIVE INVESTIGATIONS
-- =============================================================================

-- INVESTIGATION 1: Record Count Anomaly Deep Dive
-- Usage: Run when anomaly alert fires
-- Action: Understand why record count is abnormal

WITH historical_stats AS (
  SELECT
    processor_name,
    AVG(records_created) as avg_records,
    STDDEV(records_created) as stddev_records,
    MIN(records_created) as min_records,
    MAX(records_created) as max_records,
    APPROX_QUANTILES(records_created, 100)[OFFSET(25)] as q25,
    APPROX_QUANTILES(records_created, 100)[OFFSET(50)] as median,
    APPROX_QUANTILES(records_created, 100)[OFFSET(75)] as q75
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
    AND status = 'success'
    AND records_created > 0
  GROUP BY processor_name
)
SELECT
  h.processor_name,
  h.run_id,
  h.started_at,
  h.records_created,
  s.avg_records,
  s.stddev_records,
  s.median,
  ROUND((h.records_created - s.avg_records) / NULLIF(s.stddev_records, 0), 2) as z_score,
  CASE
    WHEN h.records_created < s.q25 - 1.5 * (s.q75 - s.q25) THEN 'Low Outlier'
    WHEN h.records_created > s.q75 + 1.5 * (s.q75 - s.q25) THEN 'High Outlier'
    ELSE 'Normal'
  END as outlier_status
FROM `nba-props-platform.nba_reference.processor_run_history` h
JOIN historical_stats s ON h.processor_name = s.processor_name
WHERE h.started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND h.status = 'success'
  AND ABS(h.records_created - s.avg_records) > 3 * s.stddev_records
ORDER BY ABS(z_score) DESC;


-- INVESTIGATION 2: Dependency Chain Analysis
-- Usage: Understand which processors depend on what
-- Action: Identify critical path and bottlenecks

SELECT
  processor_name,
  phase,
  JSON_VALUE(upstream_dependencies, '$[0].table_name') as dep1,
  JSON_VALUE(upstream_dependencies, '$[1].table_name') as dep2,
  JSON_VALUE(upstream_dependencies, '$[2].table_name') as dep3,
  COUNT(DISTINCT run_id) as total_runs,
  COUNTIF(dependency_check_passed = false) as dep_failures,
  ROUND(COUNTIF(dependency_check_passed = false) / COUNT(*) * 100, 2) as dep_failure_rate_pct
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND upstream_dependencies IS NOT NULL
GROUP BY processor_name, phase, dep1, dep2, dep3
ORDER BY dep_failures DESC;


-- INVESTIGATION 3: Processor Run Duration Timeline
-- Usage: Visualize when a specific processor is slow
-- Action: Identify time-of-day or day-of-week patterns

SELECT
  processor_name,
  started_at,
  duration_seconds,
  records_created,
  EXTRACT(HOUR FROM started_at) as hour_of_day,
  EXTRACT(DAYOFWEEK FROM started_at) as day_of_week,
  status
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE processor_name = 'PlayerGameSummaryProcessor'  -- REPLACE with processor of interest
  AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY started_at DESC;


-- INVESTIGATION 4: Failure Spike Root Cause Analysis
-- Usage: When alerts show spike in failures
-- Action: Group by error type, time, and common attributes

WITH failure_analysis AS (
  SELECT
    DATE_TRUNC(started_at, HOUR) as failure_hour,
    processor_name,
    phase,
    JSON_VALUE(errors, '$[0]') as error_message,
    COUNT(*) as failure_count
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
    AND status = 'failed'
  GROUP BY failure_hour, processor_name, phase, error_message
)
SELECT
  failure_hour,
  SUM(failure_count) as total_failures,
  ARRAY_AGG(
    STRUCT(processor_name, phase, error_message, failure_count)
    ORDER BY failure_count DESC
    LIMIT 5
  ) as top_5_errors
FROM failure_analysis
GROUP BY failure_hour
ORDER BY failure_hour DESC;


-- INVESTIGATION 5: Retry Success Rate Analysis
-- Usage: Understand which processors benefit from retries
-- Action: Optimize retry logic per processor

SELECT
  processor_name,
  retry_attempt,
  COUNT(*) as run_count,
  COUNTIF(status = 'success') as successes,
  COUNTIF(status = 'failed') as failures,
  ROUND(COUNTIF(status = 'success') / COUNT(*) * 100, 2) as success_rate_pct
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND retry_attempt IS NOT NULL
GROUP BY processor_name, retry_attempt
HAVING run_count > 5
ORDER BY processor_name, retry_attempt;


-- =============================================================================
-- SECTION 4: CAPACITY PLANNING & TRENDS
-- =============================================================================

-- CAPACITY 1: Hourly Run Volume Pattern (Last 7 Days)
-- Usage: Understand peak load times
-- Action: Plan capacity, identify retry storms

SELECT
  EXTRACT(HOUR FROM started_at) as hour_of_day,
  EXTRACT(DAYOFWEEK FROM started_at) as day_of_week,
  COUNT(*) as total_runs,
  COUNTIF(status = 'success') as successes,
  COUNTIF(status = 'failed') as failures,
  ROUND(AVG(duration_seconds), 2) as avg_duration_sec,
  ROUND(SUM(duration_seconds) / 3600, 2) as total_compute_hours
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY hour_of_day, day_of_week
ORDER BY total_runs DESC;


-- CAPACITY 2: Processor Concurrency Analysis
-- Usage: Identify if processors run concurrently or serially
-- Action: Optimize DAG execution

WITH running_processors AS (
  SELECT
    started_at,
    TIMESTAMP_ADD(started_at, INTERVAL CAST(duration_seconds AS INT64) SECOND) as ended_at,
    processor_name
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
    AND duration_seconds IS NOT NULL
)
SELECT
  a.processor_name as processor_a,
  b.processor_name as processor_b,
  COUNT(*) as concurrent_runs
FROM running_processors a
JOIN running_processors b
  ON a.started_at < b.ended_at
  AND a.ended_at > b.started_at
  AND a.processor_name < b.processor_name  -- Avoid duplicates
GROUP BY processor_a, processor_b
HAVING concurrent_runs > 10
ORDER BY concurrent_runs DESC;


-- CAPACITY 3: Data Growth Trends
-- Usage: Predict storage and processing needs
-- Action: Plan for scale

WITH daily_volume AS (
  SELECT
    DATE(started_at) as run_date,
    SUM(records_created) as total_records_created,
    COUNT(DISTINCT processor_name) as active_processors,
    SUM(duration_seconds) / 3600 as total_compute_hours
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
    AND status = 'success'
  GROUP BY run_date
)
SELECT
  run_date,
  total_records_created,
  active_processors,
  total_compute_hours,
  AVG(total_records_created) OVER (
    ORDER BY run_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
  ) as rolling_7day_avg_records,
  AVG(total_compute_hours) OVER (
    ORDER BY run_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
  ) as rolling_7day_avg_hours
FROM daily_volume
ORDER BY run_date DESC;


-- =============================================================================
-- SECTION 5: DATA QUALITY CHECKS
-- =============================================================================

-- QUALITY 1: Processors with No Recent Runs
-- Severity: P2
-- Schedule: Daily
-- Action: Investigate if processor is disabled or broken

SELECT
  processor_name,
  MAX(started_at) as last_run_at,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(started_at), HOUR) as hours_since_last_run
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY processor_name
HAVING hours_since_last_run > 24
ORDER BY hours_since_last_run DESC;


-- QUALITY 2: Processors Always Producing Zero Records
-- Severity: P1
-- Schedule: Weekly
-- Action: Investigate if processor is configured correctly

SELECT
  processor_name,
  COUNT(*) as total_successful_runs,
  COUNTIF(records_created = 0) as zero_record_runs,
  ROUND(COUNTIF(records_created = 0) / COUNT(*) * 100, 2) as zero_record_rate_pct,
  MAX(records_created) as max_records_ever
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  AND status = 'success'
GROUP BY processor_name
HAVING zero_record_rate_pct > 95.0  -- >95% zero-record rate
ORDER BY zero_record_rate_pct DESC;


-- QUALITY 3: Schema Validation - Check for Unexpected NULL Values
-- Severity: P2
-- Schedule: Weekly
-- Action: Identify data quality issues

SELECT
  'Missing duration_seconds' as issue,
  COUNT(*) as affected_runs
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND status = 'success'
  AND duration_seconds IS NULL

UNION ALL

SELECT
  'Missing processed_at timestamp' as issue,
  COUNT(*) as affected_runs
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND status = 'success'
  AND processed_at IS NULL

UNION ALL

SELECT
  'Missing phase classification' as issue,
  COUNT(*) as affected_runs
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND phase IS NULL

ORDER BY affected_runs DESC;


-- =============================================================================
-- SECTION 6: COST OPTIMIZATION
-- =============================================================================

-- COST 1: Most Expensive Processors (Compute Time)
-- Usage: Identify optimization targets
-- Action: Optimize queries, add caching, improve algorithms

SELECT
  processor_name,
  COUNT(*) as total_runs,
  ROUND(SUM(duration_seconds) / 3600, 2) as total_compute_hours,
  ROUND(AVG(duration_seconds), 2) as avg_duration_sec,
  ROUND(SUM(duration_seconds) / 3600 * 0.10, 2) as estimated_cost_usd  -- $0.10/hour estimate
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  AND status = 'success'
GROUP BY processor_name
ORDER BY total_compute_hours DESC
LIMIT 20;


-- COST 2: Failed Run Waste Analysis
-- Usage: Quantify cost of failures
-- Action: Prioritize fixing highest-cost failures

SELECT
  processor_name,
  COUNT(*) as failed_runs,
  ROUND(SUM(IFNULL(duration_seconds, 0)) / 3600, 2) as wasted_compute_hours,
  ROUND(AVG(IFNULL(duration_seconds, 0)), 2) as avg_time_before_failure_sec,
  ROUND(SUM(IFNULL(duration_seconds, 0)) / 3600 * 0.10, 2) as wasted_cost_usd
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  AND status = 'failed'
GROUP BY processor_name
ORDER BY wasted_compute_hours DESC
LIMIT 20;


-- =============================================================================
-- SECTION 7: FAILURE CATEGORIZATION ANALYSIS (Added 2026-01-14, Session 35)
-- =============================================================================

-- CATEGORY 1: Failure Category Breakdown (Last 7 Days)
-- Purpose: Validate failure categorization and track alert noise reduction
-- Schedule: Weekly review

SELECT
  failure_category,
  COUNT(*) as failure_count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as pct_of_all_failures,
  COUNT(DISTINCT processor_name) as affected_processors,
  ARRAY_AGG(DISTINCT processor_name LIMIT 5) as sample_processors
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND status = 'failed'
GROUP BY failure_category
ORDER BY failure_count DESC;


-- CATEGORY 2: Alert Noise Reduction Metrics
-- Purpose: Track how much alert noise was reduced by filtering expected failures
-- Use to validate the 90%+ noise reduction goal

SELECT
  DATE(started_at) as date,
  COUNT(*) as total_failures,
  COUNTIF(COALESCE(failure_category, 'unknown') = 'no_data_available') as expected_failures,
  COUNTIF(COALESCE(failure_category, 'unknown') NOT IN ('no_data_available')) as real_failures,
  ROUND(
    COUNTIF(COALESCE(failure_category, 'unknown') = 'no_data_available') * 100.0 / NULLIF(COUNT(*), 0),
    2
  ) as noise_reduction_pct
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND status = 'failed'
GROUP BY date
ORDER BY date DESC;


-- CATEGORY 3: Failure Category by Phase
-- Purpose: Understand which phases have expected vs real failures

SELECT
  phase,
  failure_category,
  COUNT(*) as failure_count,
  ARRAY_AGG(DISTINCT processor_name LIMIT 3) as sample_processors
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND status = 'failed'
GROUP BY phase, failure_category
ORDER BY phase, failure_count DESC;


-- =============================================================================
-- END OF MONITORING QUERIES
-- =============================================================================

-- To use these queries:
-- 1. Copy the query you need
-- 2. Run in BigQuery console or schedule via Cloud Scheduler
-- 3. Connect to alerting system (Cloud Monitoring, PagerDuty, Slack)
-- 4. Adjust thresholds based on your SLAs

-- For automated scheduling:
-- - Real-time alerts: Every 5-15 minutes
-- - Daily reports: Once per day at 9am
-- - Weekly reports: Monday morning
-- - Cost analysis: Monthly

-- Recommended alerting thresholds:
-- - P0 (Page immediately): Stuck processors >15 min, Phase success rate <30%
-- - P1 (Alert urgently): Slow queries >2x P95, Dependency cascades >3 processors
-- - P2 (Monitor/Review): Zero-record anomalies, Schema validation issues
