-- Extended League Trend Monitoring Views
-- Additional views for comprehensive trend analysis
-- Created: 2026-01-30

-- ============================================================================
-- VIEW 8: Starter vs Bench Performance Trends
-- Uses actual starter_flag from player_game_summary when available
-- ============================================================================
CREATE OR REPLACE VIEW `nba_trend_monitoring.starter_bench_trends` AS
WITH player_roles AS (
  SELECT
    pa.game_date,
    pa.player_lookup,
    pa.predicted_points,
    pa.actual_points,
    pa.line_value,
    pa.recommendation,
    pa.prediction_correct,
    pa.confidence_score,
    -- Try to get starter status from analytics
    COALESCE(
      pgs.starter_flag,
      -- Fallback: infer from line (starters typically have higher lines)
      pa.line_value >= 12
    ) as is_starter
  FROM `nba_predictions.prediction_accuracy` pa
  LEFT JOIN `nba_analytics.player_game_summary` pgs
    ON pa.player_lookup = pgs.player_lookup AND pa.game_date = pgs.game_date
  WHERE pa.actual_points IS NOT NULL
    AND pa.actual_points > 0
    AND pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
    AND pa.system_id = 'catboost_v8'
)
SELECT
  DATE_TRUNC(game_date, WEEK(MONDAY)) as week_start,
  CASE WHEN is_starter THEN 'starter' ELSE 'bench' END as player_role,
  COUNT(*) as predictions,

  -- Scoring
  ROUND(AVG(actual_points), 1) as avg_actual,
  ROUND(AVG(predicted_points), 1) as avg_predicted,
  ROUND(AVG(line_value), 1) as avg_line,
  ROUND(AVG(predicted_points - actual_points), 2) as prediction_bias,

  -- Hit rates
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'OVER') /
        NULLIF(COUNTIF(prediction_correct IS NOT NULL AND recommendation = 'OVER'), 0), 1) as over_hit_rate,
  ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'UNDER') /
        NULLIF(COUNTIF(prediction_correct IS NOT NULL AND recommendation = 'UNDER'), 0), 1) as under_hit_rate,

  -- Recommendation balance
  ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) as pct_over_recs

FROM player_roles
GROUP BY week_start, player_role
ORDER BY week_start DESC, player_role;


-- ============================================================================
-- VIEW 9: Usage Rate Impact Trends
-- Tracks how high-usage vs low-usage players perform differently
-- ============================================================================
CREATE OR REPLACE VIEW `nba_trend_monitoring.usage_rate_trends` AS
WITH with_usage AS (
  SELECT
    pa.*,
    pgs.usage_rate,
    CASE
      WHEN pgs.usage_rate >= 0.28 THEN 'high_usage'
      WHEN pgs.usage_rate >= 0.20 THEN 'medium_usage'
      WHEN pgs.usage_rate >= 0.12 THEN 'low_usage'
      ELSE 'minimal_usage'
    END as usage_tier
  FROM `nba_predictions.prediction_accuracy` pa
  LEFT JOIN `nba_analytics.player_game_summary` pgs
    ON pa.player_lookup = pgs.player_lookup AND pa.game_date = pgs.game_date
  WHERE pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
    AND pa.system_id = 'catboost_v8'
    AND pa.actual_points IS NOT NULL
    AND pa.actual_points > 0
    AND pgs.usage_rate IS NOT NULL
)
SELECT
  DATE_TRUNC(game_date, WEEK(MONDAY)) as week_start,
  usage_tier,
  COUNT(*) as predictions,

  -- Scoring
  ROUND(AVG(actual_points), 1) as avg_actual,
  ROUND(AVG(predicted_points), 1) as avg_predicted,
  ROUND(AVG(predicted_points - actual_points), 2) as prediction_bias,

  -- Hit rate
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,

  -- Usage stats
  ROUND(AVG(usage_rate) * 100, 1) as avg_usage_pct

FROM with_usage
WHERE usage_tier IS NOT NULL
GROUP BY week_start, usage_tier
ORDER BY week_start DESC, usage_tier;


-- ============================================================================
-- VIEW 10: Home vs Away Performance Trends
-- ============================================================================
CREATE OR REPLACE VIEW `nba_trend_monitoring.home_away_trends` AS
WITH with_location AS (
  SELECT
    pa.*,
    fs.is_home
  FROM `nba_predictions.prediction_accuracy` pa
  LEFT JOIN `nba_predictions.ml_feature_store_v2` fs
    ON pa.player_lookup = fs.player_lookup AND pa.game_date = fs.game_date
  WHERE pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
    AND pa.system_id = 'catboost_v8'
    AND pa.actual_points IS NOT NULL
    AND pa.actual_points > 0
)
SELECT
  DATE_TRUNC(game_date, WEEK(MONDAY)) as week_start,
  CASE WHEN is_home THEN 'home' ELSE 'away' END as location,
  COUNT(*) as predictions,

  -- Scoring
  ROUND(AVG(actual_points), 1) as avg_actual,
  ROUND(AVG(predicted_points), 1) as avg_predicted,
  ROUND(AVG(predicted_points - actual_points), 2) as prediction_bias,

  -- Hit rate
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,

  -- Over/Under
  ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'OVER') /
        NULLIF(COUNTIF(prediction_correct IS NOT NULL AND recommendation = 'OVER'), 0), 1) as over_hit_rate,
  ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'UNDER') /
        NULLIF(COUNTIF(prediction_correct IS NOT NULL AND recommendation = 'UNDER'), 0), 1) as under_hit_rate

FROM with_location
WHERE is_home IS NOT NULL
GROUP BY week_start, location
ORDER BY week_start DESC, location;


-- ============================================================================
-- VIEW 11: Underperforming Star Tracker
-- Identifies star players consistently missing predictions
-- ============================================================================
CREATE OR REPLACE VIEW `nba_trend_monitoring.underperforming_stars` AS
WITH recent_star_performance AS (
  SELECT
    player_lookup,
    game_date,
    predicted_points,
    actual_points,
    line_value,
    predicted_points - actual_points as over_prediction,
    prediction_correct
  FROM `nba_predictions.prediction_accuracy`
  WHERE line_value >= 18  -- Star threshold
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 21 DAY)
    AND system_id = 'catboost_v8'
    AND actual_points IS NOT NULL
)
SELECT
  player_lookup,
  COUNT(*) as games,
  ROUND(AVG(predicted_points), 1) as avg_predicted,
  ROUND(AVG(actual_points), 1) as avg_actual,
  ROUND(AVG(line_value), 1) as avg_line,
  ROUND(AVG(over_prediction), 2) as avg_over_prediction,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  COUNTIF(actual_points = 0) as dnp_games,
  -- Trend direction (is bias getting worse?)
  ROUND(AVG(CASE WHEN game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) THEN over_prediction END), 2) as recent_bias,
  ROUND(AVG(CASE WHEN game_date < DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) THEN over_prediction END), 2) as older_bias
FROM recent_star_performance
GROUP BY player_lookup
HAVING COUNT(*) >= 3
ORDER BY avg_over_prediction DESC;


-- ============================================================================
-- VIEW 12: Hot/Cold Streak Tracker
-- Identifies players on scoring streaks vs cold spells
-- ============================================================================
CREATE OR REPLACE VIEW `nba_trend_monitoring.player_streaks` AS
WITH player_recent AS (
  SELECT
    player_lookup,
    game_date,
    actual_points,
    line_value,
    actual_points - line_value as vs_line,
    CASE WHEN actual_points > line_value THEN 1 ELSE 0 END as over_line
  FROM `nba_predictions.prediction_accuracy`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
    AND actual_points IS NOT NULL
    AND actual_points > 0
    AND line_value >= 10  -- Meaningful lines only
    AND system_id = 'catboost_v8'
),
player_stats AS (
  SELECT
    player_lookup,
    COUNT(*) as games,
    ROUND(AVG(actual_points), 1) as avg_actual,
    ROUND(AVG(line_value), 1) as avg_line,
    ROUND(AVG(vs_line), 2) as avg_vs_line,
    SUM(over_line) as times_over,
    COUNT(*) - SUM(over_line) as times_under,
    -- Consecutive overs/unders (approximation using recent games)
    ROUND(100.0 * SUM(over_line) / COUNT(*), 1) as over_pct
  FROM player_recent
  GROUP BY player_lookup
  HAVING COUNT(*) >= 4
)
SELECT
  *,
  CASE
    WHEN over_pct >= 75 THEN 'HOT_STREAK'
    WHEN over_pct <= 25 THEN 'COLD_STREAK'
    ELSE 'NEUTRAL'
  END as streak_status,
  CASE
    WHEN avg_vs_line >= 3 THEN 'OUTPERFORMING'
    WHEN avg_vs_line <= -3 THEN 'UNDERPERFORMING'
    ELSE 'ON_TARGET'
  END as performance_status
FROM player_stats
ORDER BY avg_vs_line DESC;


-- ============================================================================
-- VIEW 13: Weekly Trend Change Detection
-- Highlights significant week-over-week changes
-- ============================================================================
CREATE OR REPLACE VIEW `nba_trend_monitoring.trend_changes` AS
WITH weekly_metrics AS (
  SELECT
    DATE_TRUNC(game_date, WEEK(MONDAY)) as week_start,
    ROUND(AVG(actual_points), 2) as avg_points,
    ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
    ROUND(AVG(predicted_points - actual_points), 2) as bias,
    ROUND(100.0 * COUNTIF(actual_points > line_value) / NULLIF(COUNTIF(actual_points IS NOT NULL), 0), 1) as overs_hitting
  FROM `nba_predictions.prediction_accuracy`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
    AND system_id = 'catboost_v8'
    AND actual_points IS NOT NULL
    AND actual_points > 0
  GROUP BY week_start
),
with_changes AS (
  SELECT
    *,
    avg_points - LAG(avg_points) OVER (ORDER BY week_start) as points_change,
    hit_rate - LAG(hit_rate) OVER (ORDER BY week_start) as hit_rate_change,
    bias - LAG(bias) OVER (ORDER BY week_start) as bias_change,
    overs_hitting - LAG(overs_hitting) OVER (ORDER BY week_start) as overs_change
  FROM weekly_metrics
)
SELECT
  *,
  -- Flag significant changes
  CASE
    WHEN ABS(points_change) >= 1.5 THEN 'SIGNIFICANT'
    WHEN ABS(points_change) >= 0.75 THEN 'NOTABLE'
    ELSE 'NORMAL'
  END as points_change_flag,
  CASE
    WHEN ABS(hit_rate_change) >= 10 THEN 'SIGNIFICANT'
    WHEN ABS(hit_rate_change) >= 5 THEN 'NOTABLE'
    ELSE 'NORMAL'
  END as hit_rate_change_flag,
  CASE
    WHEN ABS(bias_change) >= 2 THEN 'SIGNIFICANT'
    WHEN ABS(bias_change) >= 1 THEN 'NOTABLE'
    ELSE 'NORMAL'
  END as bias_change_flag
FROM with_changes
WHERE week_start >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY week_start DESC;


-- ============================================================================
-- VIEW 14: Monthly Seasonal Baseline
-- Establishes expected ranges by month for seasonal comparison
-- ============================================================================
CREATE OR REPLACE VIEW `nba_trend_monitoring.monthly_baselines` AS
SELECT
  EXTRACT(MONTH FROM game_date) as month_num,
  FORMAT_DATE('%B', game_date) as month_name,
  COUNT(*) as total_predictions,
  ROUND(AVG(actual_points), 2) as baseline_avg_points,
  ROUND(STDDEV(actual_points), 2) as baseline_std_points,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as baseline_hit_rate,
  ROUND(AVG(predicted_points - actual_points), 2) as baseline_bias,
  ROUND(100.0 * COUNTIF(actual_points > line_value) / NULLIF(COUNTIF(actual_points IS NOT NULL), 0), 1) as baseline_overs_pct
FROM `nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY)
  AND actual_points IS NOT NULL
  AND actual_points > 0
GROUP BY month_num, month_name
ORDER BY month_num;
