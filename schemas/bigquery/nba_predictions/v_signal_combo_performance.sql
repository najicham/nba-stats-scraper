-- ============================================================================
-- Signal Combo Performance View
-- ============================================================================
-- Dataset: nba_predictions
-- View: v_signal_combo_performance
-- Purpose: Per-combo hit rate, ROI, and pick count for monitoring.
--          JOINs pick_signal_tags (with matched_combo_id) against
--          prediction_accuracy to grade combos over the last 30 days.
-- Created: 2026-02-15 (Session 259)
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_signal_combo_performance` AS

WITH picks_with_combos AS (
  SELECT
    pst.game_date,
    pst.player_lookup,
    pst.matched_combo_id,
    pst.combo_classification,
    pa.prediction_correct,
    ABS(pa.predicted_points - pa.line_value) AS edge
  FROM `nba-props-platform.nba_predictions.pick_signal_tags` pst
  INNER JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
    ON pst.player_lookup = pa.player_lookup
    AND pst.game_date = pa.game_date
    AND pst.system_id = pa.system_id
  WHERE pst.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND pa.prediction_correct IS NOT NULL
    AND pa.is_voided IS NOT TRUE
    AND pst.matched_combo_id IS NOT NULL
)

SELECT
  matched_combo_id,
  combo_classification,
  COUNT(*) AS total_picks,
  COUNTIF(prediction_correct) AS wins,
  COUNT(*) - COUNTIF(prediction_correct) AS losses,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) AS hit_rate,
  ROUND(100.0 * (COUNTIF(prediction_correct) * 100
    - (COUNT(*) - COUNTIF(prediction_correct)) * 110) / (COUNT(*) * 110), 1) AS roi,
  ROUND(AVG(edge), 1) AS avg_edge,
  MIN(game_date) AS first_date,
  MAX(game_date) AS last_date
FROM picks_with_combos
GROUP BY 1, 2;
