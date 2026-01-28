-- ============================================================================
-- Scheduled Query: Update Quality Trends
-- Path: monitoring/scheduled_queries/update_quality_trends.sql
-- Created: 2026-01-27
-- ============================================================================
-- Purpose: Calculate daily quality metrics with rolling statistics and trend detection
-- Schedule: Run daily at 8:00 AM PT (after nightly processing completes)
-- Destination: nba_monitoring.quality_trends
-- ============================================================================
--
-- This query calculates key quality metrics and performs statistical analysis:
-- 1. Field completeness rates from player_game_summary
-- 2. Prediction coverage rates from predictions table
-- 3. Processing success rates from processor_run_history
-- 4. 7-day rolling averages and standard deviations
-- 5. Trend direction classification
-- 6. Alert triggering based on statistical anomalies
--
-- Setup Instructions:
-- 1. Ensure nba_monitoring.quality_trends table exists (run quality_trends.sql)
--
-- 2. Create scheduled query in Cloud Console or via bq CLI:
--    bq mk --transfer_config \
--      --project_id=nba-props-platform \
--      --data_source=scheduled_query \
--      --schedule='0 8 * * *' \
--      --schedule_timezone='America/Los_Angeles' \
--      --display_name='Update Quality Trends' \
--      --target_dataset=nba_monitoring \
--      --params='{
--        "query":"<THIS_QUERY>",
--        "destination_table_name_template":"quality_trends",
--        "write_disposition":"WRITE_APPEND",
--        "partitioning_type":"DAY"
--      }'
-- ============================================================================

-- ============================================================================
-- STEP 1: Calculate Field Completeness Metrics
-- ============================================================================
WITH field_completeness_metrics AS (
  SELECT
    game_date,
    -- Minutes Played (critical field - 99% threshold)
    'field_completeness_minutes_played' as metric_name,
    ROUND(COUNTIF(minutes_played IS NOT NULL) * 100.0 / COUNT(*), 2) as metric_value
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date = CURRENT_DATE() - 1
  GROUP BY game_date

  UNION ALL

  SELECT
    game_date,
    'field_completeness_usage_rate' as metric_name,
    ROUND(COUNTIF(usage_rate IS NOT NULL) * 100.0 / COUNT(*), 2) as metric_value
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date = CURRENT_DATE() - 1
  GROUP BY game_date

  UNION ALL

  SELECT
    game_date,
    'field_completeness_points' as metric_name,
    ROUND(COUNTIF(points IS NOT NULL) * 100.0 / COUNT(*), 2) as metric_value
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date = CURRENT_DATE() - 1
  GROUP BY game_date

  UNION ALL

  SELECT
    game_date,
    'field_completeness_assists' as metric_name,
    ROUND(COUNTIF(assists IS NOT NULL) * 100.0 / COUNT(*), 2) as metric_value
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date = CURRENT_DATE() - 1
  GROUP BY game_date

  UNION ALL

  SELECT
    game_date,
    'field_completeness_rebounds' as metric_name,
    ROUND(COUNTIF(offensive_rebounds IS NOT NULL AND defensive_rebounds IS NOT NULL) * 100.0 / COUNT(*), 2) as metric_value
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date = CURRENT_DATE() - 1
  GROUP BY game_date

  UNION ALL

  SELECT
    game_date,
    'field_completeness_paint_attempts' as metric_name,
    ROUND(COUNTIF(paint_attempts IS NOT NULL) * 100.0 / COUNT(*), 2) as metric_value
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date = CURRENT_DATE() - 1
  GROUP BY game_date

  UNION ALL

  SELECT
    game_date,
    'field_completeness_mid_range_attempts' as metric_name,
    ROUND(COUNTIF(mid_range_attempts IS NOT NULL) * 100.0 / COUNT(*), 2) as metric_value
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date = CURRENT_DATE() - 1
  GROUP BY game_date
),

-- ============================================================================
-- STEP 2: Calculate Prediction Coverage Metrics
-- ============================================================================
prediction_coverage_metrics AS (
  SELECT
    game_date,
    'prediction_coverage_overall' as metric_name,
    ROUND(COUNT(DISTINCT player_lookup) * 100.0 /
      (SELECT COUNT(DISTINCT player_lookup)
       FROM `nba-props-platform.nba_analytics.player_game_summary`
       WHERE game_date = CURRENT_DATE() - 1
         AND minutes_played >= 10), 2) as metric_value
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE game_date = CURRENT_DATE() - 1
    AND is_active = TRUE
  GROUP BY game_date

  UNION ALL

  SELECT
    game_date,
    'prediction_coverage_points' as metric_name,
    ROUND(COUNTIF(prop_type = 'points') * 100.0 /
      (SELECT COUNT(DISTINCT player_lookup)
       FROM `nba-props-platform.nba_analytics.player_game_summary`
       WHERE game_date = CURRENT_DATE() - 1
         AND minutes_played >= 10), 2) as metric_value
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE game_date = CURRENT_DATE() - 1
    AND is_active = TRUE
  GROUP BY game_date

  UNION ALL

  SELECT
    game_date,
    'prediction_coverage_assists' as metric_name,
    ROUND(COUNTIF(prop_type = 'assists') * 100.0 /
      (SELECT COUNT(DISTINCT player_lookup)
       FROM `nba-props-platform.nba_analytics.player_game_summary`
       WHERE game_date = CURRENT_DATE() - 1
         AND minutes_played >= 10), 2) as metric_value
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE game_date = CURRENT_DATE() - 1
    AND is_active = TRUE
  GROUP BY game_date
),

-- ============================================================================
-- STEP 3: Calculate Processing Success Rates
-- ============================================================================
processing_success_metrics AS (
  SELECT
    data_date as game_date,
    'processing_success_rate_phase3' as metric_name,
    ROUND(COUNTIF(status = 'success') * 100.0 / COUNT(*), 2) as metric_value
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE data_date = CURRENT_DATE() - 1
    AND phase = 'phase_3_analytics'
  GROUP BY data_date

  UNION ALL

  SELECT
    data_date as game_date,
    'processing_success_rate_phase4' as metric_name,
    ROUND(COUNTIF(status = 'success') * 100.0 / COUNT(*), 2) as metric_value
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE data_date = CURRENT_DATE() - 1
    AND phase = 'phase_4_precompute'
  GROUP BY data_date

  UNION ALL

  SELECT
    data_date as game_date,
    'processing_success_rate_overall' as metric_name,
    ROUND(COUNTIF(status = 'success') * 100.0 / COUNT(*), 2) as metric_value
  FROM `nba-props-platform.nba_reference.processor_run_history`
  WHERE data_date = CURRENT_DATE() - 1
  GROUP BY data_date
),

-- ============================================================================
-- STEP 4: Combine All Current Metrics
-- ============================================================================
current_metrics AS (
  SELECT * FROM field_completeness_metrics
  UNION ALL
  SELECT * FROM prediction_coverage_metrics
  UNION ALL
  SELECT * FROM processing_success_metrics
),

-- ============================================================================
-- STEP 5: Get Historical Data for Rolling Calculations
-- ============================================================================
historical_metrics AS (
  SELECT
    metric_date,
    metric_name,
    metric_value
  FROM `nba-props-platform.nba_monitoring.quality_trends`
  WHERE metric_date >= CURRENT_DATE() - 8
    AND metric_date < CURRENT_DATE() - 1
),

-- ============================================================================
-- STEP 6: Combine Current and Historical for Rolling Window
-- ============================================================================
all_metrics AS (
  SELECT
    game_date as metric_date,
    metric_name,
    metric_value
  FROM current_metrics

  UNION ALL

  SELECT
    metric_date,
    metric_name,
    metric_value
  FROM historical_metrics
),

-- ============================================================================
-- STEP 7: Calculate Rolling Statistics (7-Day Window)
-- ============================================================================
metrics_with_rolling_stats AS (
  SELECT
    metric_date,
    metric_name,
    metric_value,
    -- 7-day rolling average (including current day)
    AVG(metric_value) OVER (
      PARTITION BY metric_name
      ORDER BY metric_date
      ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) as rolling_7d_avg,
    -- 7-day rolling standard deviation
    STDDEV(metric_value) OVER (
      PARTITION BY metric_name
      ORDER BY metric_date
      ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) as rolling_7d_stddev,
    -- 3-day lag for trend comparison
    LAG(metric_value, 3) OVER (
      PARTITION BY metric_name
      ORDER BY metric_date
    ) as value_3d_ago
  FROM all_metrics
),

-- ============================================================================
-- STEP 8: Calculate Trend Direction and Deviations
-- ============================================================================
metrics_with_trends AS (
  SELECT
    metric_date,
    metric_name,
    metric_value,
    rolling_7d_avg,
    rolling_7d_stddev,
    -- Calculate deviation in standard deviations
    CASE
      WHEN rolling_7d_stddev > 0 AND rolling_7d_avg IS NOT NULL
      THEN (metric_value - rolling_7d_avg) / rolling_7d_stddev
      ELSE 0
    END as deviation_from_avg,
    -- Classify trend direction (comparing to 3 days ago)
    CASE
      WHEN value_3d_ago IS NULL THEN 'stable'
      WHEN metric_value > value_3d_ago + (0.02 * value_3d_ago) THEN 'improving'
      WHEN metric_value < value_3d_ago - (0.02 * value_3d_ago) THEN 'declining'
      ELSE 'stable'
    END as trend_direction
  FROM metrics_with_rolling_stats
),

-- ============================================================================
-- STEP 9: Apply Alert Logic
-- ============================================================================
final_metrics AS (
  SELECT
    metric_date,
    metric_name,
    ROUND(metric_value, 2) as metric_value,
    ROUND(rolling_7d_avg, 2) as rolling_7d_avg,
    ROUND(rolling_7d_stddev, 2) as rolling_7d_stddev,
    trend_direction,
    ROUND(deviation_from_avg, 2) as deviation_from_avg,
    -- Alert conditions:
    -- 1. Significant decline (>5% drop from 7-day avg)
    -- 2. Statistical anomaly (>2 stddev from average)
    -- 3. Declining trend with value below threshold
    CASE
      WHEN metric_value < rolling_7d_avg - (0.05 * rolling_7d_avg) THEN TRUE
      WHEN ABS(deviation_from_avg) > 2.0 THEN TRUE
      WHEN trend_direction = 'declining'
           AND metric_value < rolling_7d_avg - (0.03 * rolling_7d_avg) THEN TRUE
      ELSE FALSE
    END as alert_triggered
  FROM metrics_with_trends
)

-- ============================================================================
-- FINAL OUTPUT: Insert only today's metrics
-- ============================================================================
SELECT
  metric_date,
  metric_name,
  metric_value,
  rolling_7d_avg,
  rolling_7d_stddev,
  trend_direction,
  deviation_from_avg,
  alert_triggered,
  CURRENT_TIMESTAMP() as created_at
FROM final_metrics
WHERE metric_date = CURRENT_DATE() - 1
ORDER BY metric_name;

-- ============================================================================
-- EXPECTED OUTPUT
-- ============================================================================
-- This query will insert approximately 13 rows daily:
--   - 7 field completeness metrics
--   - 3 prediction coverage metrics
--   - 3 processing success metrics
--
-- Each row includes:
--   - Current metric value
--   - 7-day rolling average and standard deviation
--   - Trend direction (improving/stable/declining)
--   - Deviation from average (in standard deviations)
--   - Alert flag (TRUE if metric requires attention)
-- ============================================================================

-- ============================================================================
-- MONITORING AND VALIDATION
-- ============================================================================

-- Validation Query 1: Check today's run
-- SELECT
--   metric_name,
--   metric_value,
--   rolling_7d_avg,
--   trend_direction,
--   alert_triggered
-- FROM `nba-props-platform.nba_monitoring.quality_trends`
-- WHERE metric_date = CURRENT_DATE() - 1
-- ORDER BY alert_triggered DESC, metric_name;

-- Validation Query 2: Verify all expected metrics were calculated
-- SELECT
--   COUNT(DISTINCT metric_name) as unique_metrics,
--   COUNT(*) as total_rows,
--   COUNTIF(alert_triggered) as alerts_triggered
-- FROM `nba-props-platform.nba_monitoring.quality_trends`
-- WHERE metric_date = CURRENT_DATE() - 1;

-- Validation Query 3: Check for data gaps
-- SELECT
--   metric_name,
--   COUNT(DISTINCT metric_date) as days_with_data,
--   MIN(metric_date) as first_date,
--   MAX(metric_date) as last_date
-- FROM `nba-props-platform.nba_monitoring.quality_trends`
-- WHERE metric_date >= CURRENT_DATE() - 30
-- GROUP BY metric_name
-- HAVING COUNT(DISTINCT metric_date) < 30
-- ORDER BY days_with_data;

-- ============================================================================
-- DEPLOYMENT NOTES
-- ============================================================================
-- 1. This query should run AFTER nightly processing completes
--    Recommended: 8:00 AM PT daily
--
-- 2. Calculates metrics for CURRENT_DATE() - 1 (previous day)
--
-- 3. Requires at least 7 days of historical data for accurate rolling stats
--    - First 6 days will have partial rolling windows
--    - Alert thresholds may be less reliable during initial setup
--
-- 4. If scheduled query fails, gaps in data will affect future rolling calculations
--    - Monitor scheduled query execution in Cloud Console
--    - Set up alerts for failed scheduled query runs
--
-- 5. Performance considerations:
--    - Query processes ~7-14 days of data per run
--    - Typical execution time: 10-30 seconds
--    - Cost: Minimal (processes <100MB per run)
-- ============================================================================
