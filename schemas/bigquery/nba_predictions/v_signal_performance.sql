-- ============================================================================
-- Signal Performance Summary View
-- ============================================================================
-- Dataset: nba_predictions
-- View: v_signal_performance
-- Purpose: Per-signal hit rate, ROI, and pick count for monitoring.
--          JOINs pick_signal_tags with prediction_accuracy to grade
--          individual signals (not just the aggregated Signal Picks subset).
-- Created: 2026-02-14 (Session 254)
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_signal_performance` AS

WITH tagged_predictions AS (
  SELECT
    pst.game_date,
    pst.player_lookup,
    pst.system_id,
    signal_tag,
    pst.model_health_status,
    pa.prediction_correct,
    pa.actual_points,
    ABS(pa.predicted_points - pa.line_value) AS edge
  FROM `nba-props-platform.nba_predictions.pick_signal_tags` pst
  CROSS JOIN UNNEST(pst.signal_tags) AS signal_tag
  INNER JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
    ON pst.player_lookup = pa.player_lookup
    AND pst.game_date = pa.game_date
    AND pst.system_id = pa.system_id
  WHERE pa.prediction_correct IS NOT NULL
    AND pa.is_voided IS NOT TRUE
    AND pst.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
)

SELECT
  signal_tag,
  COUNT(*) AS total_picks,
  COUNTIF(prediction_correct) AS wins,
  COUNT(*) - COUNTIF(prediction_correct) AS losses,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) AS hit_rate,
  ROUND(100.0 * (COUNTIF(prediction_correct) * 100
    - (COUNT(*) - COUNTIF(prediction_correct)) * 110) / (COUNT(*) * 110), 1) AS roi,
  ROUND(AVG(edge), 1) AS avg_edge,
  MIN(game_date) AS first_date,
  MAX(game_date) AS last_date
FROM tagged_predictions
GROUP BY signal_tag
ORDER BY hit_rate DESC;
