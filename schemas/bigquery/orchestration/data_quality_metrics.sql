-- ============================================================================
-- NBA Props Platform - Data Quality Metrics Table
-- Data Quality Self-Healing System
-- ============================================================================
-- Table: nba_orchestration.data_quality_metrics
-- Purpose: Daily quality metrics for trend analysis and alerting
-- Update: Daily via scheduled query or Cloud Function
-- Retention: 365 days
--
-- Version: 1.0 (Initial implementation)
-- Date: January 2026
-- Status: Production-Ready
--
-- Related Documents:
-- - docs/08-projects/current/data-quality-self-healing/README.md
-- ============================================================================

-- ============================================================================
-- TABLE DEFINITION
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.data_quality_metrics` (
  -- ============================================================================
  -- IDENTIFIERS (3 fields)
  -- ============================================================================
  metric_id STRING NOT NULL,                        -- Unique metric ID (UUID)
                                                     -- Example: '550e8400-e29b-41d4-a716-446655440000'

  metric_date DATE NOT NULL,                        -- Date of measurement
                                                     -- Example: '2026-01-29'

  check_run_id STRING,                              -- Batch ID for this check run
                                                     -- Groups metrics from same check execution

  -- ============================================================================
  -- METRIC DEFINITION (4 fields)
  -- ============================================================================
  table_name STRING NOT NULL,                       -- Source table being measured
                                                     -- Example: 'player_game_summary'

  metric_name STRING NOT NULL,                      -- Metric identifier
                                                     -- Examples: 'pct_zero_points', 'pct_dnp_marked',
                                                     --           'avg_points', 'record_count',
                                                     --           'fatigue_avg', 'feature_completeness'

  metric_value FLOAT64 NOT NULL,                    -- Measured value
                                                     -- Example: 8.5

  metric_unit STRING,                               -- Unit of measurement
                                                     -- Examples: 'percent', 'count', 'points', 'score'

  -- ============================================================================
  -- THRESHOLDS (4 fields)
  -- ============================================================================
  threshold_warning FLOAT64,                        -- Warning threshold
                                                     -- Example: 15.0

  threshold_critical FLOAT64,                       -- Critical threshold
                                                     -- Example: 30.0

  direction STRING,                                 -- How to compare against threshold
                                                     -- Values: 'above', 'below', 'outside_range'

  status STRING NOT NULL,                           -- Result status
                                                     -- Values: 'OK', 'WARNING', 'CRITICAL'

  -- ============================================================================
  -- CONTEXT (3 fields)
  -- ============================================================================
  baseline_value FLOAT64,                           -- 7-day rolling baseline
                                                     -- Example: 7.2

  deviation_pct FLOAT64,                            -- Percent deviation from baseline
                                                     -- Example: 18.0 (18% higher than baseline)

  details STRING,                                   -- Additional context or debug info
                                                     -- Example: '{"total_records": 250, "zero_count": 21}'

  -- ============================================================================
  -- METADATA (2 fields)
  -- ============================================================================
  query_duration_ms INT64,                          -- How long the check took
                                                     -- Example: 1500

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() -- Row creation timestamp
)
PARTITION BY metric_date
CLUSTER BY table_name, metric_name
OPTIONS(
  description="Daily data quality metrics for trend analysis and alerting. Tracks quality indicators over time.",
  partition_expiration_days=365
);

-- ============================================================================
-- VALIDATION QUERIES
-- ============================================================================

-- Query 1: Today's quality status
SELECT
  table_name,
  metric_name,
  metric_value,
  threshold_warning,
  threshold_critical,
  status,
  deviation_pct
FROM `nba-props-platform.nba_orchestration.data_quality_metrics`
WHERE metric_date = CURRENT_DATE() - 1  -- Yesterday's data
ORDER BY
  CASE status WHEN 'CRITICAL' THEN 0 WHEN 'WARNING' THEN 1 ELSE 2 END,
  table_name,
  metric_name;

-- Query 2: Quality trends for a specific metric
SELECT
  metric_date,
  metric_value,
  baseline_value,
  status,
  deviation_pct
FROM `nba-props-platform.nba_orchestration.data_quality_metrics`
WHERE table_name = 'player_game_summary'
  AND metric_name = 'pct_zero_points'
  AND metric_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY metric_date DESC;

-- Query 3: Critical issues over time
SELECT
  metric_date,
  table_name,
  metric_name,
  metric_value,
  threshold_critical
FROM `nba-props-platform.nba_orchestration.data_quality_metrics`
WHERE status = 'CRITICAL'
  AND metric_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY metric_date DESC, table_name;

-- Query 4: Overall quality score by table
SELECT
  table_name,
  COUNT(*) as total_checks,
  COUNTIF(status = 'OK') as ok_count,
  COUNTIF(status = 'WARNING') as warning_count,
  COUNTIF(status = 'CRITICAL') as critical_count,
  ROUND(100.0 * COUNTIF(status = 'OK') / COUNT(*), 1) as quality_score_pct
FROM `nba-props-platform.nba_orchestration.data_quality_metrics`
WHERE metric_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY table_name
ORDER BY quality_score_pct ASC;

-- ============================================================================
-- HELPER VIEWS
-- ============================================================================

-- View: Latest quality status by table/metric
CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_latest_quality_status` AS
WITH latest AS (
  SELECT
    table_name,
    metric_name,
    metric_value,
    status,
    deviation_pct,
    metric_date,
    ROW_NUMBER() OVER (
      PARTITION BY table_name, metric_name
      ORDER BY metric_date DESC
    ) as rn
  FROM `nba-props-platform.nba_orchestration.data_quality_metrics`
  WHERE metric_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
)
SELECT
  table_name,
  metric_name,
  metric_value,
  status,
  deviation_pct,
  metric_date as last_checked
FROM latest
WHERE rn = 1
ORDER BY
  CASE status WHEN 'CRITICAL' THEN 0 WHEN 'WARNING' THEN 1 ELSE 2 END,
  table_name,
  metric_name;

-- ============================================================================
-- SAMPLE ROWS
-- ============================================================================

/*
-- Sample: OK status
{
  "metric_id": "550e8400-e29b-41d4-a716-446655440000",
  "metric_date": "2026-01-29",
  "check_run_id": "run_20260130_080000",
  "table_name": "player_game_summary",
  "metric_name": "pct_zero_points",
  "metric_value": 8.5,
  "metric_unit": "percent",
  "threshold_warning": 15.0,
  "threshold_critical": 30.0,
  "direction": "above",
  "status": "OK",
  "baseline_value": 7.2,
  "deviation_pct": 18.0,
  "query_duration_ms": 1500
}

-- Sample: CRITICAL status
{
  "metric_id": "550e8400-e29b-41d4-a716-446655440001",
  "metric_date": "2026-01-22",
  "table_name": "player_game_summary",
  "metric_name": "pct_zero_points",
  "metric_value": 46.8,
  "threshold_warning": 15.0,
  "threshold_critical": 30.0,
  "direction": "above",
  "status": "CRITICAL",
  "baseline_value": 8.0,
  "deviation_pct": 485.0,
  "details": "{\"total_records\": 250, \"zero_count\": 117, \"dnp_marked\": 0}"
}
*/

-- ============================================================================
-- SCHEDULED QUERY TEMPLATE
-- ============================================================================
-- This query can be scheduled to run daily at 8 AM ET to populate metrics

/*
INSERT INTO `nba-props-platform.nba_orchestration.data_quality_metrics`
(metric_id, metric_date, check_run_id, table_name, metric_name, metric_value,
 threshold_warning, threshold_critical, direction, status, created_at)

-- pct_zero_points check
SELECT
  GENERATE_UUID() as metric_id,
  @check_date as metric_date,
  @run_id as check_run_id,
  'player_game_summary' as table_name,
  'pct_zero_points' as metric_name,
  ROUND(100.0 * COUNTIF(points = 0) / COUNT(*), 1) as metric_value,
  15.0 as threshold_warning,
  30.0 as threshold_critical,
  'above' as direction,
  CASE
    WHEN ROUND(100.0 * COUNTIF(points = 0) / COUNT(*), 1) > 30 THEN 'CRITICAL'
    WHEN ROUND(100.0 * COUNTIF(points = 0) / COUNT(*), 1) > 15 THEN 'WARNING'
    ELSE 'OK'
  END as status,
  CURRENT_TIMESTAMP() as created_at
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = @check_date

UNION ALL

-- pct_dnp_marked check
SELECT
  GENERATE_UUID() as metric_id,
  @check_date as metric_date,
  @run_id as check_run_id,
  'player_game_summary' as table_name,
  'pct_dnp_marked' as metric_name,
  ROUND(100.0 * COUNTIF(is_dnp = TRUE) / COUNT(*), 1) as metric_value,
  5.0 as threshold_warning,
  0.0 as threshold_critical,
  'below' as direction,
  CASE
    WHEN COUNTIF(is_dnp = TRUE) = 0 THEN 'CRITICAL'
    WHEN ROUND(100.0 * COUNTIF(is_dnp = TRUE) / COUNT(*), 1) < 5 THEN 'WARNING'
    ELSE 'OK'
  END as status,
  CURRENT_TIMESTAMP() as created_at
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = @check_date
*/

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================
