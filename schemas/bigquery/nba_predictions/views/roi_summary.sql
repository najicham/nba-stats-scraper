-- ============================================================================
-- View: roi_summary
-- Purpose: Aggregated ROI metrics by system (for dashboard display)
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.roi_summary` AS
SELECT
  system_id,

  -- Overall betting volume
  SUM(total_bets) as total_bets,
  SUM(wins) as total_wins,
  SUM(losses) as total_losses,
  ROUND(100.0 * SUM(wins) / (SUM(wins) + SUM(losses)), 2) as win_rate_pct,

  -- Flat betting strategy ($100 per bet)
  ROUND(SUM(flat_betting_profit), 2) as flat_betting_total_profit,
  ROUND(100.0 * SUM(flat_betting_profit) / (SUM(total_bets) * 100), 2) as flat_betting_roi_pct,
  ROUND(SUM(flat_betting_profit) / SUM(total_bets), 2) as flat_betting_ev_per_bet,

  -- High confidence betting (>70% confidence)
  SUM(high_conf_bets) as high_conf_bets,
  SUM(high_conf_wins) as high_conf_wins,
  SUM(high_conf_losses) as high_conf_losses,
  ROUND(100.0 * SUM(high_conf_wins) / NULLIF(SUM(high_conf_wins) + SUM(high_conf_losses), 0), 2) as high_conf_win_rate_pct,
  ROUND(100.0 * (SUM(high_conf_wins) * 90.91 - SUM(high_conf_losses) * 100) / NULLIF(SUM(high_conf_bets) * 100, 0), 2) as high_conf_roi_pct,
  ROUND((SUM(high_conf_wins) * 90.91 - SUM(high_conf_losses) * 100) / NULLIF(SUM(high_conf_bets), 0), 2) as high_conf_ev_per_bet,

  -- Very high confidence betting (>80% confidence)
  SUM(very_high_conf_bets) as very_high_conf_bets,
  SUM(very_high_conf_wins) as very_high_conf_wins,
  SUM(very_high_conf_losses) as very_high_conf_losses,
  ROUND(100.0 * SUM(very_high_conf_wins) / NULLIF(SUM(very_high_conf_wins) + SUM(very_high_conf_losses), 0), 2) as very_high_conf_win_rate_pct,
  ROUND(100.0 * (SUM(very_high_conf_wins) * 90.91 - SUM(very_high_conf_losses) * 100) / NULLIF(SUM(very_high_conf_bets) * 100, 0), 2) as very_high_conf_roi_pct,
  ROUND((SUM(very_high_conf_wins) * 90.91 - SUM(very_high_conf_losses) * 100) / NULLIF(SUM(very_high_conf_bets), 0), 2) as very_high_conf_ev_per_bet,

  -- Date range
  MIN(game_date) as first_game_date,
  MAX(game_date) as last_game_date,
  COUNT(DISTINCT game_date) as days_of_data

FROM `nba-props-platform.nba_predictions.roi_simulation`
GROUP BY system_id
ORDER BY flat_betting_roi_pct DESC;
