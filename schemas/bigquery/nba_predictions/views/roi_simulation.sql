-- ============================================================================
-- View: roi_simulation
-- Purpose: Simulate betting ROI using standard sportsbook odds
-- ============================================================================
-- Assumptions:
--   - Standard odds: -110 (bet $110 to win $100)
--   - Win payout: +$90.91 per $100 bet
--   - Loss cost: -$100 per $100 bet
--   - Pushes: $0 (bet returned)
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.roi_simulation` AS
WITH normalized_predictions AS (
  SELECT
    *,
    -- Normalize confidence scores (handle catboost_v8 percentage issue)
    CASE
      WHEN confidence_score > 1 THEN confidence_score / 100
      ELSE confidence_score
    END as normalized_confidence
  FROM `nba-props-platform.nba_predictions.prediction_grades`
  WHERE has_issues = FALSE  -- Only clean predictions
    AND prediction_correct IS NOT NULL  -- Only gradeable
),

flat_betting AS (
  SELECT
    system_id,
    game_date,

    -- Win/Loss/Push counts
    COUNTIF(prediction_correct) as wins,
    COUNTIF(NOT prediction_correct) as losses,
    COUNTIF(prediction_correct IS NULL) as pushes,
    COUNT(*) as total_bets,

    -- Win rate
    ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 2) as win_rate_pct,

    -- Flat betting: $100 per bet
    COUNTIF(prediction_correct) * 90.91 as win_profit,
    COUNTIF(NOT prediction_correct) * 100 as loss_cost,
    ROUND(COUNTIF(prediction_correct) * 90.91 - COUNTIF(NOT prediction_correct) * 100, 2) as net_profit,

    -- ROI calculation
    ROUND(
      100.0 * (COUNTIF(prediction_correct) * 90.91 - COUNTIF(NOT prediction_correct) * 100) /
      (COUNT(*) * 100),
      2
    ) as roi_pct,

    -- Expected value per bet
    ROUND(
      (COUNTIF(prediction_correct) * 90.91 - COUNTIF(NOT prediction_correct) * 100) / COUNT(*),
      2
    ) as expected_value_per_bet,

    -- Average confidence
    ROUND(AVG(normalized_confidence) * 100, 2) as avg_confidence

  FROM normalized_predictions
  GROUP BY system_id, game_date
),

high_confidence_betting AS (
  SELECT
    system_id,
    game_date,

    -- High confidence (>70%) betting
    COUNTIF(prediction_correct AND normalized_confidence >= 0.70) as high_conf_wins,
    COUNTIF(NOT prediction_correct AND normalized_confidence >= 0.70) as high_conf_losses,
    COUNTIF(normalized_confidence >= 0.70) as high_conf_total,

    -- High confidence ROI
    ROUND(
      CASE
        WHEN COUNTIF(normalized_confidence >= 0.70) > 0 THEN
          100.0 * (
            COUNTIF(prediction_correct AND normalized_confidence >= 0.70) * 90.91 -
            COUNTIF(NOT prediction_correct AND normalized_confidence >= 0.70) * 100
          ) / (COUNTIF(normalized_confidence >= 0.70) * 100)
        ELSE NULL
      END,
      2
    ) as high_conf_roi_pct,

    -- Very high confidence (>80%) betting
    COUNTIF(prediction_correct AND normalized_confidence >= 0.80) as very_high_conf_wins,
    COUNTIF(NOT prediction_correct AND normalized_confidence >= 0.80) as very_high_conf_losses,
    COUNTIF(normalized_confidence >= 0.80) as very_high_conf_total,

    -- Very high confidence ROI
    ROUND(
      CASE
        WHEN COUNTIF(normalized_confidence >= 0.80) > 0 THEN
          100.0 * (
            COUNTIF(prediction_correct AND normalized_confidence >= 0.80) * 90.91 -
            COUNTIF(NOT prediction_correct AND normalized_confidence >= 0.80) * 100
          ) / (COUNTIF(normalized_confidence >= 0.80) * 100)
        ELSE NULL
      END,
      2
    ) as very_high_conf_roi_pct

  FROM normalized_predictions
  GROUP BY system_id, game_date
)

SELECT
  f.system_id,
  f.game_date,

  -- Betting volume
  f.total_bets,
  f.wins,
  f.losses,
  f.win_rate_pct,
  f.avg_confidence,

  -- Flat betting results ($100 per bet)
  f.net_profit as flat_betting_profit,
  f.roi_pct as flat_betting_roi_pct,
  f.expected_value_per_bet as flat_betting_ev,

  -- High confidence betting (>70%)
  h.high_conf_total as high_conf_bets,
  h.high_conf_wins,
  h.high_conf_losses,
  ROUND(100.0 * h.high_conf_wins / NULLIF(h.high_conf_total, 0), 2) as high_conf_win_rate_pct,
  h.high_conf_roi_pct,

  -- Very high confidence betting (>80%)
  h.very_high_conf_total as very_high_conf_bets,
  h.very_high_conf_wins,
  h.very_high_conf_losses,
  ROUND(100.0 * h.very_high_conf_wins / NULLIF(h.very_high_conf_total, 0), 2) as very_high_conf_win_rate_pct,
  h.very_high_conf_roi_pct

FROM flat_betting f
LEFT JOIN high_confidence_betting h
  ON f.system_id = h.system_id
  AND f.game_date = h.game_date

ORDER BY f.game_date DESC, f.roi_pct DESC;
