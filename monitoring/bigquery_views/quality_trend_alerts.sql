-- ============================================================================
-- View: quality_trend_alerts
-- Path: monitoring/bigquery_views/quality_trend_alerts.sql
-- Created: 2026-01-27
-- ============================================================================
-- Purpose: Filter quality_trends to show only active alerts requiring attention
-- Usage: SELECT * FROM `nba-props-platform.nba_monitoring.quality_trend_alerts`
-- ============================================================================
-- Provides focused view of quality metrics that have triggered alerts,
-- making it easy to:
--   1. Send targeted Slack/email notifications
--   2. Display critical metrics in monitoring dashboards
--   3. Prioritize quality issues requiring immediate attention
--   4. Track alert frequency and patterns over time
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_monitoring.quality_trend_alerts` AS

WITH latest_alerts AS (
  SELECT
    metric_date,
    metric_name,
    metric_value,
    rolling_7d_avg,
    rolling_7d_stddev,
    trend_direction,
    deviation_from_avg,
    created_at
  FROM `nba-props-platform.nba_monitoring.quality_trends`
  WHERE alert_triggered = TRUE
),

-- ============================================================================
-- Categorize metrics by type for better reporting
-- ============================================================================
categorized_alerts AS (
  SELECT
    metric_date,
    metric_name,
    metric_value,
    rolling_7d_avg,
    rolling_7d_stddev,
    trend_direction,
    deviation_from_avg,
    created_at,
    -- Categorize metric type
    CASE
      WHEN metric_name LIKE 'field_completeness_%' THEN 'Field Completeness'
      WHEN metric_name LIKE 'prediction_coverage_%' THEN 'Prediction Coverage'
      WHEN metric_name LIKE 'processing_success_rate_%' THEN 'Processing Success'
      ELSE 'Other'
    END as metric_category,
    -- Extract field name for completeness metrics
    CASE
      WHEN metric_name LIKE 'field_completeness_%'
      THEN REPLACE(metric_name, 'field_completeness_', '')
      ELSE NULL
    END as field_name
  FROM latest_alerts
),

-- ============================================================================
-- Calculate alert severity and impact
-- ============================================================================
alerts_with_severity AS (
  SELECT
    metric_date,
    metric_name,
    metric_category,
    field_name,
    metric_value,
    rolling_7d_avg,
    rolling_7d_stddev,
    trend_direction,
    deviation_from_avg,
    created_at,
    -- Calculate percentage decline from average
    ROUND((metric_value - rolling_7d_avg) / NULLIF(rolling_7d_avg, 0) * 100, 1) as pct_change_from_avg,
    -- Determine severity based on deviation and decline
    CASE
      WHEN ABS(deviation_from_avg) > 3.0 THEN 'CRITICAL'
      WHEN ABS(deviation_from_avg) > 2.5 THEN 'HIGH'
      WHEN ABS(deviation_from_avg) > 2.0 THEN 'MEDIUM'
      WHEN metric_value < rolling_7d_avg - (0.05 * rolling_7d_avg) THEN 'MEDIUM'
      ELSE 'LOW'
    END as severity
  FROM categorized_alerts
)

-- ============================================================================
-- Final output with enriched alert details
-- ============================================================================
SELECT
  metric_date,
  metric_name,
  metric_category,
  field_name,
  severity,
  metric_value,
  rolling_7d_avg,
  rolling_7d_stddev,
  pct_change_from_avg,
  trend_direction,
  deviation_from_avg,
  -- Generate human-readable alert message
  CASE
    WHEN severity = 'CRITICAL'
    THEN CONCAT('CRITICAL: ', metric_name, ' at ', CAST(metric_value AS STRING), '% (', CAST(deviation_from_avg AS STRING), ' stddev from avg)')
    WHEN severity = 'HIGH'
    THEN CONCAT('HIGH: ', metric_name, ' dropped to ', CAST(metric_value AS STRING), '% (', CAST(pct_change_from_avg AS STRING), '% change)')
    WHEN severity = 'MEDIUM'
    THEN CONCAT('MEDIUM: ', metric_name, ' declining at ', CAST(metric_value AS STRING), '%')
    ELSE CONCAT('LOW: ', metric_name, ' needs monitoring')
  END as alert_message,
  -- Days since metric was last healthy
  DATE_DIFF(
    CURRENT_DATE(),
    metric_date,
    DAY
  ) as days_since_alert,
  created_at
FROM alerts_with_severity
ORDER BY severity DESC, metric_date DESC, ABS(deviation_from_avg) DESC;

-- ============================================================================
-- EXAMPLE QUERIES
-- ============================================================================

-- Query 1: Current active alerts (last 3 days)
-- SELECT
--   metric_name,
--   metric_date,
--   severity,
--   metric_value,
--   rolling_7d_avg,
--   pct_change_from_avg,
--   alert_message
-- FROM `nba-props-platform.nba_monitoring.quality_trend_alerts`
-- WHERE metric_date >= CURRENT_DATE() - 3
-- ORDER BY severity DESC, metric_date DESC;

-- Query 2: Critical alerts requiring immediate attention
-- SELECT
--   metric_name,
--   metric_date,
--   metric_value,
--   rolling_7d_avg,
--   deviation_from_avg,
--   alert_message
-- FROM `nba-props-platform.nba_monitoring.quality_trend_alerts`
-- WHERE severity IN ('CRITICAL', 'HIGH')
--   AND metric_date >= CURRENT_DATE() - 7
-- ORDER BY severity DESC, metric_date DESC;

-- Query 3: Alerts by category (for targeted team notifications)
-- SELECT
--   metric_category,
--   COUNT(*) as alert_count,
--   ARRAY_AGG(DISTINCT metric_name ORDER BY metric_name LIMIT 10) as affected_metrics,
--   COUNTIF(severity = 'CRITICAL') as critical_count,
--   COUNTIF(severity = 'HIGH') as high_count
-- FROM `nba-props-platform.nba_monitoring.quality_trend_alerts`
-- WHERE metric_date >= CURRENT_DATE() - 7
-- GROUP BY metric_category
-- ORDER BY critical_count DESC, high_count DESC;

-- Query 4: Field completeness issues (for data quality team)
-- SELECT
--   field_name,
--   metric_date,
--   metric_value,
--   rolling_7d_avg,
--   pct_change_from_avg,
--   severity
-- FROM `nba-props-platform.nba_monitoring.quality_trend_alerts`
-- WHERE metric_category = 'Field Completeness'
--   AND metric_date >= CURRENT_DATE() - 7
-- ORDER BY severity DESC, metric_date DESC;

-- Query 5: Persistent alerts (same metric alerting multiple days)
-- SELECT
--   metric_name,
--   COUNT(DISTINCT metric_date) as alert_days,
--   MIN(metric_date) as first_alert_date,
--   MAX(metric_date) as latest_alert_date,
--   AVG(metric_value) as avg_metric_value,
--   MAX(severity) as max_severity
-- FROM `nba-props-platform.nba_monitoring.quality_trend_alerts`
-- WHERE metric_date >= CURRENT_DATE() - 30
-- GROUP BY metric_name
-- HAVING COUNT(DISTINCT metric_date) > 3
-- ORDER BY alert_days DESC, max_severity DESC;

-- ============================================================================
-- SLACK NOTIFICATION QUERY
-- ============================================================================
-- This query generates formatted messages for Slack alerts
--
-- SELECT
--   CONCAT(
--     '🚨 *Quality Alert - ', severity, '*\n',
--     '*Metric:* ', metric_name, '\n',
--     '*Date:* ', CAST(metric_date AS STRING), '\n',
--     '*Value:* ', CAST(metric_value AS STRING), '% (7-day avg: ', CAST(rolling_7d_avg AS STRING), '%)\n',
--     '*Change:* ', CAST(pct_change_from_avg AS STRING), '%\n',
--     '*Trend:* ', trend_direction, '\n',
--     '*Deviation:* ', CAST(deviation_from_avg AS STRING), ' standard deviations'
--   ) as slack_message
-- FROM `nba-props-platform.nba_monitoring.quality_trend_alerts`
-- WHERE metric_date = CURRENT_DATE() - 1
--   AND severity IN ('CRITICAL', 'HIGH')
-- ORDER BY severity DESC
-- LIMIT 5;

-- ============================================================================
-- EMAIL REPORT QUERY
-- ============================================================================
-- This query generates a daily summary for email reports
--
-- SELECT
--   metric_category,
--   severity,
--   metric_name,
--   metric_value,
--   rolling_7d_avg,
--   pct_change_from_avg,
--   trend_direction
-- FROM `nba-props-platform.nba_monitoring.quality_trend_alerts`
-- WHERE metric_date = CURRENT_DATE() - 1
-- ORDER BY
--   CASE severity
--     WHEN 'CRITICAL' THEN 1
--     WHEN 'HIGH' THEN 2
--     WHEN 'MEDIUM' THEN 3
--     ELSE 4
--   END,
--   metric_category,
--   metric_name;

-- ============================================================================
-- DASHBOARD WIDGET QUERIES
-- ============================================================================

-- Widget 1: Alert count by severity (gauge/number)
-- SELECT
--   severity,
--   COUNT(*) as count
-- FROM `nba-props-platform.nba_monitoring.quality_trend_alerts`
-- WHERE metric_date >= CURRENT_DATE() - 1
-- GROUP BY severity;

-- Widget 2: Alerts over time (time series)
-- SELECT
--   metric_date,
--   severity,
--   COUNT(*) as alert_count
-- FROM `nba-props-platform.nba_monitoring.quality_trend_alerts`
-- WHERE metric_date >= CURRENT_DATE() - 30
-- GROUP BY metric_date, severity
-- ORDER BY metric_date;

-- Widget 3: Top 5 problematic metrics (table)
-- SELECT
--   metric_name,
--   COUNT(DISTINCT metric_date) as days_alerting,
--   AVG(metric_value) as avg_value,
--   MAX(severity) as worst_severity
-- FROM `nba-props-platform.nba_monitoring.quality_trend_alerts`
-- WHERE metric_date >= CURRENT_DATE() - 30
-- GROUP BY metric_name
-- ORDER BY
--   CASE MAX(severity)
--     WHEN 'CRITICAL' THEN 1
--     WHEN 'HIGH' THEN 2
--     WHEN 'MEDIUM' THEN 3
--     ELSE 4
--   END,
--   days_alerting DESC
-- LIMIT 5;

-- ============================================================================
-- INTEGRATION WITH SMART ALERTING
-- ============================================================================
-- Use this view with monitoring/smart_alerting.py:
--
-- Python example:
-- ```python
-- from monitoring.smart_alerting import SmartAlertManager
--
-- query = """
-- SELECT
--   metric_name,
--   severity,
--   alert_message
-- FROM `nba-props-platform.nba_monitoring.quality_trend_alerts`
-- WHERE metric_date = CURRENT_DATE() - 1
--   AND severity IN ('CRITICAL', 'HIGH')
-- """
--
-- results = client.query(query).result()
-- for row in results:
--     alert_manager.send_alert(
--         alert_type='quality_degradation',
--         severity=row.severity,
--         message=row.alert_message,
--         metric_name=row.metric_name
--     )
-- ```
-- ============================================================================

-- ============================================================================
-- DEPLOYMENT CHECKLIST
-- ============================================================================
-- [ ] Ensure quality_trends table exists and is populated
-- [ ] Run CREATE VIEW for quality_trend_alerts
-- [ ] Verify view returns expected columns
-- [ ] Test example queries to ensure correct filtering
-- [ ] Integrate with Slack notification system
-- [ ] Add to daily email report generation
-- [ ] Create Grafana dashboard using widget queries
-- [ ] Set up scheduled check for CRITICAL alerts
-- [ ] Document alert response procedures
-- [ ] Train team on interpreting severity levels
-- ============================================================================

-- ============================================================================
-- VIEW SCHEMA
-- ============================================================================
-- Columns:
--   - metric_date: DATE - Date of the metric
--   - metric_name: STRING - Full metric identifier
--   - metric_category: STRING - Category (Field Completeness, Prediction Coverage, etc.)
--   - field_name: STRING - Field name for completeness metrics (NULL for others)
--   - severity: STRING - Alert severity (CRITICAL, HIGH, MEDIUM, LOW)
--   - metric_value: FLOAT64 - Current metric value
--   - rolling_7d_avg: FLOAT64 - 7-day rolling average
--   - rolling_7d_stddev: FLOAT64 - 7-day standard deviation
--   - pct_change_from_avg: FLOAT64 - Percentage change from average
--   - trend_direction: STRING - Trend classification (improving, stable, declining)
--   - deviation_from_avg: FLOAT64 - Standard deviations from average
--   - alert_message: STRING - Human-readable alert message
--   - days_since_alert: INT64 - Days since alert was triggered
--   - created_at: TIMESTAMP - When metric was calculated
-- ============================================================================
