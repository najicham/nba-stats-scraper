-- Feature Health Daily Monitoring Table
-- Created: 2026-01-31
-- Purpose: Track daily feature quality statistics for early anomaly detection
--
-- This table enables:
-- 1. Detecting feature quality issues within 24 hours (vs 5+ days via model degradation)
-- 2. Tracking feature distributions over time
-- 3. Alerting on anomalies (zeros, out-of-range, mean drift)
--
-- Populated by: Scheduled query (daily at 6 AM ET)
-- Retention: 90 days rolling

-- Note: Table is in nba_monitoring_west2 dataset (us-west2 region) to match source tables
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_monitoring_west2.feature_health_daily` (
  -- Primary key
  report_date DATE NOT NULL,
  feature_name STRING NOT NULL,
  source_table STRING NOT NULL,  -- 'player_composite_factors', 'ml_feature_store_v2'

  -- Distribution statistics
  mean FLOAT64,
  stddev FLOAT64,
  min_value FLOAT64,
  max_value FLOAT64,
  p5 FLOAT64,
  p25 FLOAT64,
  p50 FLOAT64,  -- median
  p75 FLOAT64,
  p95 FLOAT64,

  -- Record counts
  total_records INT64,
  null_count INT64,
  zero_count INT64,
  negative_count INT64,
  out_of_range_count INT64,

  -- Percentages
  null_pct FLOAT64,
  zero_pct FLOAT64,
  out_of_range_pct FLOAT64,

  -- Baseline comparison (30-day rolling average)
  baseline_mean FLOAT64,
  baseline_stddev FLOAT64,
  mean_change_pct FLOAT64,  -- (current_mean - baseline_mean) / baseline_mean * 100

  -- Expected ranges (from FEATURE_RANGES config)
  expected_min FLOAT64,
  expected_max FLOAT64,

  -- Health status
  health_status STRING,  -- 'healthy', 'warning', 'critical'
  alert_reasons ARRAY<STRING>,

  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY report_date
CLUSTER BY feature_name, source_table
OPTIONS (
  description = 'Daily feature quality metrics for ML feature monitoring',
  labels = [('domain', 'monitoring'), ('retention', '90d')]
);

-- =============================================================================
-- DAILY POPULATION QUERY
-- =============================================================================
-- Run this as a scheduled query daily at 6 AM ET
-- Analyzes previous day's data from player_composite_factors and ml_feature_store_v2

-- Part 1: Player Composite Factors features
INSERT INTO `nba-props-platform.nba_monitoring_west2.feature_health_daily`
WITH feature_stats AS (
  SELECT
    DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) as report_date,
    'player_composite_factors' as source_table,
    feature_name,
    AVG(value) as mean,
    STDDEV(value) as stddev,
    MIN(value) as min_value,
    MAX(value) as max_value,
    APPROX_QUANTILES(value, 100)[OFFSET(5)] as p5,
    APPROX_QUANTILES(value, 100)[OFFSET(25)] as p25,
    APPROX_QUANTILES(value, 100)[OFFSET(50)] as p50,
    APPROX_QUANTILES(value, 100)[OFFSET(75)] as p75,
    APPROX_QUANTILES(value, 100)[OFFSET(95)] as p95,
    COUNT(*) as total_records,
    COUNTIF(value IS NULL) as null_count,
    COUNTIF(value = 0) as zero_count,
    COUNTIF(value < 0) as negative_count
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  CROSS JOIN UNNEST([
    STRUCT('fatigue_score' as feature_name, fatigue_score as value, 0.0 as expected_min, 100.0 as expected_max),
    STRUCT('shot_zone_mismatch_score', shot_zone_mismatch_score, -15.0, 15.0),
    STRUCT('pace_score', pace_score, -8.0, 8.0),
    STRUCT('usage_spike_score', usage_spike_score, -8.0, 8.0)
  ]) as f
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
  GROUP BY feature_name
),
baselines AS (
  SELECT
    feature_name,
    AVG(value) as baseline_mean,
    STDDEV(value) as baseline_stddev
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  CROSS JOIN UNNEST([
    STRUCT('fatigue_score' as feature_name, fatigue_score as value),
    STRUCT('shot_zone_mismatch_score', shot_zone_mismatch_score),
    STRUCT('pace_score', pace_score),
    STRUCT('usage_spike_score', usage_spike_score)
  ]) as f
  WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 31 DAY)
                      AND DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY)
  GROUP BY feature_name
),
expected_ranges AS (
  SELECT * FROM UNNEST([
    STRUCT('fatigue_score' as feature_name, 0.0 as expected_min, 100.0 as expected_max, 80.0 as warn_min, 10.0 as zero_warn_pct),
    STRUCT('shot_zone_mismatch_score', -15.0, 15.0, -10.0, 50.0),
    STRUCT('pace_score', -8.0, 8.0, -5.0, 50.0),
    STRUCT('usage_spike_score', -8.0, 8.0, -5.0, 50.0)
  ])
)
SELECT
  s.report_date,
  s.feature_name,
  s.source_table,
  s.mean,
  s.stddev,
  s.min_value,
  s.max_value,
  s.p5,
  s.p25,
  s.p50,
  s.p75,
  s.p95,
  s.total_records,
  s.null_count,
  s.zero_count,
  s.negative_count,
  COUNTIF(
    CASE
      WHEN s.feature_name = 'fatigue_score' THEN value < 0 OR value > 100
      WHEN s.feature_name = 'shot_zone_mismatch_score' THEN value < -15 OR value > 15
      WHEN s.feature_name = 'pace_score' THEN value < -8 OR value > 8
      WHEN s.feature_name = 'usage_spike_score' THEN value < -8 OR value > 8
      ELSE FALSE
    END
  ) as out_of_range_count,
  SAFE_DIVIDE(s.null_count, s.total_records) * 100 as null_pct,
  SAFE_DIVIDE(s.zero_count, s.total_records) * 100 as zero_pct,
  0.0 as out_of_range_pct,  -- Calculated below
  b.baseline_mean,
  b.baseline_stddev,
  SAFE_DIVIDE(s.mean - b.baseline_mean, b.baseline_mean) * 100 as mean_change_pct,
  e.expected_min,
  e.expected_max,
  CASE
    -- Critical conditions
    WHEN s.feature_name = 'fatigue_score' AND SAFE_DIVIDE(s.zero_count, s.total_records) > 0.10 THEN 'critical'
    WHEN s.feature_name = 'fatigue_score' AND s.mean < 50 THEN 'critical'
    WHEN s.negative_count > 0 AND s.feature_name = 'fatigue_score' THEN 'critical'
    -- Warning conditions
    WHEN SAFE_DIVIDE(s.zero_count, s.total_records) > e.zero_warn_pct / 100 THEN 'warning'
    WHEN ABS(SAFE_DIVIDE(s.mean - b.baseline_mean, b.baseline_mean)) > 0.20 THEN 'warning'
    WHEN s.min_value < e.expected_min OR s.max_value > e.expected_max THEN 'warning'
    ELSE 'healthy'
  END as health_status,
  ARRAY_CONCAT(
    IF(s.feature_name = 'fatigue_score' AND SAFE_DIVIDE(s.zero_count, s.total_records) > 0.10,
       ['Zero count >10%'], []),
    IF(s.feature_name = 'fatigue_score' AND s.mean < 50,
       ['Mean < 50 (expected ~90-100)'], []),
    IF(s.negative_count > 0 AND s.feature_name = 'fatigue_score',
       ['Negative values found'], []),
    IF(ABS(SAFE_DIVIDE(s.mean - b.baseline_mean, b.baseline_mean)) > 0.20,
       [CONCAT('Mean drift: ', CAST(ROUND(SAFE_DIVIDE(s.mean - b.baseline_mean, b.baseline_mean) * 100, 1) AS STRING), '%')], [])
  ) as alert_reasons,
  CURRENT_TIMESTAMP() as created_at
FROM feature_stats s
LEFT JOIN baselines b USING (feature_name)
LEFT JOIN expected_ranges e USING (feature_name);
