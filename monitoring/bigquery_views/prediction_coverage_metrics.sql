-- ============================================================================
-- View: prediction_coverage_metrics
-- Purpose: Track prediction coverage rates and gaps over time
-- ============================================================================
-- Monitors percentage of players with predictions per game date, identifies
-- coverage gaps, and shows trends over the last 7 days.
--
-- Coverage calculation:
-- - Numerator: Players with active predictions
-- - Denominator: Players with betting lines (expected coverage)
--
-- Usage:
--   -- Daily coverage trend
--   SELECT * FROM `nba-props-platform.nba_monitoring.prediction_coverage_metrics`
--   WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
--   ORDER BY game_date DESC;
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_monitoring.prediction_coverage_metrics` AS

WITH daily_betting_lines AS (
  -- Players with betting lines per date (expected coverage)
  SELECT
    game_date,
    COUNT(DISTINCT player_lookup) as players_with_lines,
    AVG(points_line) as avg_line_value,
    COUNT(DISTINCT bookmaker) as bookmakers_available
  FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_date
),

daily_predictions AS (
  -- Players with predictions per date (actual coverage)
  SELECT
    game_date,
    COUNT(DISTINCT player_lookup) as players_with_predictions,
    COUNT(DISTINCT system_id) as active_systems,
    AVG(confidence_score) as avg_confidence,

    -- Prediction quality metrics
    COUNTIF(recommendation IN ('OVER', 'UNDER')) as actionable_predictions,
    COUNTIF(has_prop_line = TRUE) as predictions_with_lines,
    COUNTIF(has_prop_line = FALSE) as predictions_without_lines,

    -- Data quality flags
    COUNTIF(is_production_ready = TRUE) as production_ready_count,
    COUNTIF(completeness_percentage >= 90) as high_completeness_count,
    AVG(completeness_percentage) as avg_completeness
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND is_active = TRUE
  GROUP BY game_date
),

coverage_gaps AS (
  -- Detailed gap analysis using existing coverage view
  SELECT
    game_date,
    gap_reason,
    COUNT(*) as gap_count
  FROM `nba-props-platform.nba_predictions.v_prediction_coverage_gaps`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_date, gap_reason
),

gap_summary AS (
  -- Pivot gap reasons into columns
  SELECT
    game_date,
    COUNTIF(gap_reason = 'NOT_IN_REGISTRY') as gap_not_in_registry,
    COUNTIF(gap_reason = 'NAME_UNRESOLVED') as gap_name_unresolved,
    COUNTIF(gap_reason = 'NOT_IN_PLAYER_CONTEXT') as gap_no_context,
    COUNTIF(gap_reason = 'NO_FEATURES') as gap_no_features,
    COUNTIF(gap_reason = 'LOW_QUALITY_FEATURES') as gap_low_quality,
    COUNTIF(gap_reason = 'UNKNOWN_REASON') as gap_unknown,
    COUNT(*) as total_gaps
  FROM coverage_gaps
  GROUP BY game_date
),

blocked_predictions AS (
  -- Count predictions blocked by quality issues
  SELECT
    game_date,
    COUNT(*) as blocked_count,

    -- Reasons for blocking
    COUNTIF(is_production_ready = FALSE) as blocked_not_ready,
    COUNTIF(completeness_percentage < 90) as blocked_incomplete,
    COUNTIF(circuit_breaker_active = TRUE) as blocked_circuit_breaker,
    COUNTIF(manual_override_required = TRUE) as blocked_manual_override,

    -- Most common blocking reasons
    APPROX_TOP_COUNT(processing_decision_reason, 1)[OFFSET(0)].value as top_block_reason,
    APPROX_TOP_COUNT(processing_decision_reason, 1)[OFFSET(0)].count as top_block_count
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND is_production_ready = FALSE
  GROUP BY game_date
),

-- Calculate 7-day rolling averages
daily_metrics AS (
  SELECT
    bl.game_date,

    -- Coverage counts
    COALESCE(bl.players_with_lines, 0) as players_with_lines,
    COALESCE(dp.players_with_predictions, 0) as players_with_predictions,
    COALESCE(gs.total_gaps, 0) as coverage_gap_count,

    -- Coverage percentage
    CASE
      WHEN bl.players_with_lines > 0
      THEN ROUND(COALESCE(dp.players_with_predictions, 0) * 100.0 / bl.players_with_lines, 2)
      ELSE 0
    END as coverage_percentage,

    -- Prediction quality
    COALESCE(dp.active_systems, 0) as active_systems,
    COALESCE(dp.avg_confidence, 0) as avg_confidence,
    COALESCE(dp.actionable_predictions, 0) as actionable_predictions,
    COALESCE(dp.predictions_with_lines, 0) as predictions_with_lines,
    COALESCE(dp.predictions_without_lines, 0) as predictions_without_lines,

    -- Data quality
    COALESCE(dp.production_ready_count, 0) as production_ready_count,
    COALESCE(dp.high_completeness_count, 0) as high_completeness_count,
    COALESCE(dp.avg_completeness, 0) as avg_completeness,

    -- Gap breakdown
    COALESCE(gs.gap_not_in_registry, 0) as gap_not_in_registry,
    COALESCE(gs.gap_name_unresolved, 0) as gap_name_unresolved,
    COALESCE(gs.gap_no_context, 0) as gap_no_context,
    COALESCE(gs.gap_no_features, 0) as gap_no_features,
    COALESCE(gs.gap_low_quality, 0) as gap_low_quality,
    COALESCE(gs.gap_unknown, 0) as gap_unknown,

    -- Blocked predictions
    COALESCE(bp.blocked_count, 0) as blocked_count,
    COALESCE(bp.blocked_not_ready, 0) as blocked_not_ready,
    COALESCE(bp.blocked_incomplete, 0) as blocked_incomplete,
    COALESCE(bp.blocked_circuit_breaker, 0) as blocked_circuit_breaker,
    COALESCE(bp.blocked_manual_override, 0) as blocked_manual_override,
    bp.top_block_reason,
    COALESCE(bp.top_block_count, 0) as top_block_count,

    -- Market context
    COALESCE(bl.avg_line_value, 0) as avg_line_value,
    COALESCE(bl.bookmakers_available, 0) as bookmakers_available

  FROM daily_betting_lines bl
  LEFT JOIN daily_predictions dp ON bl.game_date = dp.game_date
  LEFT JOIN gap_summary gs ON bl.game_date = gs.game_date
  LEFT JOIN blocked_predictions bp ON bl.game_date = bp.game_date
)

SELECT
  game_date,

  -- Coverage metrics
  players_with_lines,
  players_with_predictions,
  coverage_gap_count,
  coverage_percentage,

  -- 7-day rolling average
  ROUND(AVG(coverage_percentage) OVER (
    ORDER BY game_date
    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
  ), 2) as coverage_7d_avg,

  -- Trend (vs previous day)
  coverage_percentage - LAG(coverage_percentage) OVER (ORDER BY game_date) as coverage_change,

  -- Prediction quality
  active_systems,
  avg_confidence,
  actionable_predictions,
  predictions_with_lines,
  predictions_without_lines,

  -- Actionable prediction rate
  CASE
    WHEN players_with_predictions > 0
    THEN ROUND(actionable_predictions * 100.0 / players_with_predictions, 2)
    ELSE 0
  END as actionable_rate,

  -- Data quality
  production_ready_count,
  high_completeness_count,
  avg_completeness,

  -- Quality rate
  CASE
    WHEN players_with_predictions > 0
    THEN ROUND(production_ready_count * 100.0 / players_with_predictions, 2)
    ELSE 0
  END as production_ready_rate,

  -- Gap breakdown
  gap_not_in_registry,
  gap_name_unresolved,
  gap_no_context,
  gap_no_features,
  gap_low_quality,
  gap_unknown,

  -- Blocked predictions
  blocked_count,
  blocked_not_ready,
  blocked_incomplete,
  blocked_circuit_breaker,
  blocked_manual_override,
  top_block_reason,
  top_block_count,

  -- Market context
  avg_line_value,
  bookmakers_available,

  -- Health indicators
  CASE
    WHEN coverage_percentage >= 90 THEN 'HEALTHY'
    WHEN coverage_percentage >= 75 THEN 'WARNING'
    WHEN coverage_percentage >= 50 THEN 'DEGRADED'
    ELSE 'CRITICAL'
  END as health_status,

  CURRENT_TIMESTAMP() as last_updated

FROM daily_metrics
ORDER BY game_date DESC;

-- ============================================================================
-- EXAMPLE QUERIES
-- ============================================================================

-- 1. Current coverage status (today)
-- SELECT
--   game_date,
--   coverage_percentage,
--   coverage_7d_avg,
--   players_with_lines,
--   players_with_predictions,
--   coverage_gap_count,
--   health_status
-- FROM `nba-props-platform.nba_monitoring.prediction_coverage_metrics`
-- WHERE game_date = CURRENT_DATE();

-- 2. Coverage trend (last 7 days)
-- SELECT
--   game_date,
--   coverage_percentage,
--   coverage_change,
--   coverage_gap_count,
--   health_status
-- FROM `nba-props-platform.nba_monitoring.prediction_coverage_metrics`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
-- ORDER BY game_date DESC;

-- 3. Gap breakdown (today)
-- SELECT
--   game_date,
--   gap_not_in_registry,
--   gap_name_unresolved,
--   gap_no_context,
--   gap_no_features,
--   gap_low_quality,
--   gap_unknown,
--   coverage_gap_count
-- FROM `nba-props-platform.nba_monitoring.prediction_coverage_metrics`
-- WHERE game_date = CURRENT_DATE();

-- 4. Blocked predictions analysis
-- SELECT
--   game_date,
--   blocked_count,
--   blocked_not_ready,
--   blocked_incomplete,
--   blocked_circuit_breaker,
--   top_block_reason,
--   top_block_count
-- FROM `nba-props-platform.nba_monitoring.prediction_coverage_metrics`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
--   AND blocked_count > 0
-- ORDER BY game_date DESC;

-- 5. Alert on coverage degradation
-- SELECT
--   game_date,
--   coverage_percentage,
--   coverage_7d_avg,
--   health_status,
--   'ALERT: Coverage below threshold' as alert_message
-- FROM `nba-props-platform.nba_monitoring.prediction_coverage_metrics`
-- WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
--   AND health_status IN ('DEGRADED', 'CRITICAL')
-- ORDER BY game_date DESC;
