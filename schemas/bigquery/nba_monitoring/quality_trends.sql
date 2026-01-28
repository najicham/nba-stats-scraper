-- ============================================================================
-- NBA Monitoring - Quality Trends Table
-- Path: schemas/bigquery/nba_monitoring/quality_trends.sql
-- Created: 2026-01-27
-- ============================================================================
-- Purpose: Track quality metrics over time with statistical anomaly detection
-- Impact: Enables proactive alerting before quality degradation becomes critical
-- Priority: P1 (HIGH - fills gap in trend-based monitoring)
-- ============================================================================

-- ============================================================================
-- TABLE: quality_trends
-- ============================================================================
-- This table provides time-series tracking of key quality metrics with
-- statistical analysis for trend detection and anomaly alerting.
-- It enables:
--   1. 7-day rolling average tracking for all quality metrics
--   2. Statistical anomaly detection (>2 standard deviations)
--   3. Trend direction classification (improving/stable/declining)
--   4. Automated alerting on quality degradation
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_monitoring.quality_trends` (
  -- ============================================================================
  -- TIME AND METRIC IDENTIFICATION (2 fields)
  -- ============================================================================
  metric_date DATE NOT NULL,                    -- Date for which metric was calculated
  metric_name STRING NOT NULL,                  -- Metric identifier (e.g., "field_completeness_minutes_played")

  -- ============================================================================
  -- METRIC VALUE (1 field)
  -- ============================================================================
  metric_value FLOAT64,                         -- Current metric value (percentage, count, or rate)

  -- ============================================================================
  -- ROLLING STATISTICS (2 fields)
  -- ============================================================================
  rolling_7d_avg FLOAT64,                       -- 7-day rolling average of metric
  rolling_7d_stddev FLOAT64,                    -- 7-day rolling standard deviation

  -- ============================================================================
  -- TREND ANALYSIS (3 fields)
  -- ============================================================================
  trend_direction STRING,                       -- Trend classification: 'improving', 'stable', 'declining'
  deviation_from_avg FLOAT64,                   -- Number of standard deviations from 7-day average
  alert_triggered BOOLEAN,                      -- TRUE if metric triggered an alert condition

  -- ============================================================================
  -- RECORD METADATA (1 field)
  -- ============================================================================
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP() NOT NULL
)
PARTITION BY metric_date
CLUSTER BY metric_name
OPTIONS(
  description="Quality metrics tracking with rolling statistics and trend detection. Supports automated alerting on quality degradation.",
  partition_expiration_days=365                 -- Keep 1 year of quality trend history
);

-- ============================================================================
-- INDEXES
-- ============================================================================
-- Partition key: metric_date
--   - Enables efficient time-range queries
--   - Automatic partition expiration after 365 days
--   - Typical query: WHERE metric_date >= CURRENT_DATE() - 30
--
-- Cluster key: metric_name
--   - Co-locates records for same metric
--   - Optimizes queries by specific metric
--   - Typical query: WHERE metric_name = 'field_completeness_minutes_played'
-- ============================================================================

-- ============================================================================
-- METRIC NAMING CONVENTIONS
-- ============================================================================
-- Field Completeness Metrics (from player_game_summary):
--   - field_completeness_minutes_played
--   - field_completeness_usage_rate
--   - field_completeness_points
--   - field_completeness_rebounds
--   - field_completeness_assists
--   - field_completeness_paint_attempts
--   - field_completeness_paint_makes
--   - field_completeness_mid_range_attempts
--   - field_completeness_mid_range_makes
--   - field_completeness_three_pt_blocks
--
-- Prediction Coverage Metrics (from predictions):
--   - prediction_coverage_overall
--   - prediction_coverage_points
--   - prediction_coverage_rebounds
--   - prediction_coverage_assists
--
-- Processing Success Metrics (from processor_run_history):
--   - processing_success_rate_phase3
--   - processing_success_rate_phase4
--   - processing_success_rate_overall
-- ============================================================================

-- ============================================================================
-- ALERT CONDITIONS
-- ============================================================================
-- alert_triggered = TRUE when ANY of these conditions are met:
--
-- 1. Significant Decline:
--    - metric_value dropped >5% compared to rolling_7d_avg
--    - Example: 95% completeness dropping to 89% (>5% decline)
--
-- 2. Statistical Anomaly:
--    - deviation_from_avg > 2.0 (more than 2 standard deviations)
--    - Indicates metric is significantly outside normal range
--
-- 3. Declining Trend:
--    - trend_direction = 'declining'
--    - AND metric_value < (rolling_7d_avg - (0.05 * rolling_7d_avg))
--    - Confirms sustained decline beyond statistical noise
-- ============================================================================

-- ============================================================================
-- EXAMPLE ROWS
-- ============================================================================

-- Example 1: Stable Metric (No Alert)
/*
{
  "metric_date": "2026-01-27",
  "metric_name": "field_completeness_minutes_played",
  "metric_value": 99.2,
  "rolling_7d_avg": 99.1,
  "rolling_7d_stddev": 0.3,
  "trend_direction": "stable",
  "deviation_from_avg": 0.33,
  "alert_triggered": false,
  "created_at": "2026-01-27T08:00:00Z"
}
*/

-- Example 2: Declining Metric with Alert
/*
{
  "metric_date": "2026-01-27",
  "metric_name": "field_completeness_usage_rate",
  "metric_value": 89.5,
  "rolling_7d_avg": 95.2,
  "rolling_7d_stddev": 1.1,
  "trend_direction": "declining",
  "deviation_from_avg": -5.18,
  "alert_triggered": true,
  "created_at": "2026-01-27T08:00:00Z"
}
*/

-- Example 3: Statistical Anomaly with Alert
/*
{
  "metric_date": "2026-01-27",
  "metric_name": "prediction_coverage_overall",
  "metric_value": 62.3,
  "rolling_7d_avg": 68.5,
  "rolling_7d_stddev": 2.1,
  "trend_direction": "declining",
  "deviation_from_avg": -2.95,
  "alert_triggered": true,
  "created_at": "2026-01-27T08:00:00Z"
}
*/

-- Example 4: Improving Metric (No Alert)
/*
{
  "metric_date": "2026-01-27",
  "metric_name": "processing_success_rate_phase3",
  "metric_value": 97.8,
  "rolling_7d_avg": 95.5,
  "rolling_7d_stddev": 1.2,
  "trend_direction": "improving",
  "deviation_from_avg": 1.92,
  "alert_triggered": false,
  "created_at": "2026-01-27T08:00:00Z"
}
*/

-- ============================================================================
-- USAGE PATTERNS
-- ============================================================================

-- Pattern 1: Insert Daily Metric (via scheduled query)
-- INSERT INTO `nba-props-platform.nba_monitoring.quality_trends`
-- (metric_date, metric_name, metric_value, rolling_7d_avg, rolling_7d_stddev,
--  trend_direction, deviation_from_avg, alert_triggered)
-- VALUES
-- ('2026-01-27', 'field_completeness_minutes_played', 99.2, 99.1, 0.3,
--  'stable', 0.33, false);

-- Pattern 2: Query Recent Alerts
-- SELECT
--   metric_date,
--   metric_name,
--   metric_value,
--   rolling_7d_avg,
--   trend_direction,
--   deviation_from_avg
-- FROM `nba-props-platform.nba_monitoring.quality_trends`
-- WHERE alert_triggered = TRUE
--   AND metric_date >= CURRENT_DATE() - 7
-- ORDER BY metric_date DESC, deviation_from_avg;

-- Pattern 3: Trend Analysis for Specific Metric
-- SELECT
--   metric_date,
--   metric_value,
--   rolling_7d_avg,
--   trend_direction,
--   alert_triggered
-- FROM `nba-props-platform.nba_monitoring.quality_trends`
-- WHERE metric_name = 'field_completeness_usage_rate'
--   AND metric_date >= CURRENT_DATE() - 30
-- ORDER BY metric_date DESC;

-- ============================================================================
-- MONITORING QUERIES
-- ============================================================================

-- Query 1: All Active Alerts (Last 7 Days)
SELECT
  metric_date,
  metric_name,
  metric_value,
  rolling_7d_avg,
  rolling_7d_stddev,
  trend_direction,
  ROUND(deviation_from_avg, 2) as stddev_from_avg
FROM `nba-props-platform.nba_monitoring.quality_trends`
WHERE alert_triggered = TRUE
  AND metric_date >= CURRENT_DATE() - 7
ORDER BY metric_date DESC, ABS(deviation_from_avg) DESC;

-- Query 2: Metric Trend Summary (Last 30 Days)
SELECT
  metric_name,
  COUNT(*) as days_tracked,
  ROUND(AVG(metric_value), 2) as avg_value,
  ROUND(MIN(metric_value), 2) as min_value,
  ROUND(MAX(metric_value), 2) as max_value,
  COUNTIF(alert_triggered) as alert_days,
  ROUND(COUNTIF(alert_triggered) * 100.0 / COUNT(*), 1) as alert_pct
FROM `nba-props-platform.nba_monitoring.quality_trends`
WHERE metric_date >= CURRENT_DATE() - 30
GROUP BY metric_name
ORDER BY alert_pct DESC, metric_name;

-- Query 3: Declining Metrics Requiring Attention
SELECT
  metric_name,
  metric_date,
  metric_value,
  rolling_7d_avg,
  ROUND(metric_value - rolling_7d_avg, 2) as decline_amount,
  ROUND((metric_value - rolling_7d_avg) / NULLIF(rolling_7d_avg, 0) * 100, 1) as decline_pct
FROM `nba-props-platform.nba_monitoring.quality_trends`
WHERE trend_direction = 'declining'
  AND metric_date >= CURRENT_DATE() - 7
  AND metric_value < rolling_7d_avg - (0.05 * rolling_7d_avg)
ORDER BY decline_pct, metric_date DESC;

-- Query 4: Metric Health Dashboard (Today vs 7-Day Average)
SELECT
  t.metric_name,
  t.metric_value as today_value,
  t.rolling_7d_avg as week_avg,
  ROUND(t.metric_value - t.rolling_7d_avg, 2) as variance,
  t.trend_direction,
  t.alert_triggered,
  CASE
    WHEN t.trend_direction = 'improving' THEN '✅ IMPROVING'
    WHEN t.trend_direction = 'stable' THEN '✓ STABLE'
    WHEN t.trend_direction = 'declining' AND t.alert_triggered THEN '❌ DECLINING (ALERT)'
    WHEN t.trend_direction = 'declining' THEN '⚠ DECLINING'
    ELSE '○ UNKNOWN'
  END as status
FROM `nba-props-platform.nba_monitoring.quality_trends` t
WHERE t.metric_date = CURRENT_DATE()
ORDER BY t.alert_triggered DESC, t.trend_direction, t.metric_name;

-- ============================================================================
-- DEPLOYMENT CHECKLIST
-- ============================================================================
-- [ ] Create nba_monitoring dataset if not exists
-- [ ] Run CREATE TABLE for quality_trends
-- [ ] Verify schema matches expectations (8 fields total)
-- [ ] Set partition expiration (365 days)
-- [ ] Configure clustering (metric_name)
-- [ ] Create scheduled query to populate daily metrics
-- [ ] Create quality_trend_alerts view for filtering
-- [ ] Configure alerts in Slack/email for triggered alerts
-- [ ] Set up Grafana dashboard for trend visualization
-- [ ] Document metric naming conventions
-- ============================================================================

-- ============================================================================
-- INTEGRATION NOTES
-- ============================================================================
-- Daily Scheduled Query Should:
--   1. Run at 8:00 AM PT (after nightly processing completes)
--   2. Calculate metrics for CURRENT_DATE() - 1 (previous day)
--   3. Compute rolling 7-day statistics using window functions
--   4. Classify trend direction based on 3-day comparison
--   5. Set alert_triggered based on defined conditions
--   6. Insert results into this table
--
-- Supported Metric Sources:
--   - nba_analytics.player_game_summary (field completeness)
--   - nba_predictions.player_prop_predictions (prediction coverage)
--   - nba_reference.processor_run_history (processing success)
--
-- Alert Integration:
--   - Query quality_trend_alerts view for active alerts
--   - Send Slack notification via notification_system.py
--   - Include metric name, trend direction, and deviation in alert
-- ============================================================================
