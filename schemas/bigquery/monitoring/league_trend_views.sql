-- League Trend Monitoring Views
-- Purpose: Early warning system for model drift by tracking league-wide and cohort-level trends
-- Created: 2026-01-30
--
-- These views power the League Trends dashboard and /trend-check skill.
-- They aggregate prediction_accuracy data into weekly trends by various dimensions.

-- ============================================================================
-- VIEW 1: League Scoring Environment Trends
-- Tracks overall scoring patterns to detect league-wide shifts
-- ============================================================================
CREATE OR REPLACE VIEW `nba_trend_monitoring.league_scoring_trends` AS
WITH weekly_stats AS (
  SELECT
    DATE_TRUNC(game_date, WEEK(MONDAY)) as week_start,
    COUNT(DISTINCT game_id) as games,
    COUNT(DISTINCT player_lookup) as players,
    COUNT(*) as predictions,

    -- Scoring metrics
    ROUND(AVG(actual_points), 2) as avg_points,
    ROUND(STDDEV(actual_points), 2) as scoring_volatility,
    ROUND(PERCENTILE_CONT(actual_points, 0.5) OVER (PARTITION BY DATE_TRUNC(game_date, WEEK(MONDAY))), 1) as median_points,

    -- Line accuracy (how well do sportsbooks predict?)
    ROUND(AVG(ABS(actual_points - line_value)), 2) as line_mae,
    ROUND(AVG(actual_points - line_value), 2) as line_bias,

    -- Over/Under market balance
    ROUND(100.0 * COUNTIF(actual_points > line_value) / NULLIF(COUNTIF(actual_points IS NOT NULL), 0), 1) as pct_overs_hitting,

    -- Zero-point games (DNP/injury indicator)
    COUNTIF(actual_points = 0) as zero_point_games,
    ROUND(100.0 * COUNTIF(actual_points = 0) / COUNT(*), 1) as zero_point_pct

  FROM `nba_predictions.prediction_accuracy`
  WHERE actual_points IS NOT NULL
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
  GROUP BY week_start
),
with_changes AS (
  SELECT
    *,
    -- Week-over-week changes
    avg_points - LAG(avg_points) OVER (ORDER BY week_start) as avg_points_change,
    scoring_volatility - LAG(scoring_volatility) OVER (ORDER BY week_start) as volatility_change,
    pct_overs_hitting - LAG(pct_overs_hitting) OVER (ORDER BY week_start) as overs_pct_change,
    -- 4-week rolling baseline
    AVG(avg_points) OVER (ORDER BY week_start ROWS BETWEEN 4 PRECEDING AND 1 PRECEDING) as baseline_avg_points
  FROM weekly_stats
)
SELECT
  *,
  -- Alert flags
  CASE
    WHEN ABS(avg_points - baseline_avg_points) / NULLIF(baseline_avg_points, 0) > 0.10 THEN 'WARNING'
    WHEN ABS(avg_points - baseline_avg_points) / NULLIF(baseline_avg_points, 0) > 0.15 THEN 'CRITICAL'
    ELSE 'OK'
  END as scoring_alert,
  CASE
    WHEN pct_overs_hitting < 45 OR pct_overs_hitting > 55 THEN 'WARNING'
    WHEN pct_overs_hitting < 40 OR pct_overs_hitting > 60 THEN 'CRITICAL'
    ELSE 'OK'
  END as market_balance_alert
FROM with_changes
ORDER BY week_start DESC;


-- ============================================================================
-- VIEW 2: Player Cohort Performance Trends
-- Tracks star players, starters, and bench players separately
-- ============================================================================
CREATE OR REPLACE VIEW `nba_trend_monitoring.cohort_performance_trends` AS
WITH categorized AS (
  SELECT
    DATE_TRUNC(game_date, WEEK(MONDAY)) as week_start,
    -- Player cohort classification
    CASE
      WHEN line_value >= 20 THEN 'star'
      WHEN line_value >= 12 THEN 'starter'
      WHEN line_value >= 7 THEN 'rotation'
      ELSE 'bench'
    END as player_cohort,
    predicted_points,
    actual_points,
    line_value,
    recommendation,
    prediction_correct,
    confidence_score
  FROM `nba_predictions.prediction_accuracy`
  WHERE actual_points IS NOT NULL
    AND actual_points > 0  -- Exclude DNP
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
    AND system_id = 'catboost_v8'
)
SELECT
  week_start,
  player_cohort,
  COUNT(*) as predictions,

  -- Scoring
  ROUND(AVG(actual_points), 1) as avg_actual,
  ROUND(AVG(predicted_points), 1) as avg_predicted,
  ROUND(AVG(line_value), 1) as avg_line,

  -- Bias
  ROUND(AVG(predicted_points - actual_points), 2) as prediction_bias,
  ROUND(AVG(actual_points - line_value), 2) as vs_line_performance,

  -- Hit rate
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,

  -- Confidence
  ROUND(AVG(confidence_score), 3) as avg_confidence,

  -- Recommendation breakdown
  COUNTIF(recommendation = 'OVER') as over_count,
  COUNTIF(recommendation = 'UNDER') as under_count,
  COUNTIF(recommendation = 'PASS') as pass_count,

  -- OVER/UNDER specific hit rates
  ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'OVER') /
        NULLIF(COUNTIF(prediction_correct IS NOT NULL AND recommendation = 'OVER'), 0), 1) as over_hit_rate,
  ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'UNDER') /
        NULLIF(COUNTIF(prediction_correct IS NOT NULL AND recommendation = 'UNDER'), 0), 1) as under_hit_rate

FROM categorized
GROUP BY week_start, player_cohort
ORDER BY week_start DESC, player_cohort;


-- ============================================================================
-- VIEW 3: Model Health Trends
-- Tracks confidence calibration, bias, and recommendation patterns
-- ============================================================================
CREATE OR REPLACE VIEW `nba_trend_monitoring.model_health_trends` AS
WITH weekly_metrics AS (
  SELECT
    DATE_TRUNC(game_date, WEEK(MONDAY)) as week_start,

    -- Overall metrics
    COUNT(*) as total_predictions,
    COUNTIF(prediction_correct IS NOT NULL) as graded_predictions,
    ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as overall_hit_rate,

    -- Prediction bias
    ROUND(AVG(predicted_points - actual_points), 2) as overall_bias,
    ROUND(AVG(CASE WHEN recommendation = 'OVER' THEN predicted_points - actual_points END), 2) as over_bias,
    ROUND(AVG(CASE WHEN recommendation = 'UNDER' THEN predicted_points - actual_points END), 2) as under_bias,

    -- Confidence calibration by bucket
    ROUND(100.0 * COUNTIF(prediction_correct AND confidence_score >= 0.90) /
          NULLIF(COUNTIF(prediction_correct IS NOT NULL AND confidence_score >= 0.90), 0), 1) as conf_90_hit_rate,
    ROUND(100.0 * COUNTIF(prediction_correct AND confidence_score >= 0.85 AND confidence_score < 0.90) /
          NULLIF(COUNTIF(prediction_correct IS NOT NULL AND confidence_score >= 0.85 AND confidence_score < 0.90), 0), 1) as conf_85_90_hit_rate,
    ROUND(100.0 * COUNTIF(prediction_correct AND confidence_score >= 0.80 AND confidence_score < 0.85) /
          NULLIF(COUNTIF(prediction_correct IS NOT NULL AND confidence_score >= 0.80 AND confidence_score < 0.85), 0), 1) as conf_80_85_hit_rate,

    -- Confidence distribution
    COUNTIF(confidence_score >= 0.90) as conf_90_count,
    COUNTIF(confidence_score >= 0.85 AND confidence_score < 0.90) as conf_85_90_count,
    COUNTIF(confidence_score >= 0.80 AND confidence_score < 0.85) as conf_80_85_count,
    COUNTIF(confidence_score < 0.80) as conf_below_80_count,

    -- Recommendation balance
    ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) as pct_over_recs,
    ROUND(100.0 * COUNTIF(recommendation = 'UNDER') / COUNT(*), 1) as pct_under_recs,
    ROUND(100.0 * COUNTIF(recommendation = 'PASS') / COUNT(*), 1) as pct_pass_recs,

    -- OVER vs UNDER hit rates
    ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'OVER') /
          NULLIF(COUNTIF(prediction_correct IS NOT NULL AND recommendation = 'OVER'), 0), 1) as over_hit_rate,
    ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'UNDER') /
          NULLIF(COUNTIF(prediction_correct IS NOT NULL AND recommendation = 'UNDER'), 0), 1) as under_hit_rate,

    -- Error metrics
    ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae,
    ROUND(STDDEV(predicted_points - actual_points), 2) as error_std

  FROM `nba_predictions.prediction_accuracy`
  WHERE actual_points IS NOT NULL
    AND actual_points > 0  -- Exclude DNP
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
    AND system_id = 'catboost_v8'
  GROUP BY week_start
)
SELECT
  *,
  -- Calibration error (difference between confidence and actual hit rate)
  ABS(90 - COALESCE(conf_90_hit_rate, 0)) as conf_90_calibration_error,
  ABS(87.5 - COALESCE(conf_85_90_hit_rate, 0)) as conf_85_90_calibration_error,
  ABS(82.5 - COALESCE(conf_80_85_hit_rate, 0)) as conf_80_85_calibration_error,

  -- Alert flags
  CASE
    WHEN ABS(overall_bias) > 3 THEN 'CRITICAL'
    WHEN ABS(overall_bias) > 2 THEN 'WARNING'
    ELSE 'OK'
  END as bias_alert,
  CASE
    WHEN conf_90_hit_rate < 60 THEN 'CRITICAL'
    WHEN conf_90_hit_rate < 70 THEN 'WARNING'
    ELSE 'OK'
  END as calibration_alert,
  CASE
    WHEN ABS(over_hit_rate - under_hit_rate) > 20 THEN 'WARNING'
    WHEN ABS(over_hit_rate - under_hit_rate) > 30 THEN 'CRITICAL'
    ELSE 'OK'
  END as recommendation_balance_alert

FROM weekly_metrics
ORDER BY week_start DESC;


-- ============================================================================
-- VIEW 4: Daily Trend Summary (for quick checks)
-- Provides a daily snapshot for the last 30 days
-- ============================================================================
CREATE OR REPLACE VIEW `nba_trend_monitoring.daily_trend_summary` AS
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNTIF(prediction_correct IS NOT NULL) as graded,

  -- Hit rate
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,

  -- Scoring
  ROUND(AVG(actual_points), 1) as avg_actual,
  ROUND(AVG(predicted_points), 1) as avg_predicted,
  ROUND(AVG(predicted_points - actual_points), 2) as bias,

  -- Confidence
  ROUND(AVG(confidence_score), 3) as avg_confidence,

  -- Recommendation breakdown
  ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) as pct_over,
  ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'OVER') /
        NULLIF(COUNTIF(prediction_correct IS NOT NULL AND recommendation = 'OVER'), 0), 1) as over_hit_rate,
  ROUND(100.0 * COUNTIF(prediction_correct AND recommendation = 'UNDER') /
        NULLIF(COUNTIF(prediction_correct IS NOT NULL AND recommendation = 'UNDER'), 0), 1) as under_hit_rate,

  -- DNP tracking
  COUNTIF(actual_points = 0) as dnp_count

FROM `nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND system_id = 'catboost_v8'
  AND actual_points IS NOT NULL
GROUP BY game_date
ORDER BY game_date DESC;


-- ============================================================================
-- VIEW 5: Trend Alerts Summary
-- Aggregates all alerts into a single view for easy monitoring
-- ============================================================================
CREATE OR REPLACE VIEW `nba_trend_monitoring.trend_alerts_summary` AS
WITH latest_week AS (
  SELECT MAX(week_start) as latest FROM `nba_trend_monitoring.league_scoring_trends`
),
scoring_alerts AS (
  SELECT
    'scoring_environment' as category,
    scoring_alert as severity,
    CONCAT('Avg points: ', ROUND(avg_points, 1), ' (baseline: ', ROUND(baseline_avg_points, 1), ')') as description
  FROM `nba_trend_monitoring.league_scoring_trends`, latest_week
  WHERE week_start = latest_week.latest AND scoring_alert != 'OK'
),
market_alerts AS (
  SELECT
    'market_balance' as category,
    market_balance_alert as severity,
    CONCAT('Overs hitting at ', ROUND(pct_overs_hitting, 1), '%') as description
  FROM `nba_trend_monitoring.league_scoring_trends`, latest_week
  WHERE week_start = latest_week.latest AND market_balance_alert != 'OK'
),
model_alerts AS (
  SELECT
    'model_bias' as category,
    bias_alert as severity,
    CONCAT('Prediction bias: ', overall_bias, ' points') as description
  FROM `nba_trend_monitoring.model_health_trends`, latest_week
  WHERE week_start = latest_week.latest AND bias_alert != 'OK'

  UNION ALL

  SELECT
    'confidence_calibration' as category,
    calibration_alert as severity,
    CONCAT('90%+ confidence hitting at ', conf_90_hit_rate, '%') as description
  FROM `nba_trend_monitoring.model_health_trends`, latest_week
  WHERE week_start = latest_week.latest AND calibration_alert != 'OK'

  UNION ALL

  SELECT
    'recommendation_imbalance' as category,
    recommendation_balance_alert as severity,
    CONCAT('OVER hit rate: ', over_hit_rate, '% vs UNDER: ', under_hit_rate, '%') as description
  FROM `nba_trend_monitoring.model_health_trends`, latest_week
  WHERE week_start = latest_week.latest AND recommendation_balance_alert != 'OK'
)
SELECT * FROM scoring_alerts
UNION ALL SELECT * FROM market_alerts
UNION ALL SELECT * FROM model_alerts
ORDER BY
  CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'WARNING' THEN 2 ELSE 3 END,
  category;


-- ============================================================================
-- VIEW 6: Star Player Performance Tracking
-- Specifically tracks high-value players (line >= 20)
-- ============================================================================
CREATE OR REPLACE VIEW `nba_trend_monitoring.star_player_trends` AS
SELECT
  DATE_TRUNC(game_date, WEEK(MONDAY)) as week_start,
  player_lookup,
  COUNT(*) as games,

  -- Scoring
  ROUND(AVG(actual_points), 1) as avg_actual,
  ROUND(AVG(predicted_points), 1) as avg_predicted,
  ROUND(AVG(line_value), 1) as avg_line,
  ROUND(AVG(predicted_points - actual_points), 2) as prediction_bias,

  -- Performance vs line
  ROUND(AVG(actual_points - line_value), 2) as vs_line,
  COUNTIF(actual_points > line_value) as times_over,
  COUNTIF(actual_points < line_value) as times_under,

  -- Hit rate
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,

  -- DNP tracking
  COUNTIF(actual_points = 0) as dnp_games

FROM `nba_predictions.prediction_accuracy`
WHERE line_value >= 20
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
  AND system_id = 'catboost_v8'
  AND actual_points IS NOT NULL
GROUP BY week_start, player_lookup
HAVING COUNT(*) >= 2  -- At least 2 games in the week
ORDER BY week_start DESC, avg_line DESC;


-- ============================================================================
-- VIEW 7: Rest and Schedule Impact Trends
-- Tracks how rest days affect performance
-- ============================================================================
CREATE OR REPLACE VIEW `nba_trend_monitoring.rest_impact_trends` AS
WITH with_rest AS (
  SELECT
    pa.*,
    fs.days_rest,
    CASE
      WHEN fs.days_rest = 0 THEN 'back_to_back'
      WHEN fs.days_rest = 1 THEN 'one_day_rest'
      WHEN fs.days_rest = 2 THEN 'two_days_rest'
      WHEN fs.days_rest >= 3 THEN 'extended_rest'
      ELSE 'unknown'
    END as rest_category
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
  rest_category,
  COUNT(*) as predictions,

  -- Scoring
  ROUND(AVG(actual_points), 1) as avg_actual,
  ROUND(AVG(predicted_points), 1) as avg_predicted,
  ROUND(AVG(predicted_points - actual_points), 2) as bias,

  -- Hit rate
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate

FROM with_rest
WHERE rest_category != 'unknown'
GROUP BY week_start, rest_category
ORDER BY week_start DESC, rest_category;
