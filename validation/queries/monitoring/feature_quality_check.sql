-- Feature Quality Health Check
-- Purpose: Compare recent ML feature values to 30-day baseline
-- Detects: Distribution collapse (fatigue_score=0 bug), gradual drift, range violations
-- Usage: Run daily via Cloud Function or manually for debugging
--
-- Created: 2026-01-30 (Session 47)
-- Author: Claude Opus 4.5

WITH feature_definitions AS (
  -- All 37 ML feature store features with expected ranges
  -- Indices match ml_feature_store_v2.features array
  SELECT * FROM UNNEST([
    STRUCT(0 AS idx, 'points_avg_last_5' AS name, 0.0 AS min_val, 80.0 AS max_val, 15.0 AS typical_mean),
    STRUCT(1, 'points_avg_last_10', 0.0, 80.0, 15.0),
    STRUCT(2, 'points_avg_season', 0.0, 60.0, 12.0),
    STRUCT(3, 'points_std_last_10', 0.0, 30.0, 5.0),
    STRUCT(4, 'games_in_last_7_days', 0.0, 7.0, 3.0),
    STRUCT(5, 'fatigue_score', 0.0, 100.0, 90.0),  -- CRITICAL: Bug detector
    STRUCT(6, 'shot_zone_mismatch_score', 0.0, 100.0, 50.0),
    STRUCT(7, 'pace_score', 0.0, 100.0, 50.0),
    STRUCT(8, 'usage_spike_score', 0.0, 100.0, 50.0),
    STRUCT(9, 'rest_advantage', -2.0, 2.0, 0.0),
    STRUCT(10, 'injury_risk', 0.0, 3.0, 0.2),
    STRUCT(11, 'recent_trend', -2.0, 2.0, 0.0),
    STRUCT(12, 'minutes_change', -2.0, 2.0, 0.0),
    STRUCT(13, 'opponent_def_rating', 95.0, 125.0, 110.0),
    STRUCT(14, 'opponent_pace', 95.0, 125.0, 100.0),
    STRUCT(15, 'home_away', 0.0, 1.0, 0.5),
    STRUCT(16, 'back_to_back', 0.0, 1.0, 0.15),
    STRUCT(17, 'playoff_game', 0.0, 1.0, 0.0),
    STRUCT(18, 'pct_paint', 0.0, 1.0, 0.35),
    STRUCT(19, 'pct_mid_range', 0.0, 1.0, 0.15),
    STRUCT(20, 'pct_three', 0.0, 1.0, 0.35),
    STRUCT(21, 'pct_free_throw', 0.0, 0.5, 0.15),
    STRUCT(22, 'team_pace_last_10', 95.0, 125.0, 100.0),
    STRUCT(23, 'team_off_rating_last_10', 95.0, 130.0, 110.0),
    STRUCT(24, 'team_win_pct', 0.0, 1.0, 0.5),
    STRUCT(25, 'vegas_points_line', -20.0, 50.0, 15.0),
    STRUCT(26, 'vegas_opening_line', -20.0, 50.0, 15.0),
    STRUCT(27, 'vegas_line_move', -10.0, 10.0, 0.0),
    STRUCT(28, 'has_vegas_line', 0.0, 1.0, 0.8),
    STRUCT(29, 'avg_points_vs_opponent', 0.0, 60.0, 12.0),
    STRUCT(30, 'games_vs_opponent', 0.0, 50.0, 5.0),
    STRUCT(31, 'minutes_avg_last_10', 0.0, 48.0, 25.0),  -- HIGH importance feature
    STRUCT(32, 'ppm_avg_last_10', 0.0, 1.5, 0.55),      -- HIGH importance feature
    STRUCT(33, 'dnp_rate', 0.0, 1.0, 0.1),
    STRUCT(34, 'pts_slope_10g', -5.0, 5.0, 0.0),
    STRUCT(35, 'pts_vs_season_zscore', -3.0, 3.0, 0.0),
    STRUCT(36, 'breakout_flag', 0.0, 1.0, 0.05)
  ])
),

baseline AS (
  -- Historical baseline: last 30 days (excluding last 3)
  -- Gives stable reference for comparison
  SELECT
    fd.idx,
    fd.name AS feature_name,
    fd.min_val,
    fd.max_val,
    fd.typical_mean,
    AVG(SAFE_CAST(features[SAFE_OFFSET(fd.idx)] AS FLOAT64)) AS baseline_mean,
    STDDEV(SAFE_CAST(features[SAFE_OFFSET(fd.idx)] AS FLOAT64)) AS baseline_stddev,
    APPROX_QUANTILES(SAFE_CAST(features[SAFE_OFFSET(fd.idx)] AS FLOAT64), 100)[OFFSET(5)] AS p5,
    APPROX_QUANTILES(SAFE_CAST(features[SAFE_OFFSET(fd.idx)] AS FLOAT64), 100)[OFFSET(50)] AS p50,
    APPROX_QUANTILES(SAFE_CAST(features[SAFE_OFFSET(fd.idx)] AS FLOAT64), 100)[OFFSET(95)] AS p95,
    COUNT(*) AS baseline_samples
  FROM `nba_predictions.ml_feature_store_v2`
  CROSS JOIN feature_definitions fd
  WHERE game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 33 DAY)
                      AND DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
    AND features IS NOT NULL
    AND ARRAY_LENGTH(features) > fd.idx
  GROUP BY fd.idx, fd.name, fd.min_val, fd.max_val, fd.typical_mean
),

recent AS (
  -- Recent window: last 3 days
  -- Short window to catch sudden changes quickly
  SELECT
    fd.idx,
    AVG(SAFE_CAST(features[SAFE_OFFSET(fd.idx)] AS FLOAT64)) AS recent_mean,
    MIN(SAFE_CAST(features[SAFE_OFFSET(fd.idx)] AS FLOAT64)) AS recent_min,
    MAX(SAFE_CAST(features[SAFE_OFFSET(fd.idx)] AS FLOAT64)) AS recent_max,
    STDDEV(SAFE_CAST(features[SAFE_OFFSET(fd.idx)] AS FLOAT64)) AS recent_stddev,
    COUNT(*) AS recent_samples,
    COUNTIF(SAFE_CAST(features[SAFE_OFFSET(fd.idx)] AS FLOAT64) = 0) AS zero_count,
    COUNTIF(features[SAFE_OFFSET(fd.idx)] IS NULL) AS null_count
  FROM `nba_predictions.ml_feature_store_v2`
  CROSS JOIN feature_definitions fd
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
    AND features IS NOT NULL
    AND ARRAY_LENGTH(features) > fd.idx
  GROUP BY fd.idx
),

analysis AS (
  SELECT
    b.feature_name,
    b.idx AS feature_index,

    -- Baseline statistics
    ROUND(b.baseline_mean, 3) AS baseline_mean,
    ROUND(b.baseline_stddev, 3) AS baseline_stddev,
    ROUND(b.p5, 3) AS baseline_p5,
    ROUND(b.p50, 3) AS baseline_p50,
    ROUND(b.p95, 3) AS baseline_p95,
    b.baseline_samples,

    -- Recent statistics
    ROUND(r.recent_mean, 3) AS recent_mean,
    ROUND(r.recent_min, 3) AS recent_min,
    ROUND(r.recent_max, 3) AS recent_max,
    ROUND(r.recent_stddev, 3) AS recent_stddev,
    r.recent_samples,
    r.zero_count,
    r.null_count,
    ROUND(SAFE_DIVIDE(r.zero_count, r.recent_samples) * 100, 1) AS zero_pct,

    -- Deviation metrics
    ROUND(SAFE_DIVIDE(r.recent_mean - b.baseline_mean, NULLIF(b.baseline_stddev, 0)), 2) AS z_score,
    ROUND(SAFE_DIVIDE(r.recent_mean - b.baseline_mean, NULLIF(b.baseline_mean, 0)) * 100, 1) AS pct_change,
    ROUND(ABS(r.recent_mean - b.typical_mean), 2) AS deviation_from_typical,

    -- Expected ranges
    b.min_val AS expected_min,
    b.max_val AS expected_max,
    b.typical_mean,

    -- Status determination
    CASE
      -- Critical: Extreme z-score (like fatigue_score=0)
      WHEN ABS(SAFE_DIVIDE(r.recent_mean - b.baseline_mean, NULLIF(b.baseline_stddev, 0))) > 3.0
        THEN 'CRITICAL'
      -- Critical: High zero rate for non-binary features
      WHEN SAFE_DIVIDE(r.zero_count, r.recent_samples) > 0.5
        AND b.typical_mean > 1.0  -- Not a 0/1 flag
        THEN 'CRITICAL_ZERO_COLLAPSE'
      -- Warning: Moderate z-score
      WHEN ABS(SAFE_DIVIDE(r.recent_mean - b.baseline_mean, NULLIF(b.baseline_stddev, 0))) > 2.0
        THEN 'WARNING'
      -- Warning: Range violations
      WHEN r.recent_min < b.min_val OR r.recent_max > b.max_val
        THEN 'RANGE_VIOLATION'
      -- Warning: Distribution collapse (low variance)
      WHEN SAFE_DIVIDE(r.recent_stddev, NULLIF(b.baseline_stddev, 0)) < 0.1
        AND b.baseline_stddev > 0.1
        THEN 'VARIANCE_COLLAPSE'
      -- Info: Trending
      WHEN ABS(SAFE_DIVIDE(r.recent_mean - b.baseline_mean, NULLIF(b.baseline_stddev, 0))) > 1.5
        THEN 'TRENDING'
      ELSE 'OK'
    END AS status

  FROM baseline b
  JOIN recent r ON b.idx = r.idx
)

-- Final output: All features with their health status
-- Order by severity (CRITICAL first) then by z-score magnitude
SELECT
  feature_name,
  feature_index,
  status,
  z_score,
  pct_change,
  baseline_mean,
  recent_mean,
  baseline_stddev,
  recent_stddev,
  zero_pct,
  baseline_samples,
  recent_samples,
  expected_min,
  expected_max,
  typical_mean,
  deviation_from_typical
FROM analysis
ORDER BY
  CASE status
    WHEN 'CRITICAL' THEN 1
    WHEN 'CRITICAL_ZERO_COLLAPSE' THEN 2
    WHEN 'WARNING' THEN 3
    WHEN 'RANGE_VIOLATION' THEN 4
    WHEN 'VARIANCE_COLLAPSE' THEN 5
    WHEN 'TRENDING' THEN 6
    ELSE 7
  END,
  ABS(z_score) DESC NULLS LAST
