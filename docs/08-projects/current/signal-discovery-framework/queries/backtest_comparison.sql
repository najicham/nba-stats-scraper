-- Compare backtest data vs production data for the three signals

-- First: Get backtest window data (what signal_backtest.py uses)
WITH backtest_data AS (
  SELECT
    pst.player_lookup,
    pst.game_date,
    pst.game_id,
    signal_tag
  FROM nba_predictions.pick_signal_tags pst
  CROSS JOIN UNNEST(pst.signal_tags) AS signal_tag
  WHERE pst.game_date >= '2026-01-09'  -- Backtest start
    AND pst.system_id = 'catboost_v9'
    AND signal_tag IN ('prop_value_gap_extreme', 'edge_spread_optimal', 'cold_snap')
),

backtest_graded AS (
  SELECT
    bd.signal_tag,
    bd.game_date,
    pa.prediction_correct,
    CASE WHEN pa.prediction_correct THEN 0.91 ELSE -1.0 END AS profit_loss
  FROM backtest_data bd
  INNER JOIN nba_predictions.prediction_accuracy pa
    ON bd.player_lookup = pa.player_lookup
    AND bd.game_id = pa.game_id
    AND pa.system_id = 'catboost_v9'
  WHERE pa.prediction_correct IS NOT NULL
    AND pa.is_voided IS NOT TRUE
    AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY bd.player_lookup, bd.game_id ORDER BY pa.graded_at DESC
  ) = 1
),

-- Now: Get production data (what the view uses - last 30 days)
production_data AS (
  SELECT
    pst.player_lookup,
    pst.game_date,
    pst.game_id,
    signal_tag
  FROM nba_predictions.pick_signal_tags pst
  CROSS JOIN UNNEST(pst.signal_tags) AS signal_tag
  WHERE pst.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND pst.system_id = 'catboost_v9'
    AND signal_tag IN ('prop_value_gap_extreme', 'edge_spread_optimal', 'cold_snap')
),

production_graded AS (
  SELECT
    pd.signal_tag,
    pd.game_date,
    pa.prediction_correct,
    CASE WHEN pa.prediction_correct THEN 0.91 ELSE -1.0 END AS profit_loss
  FROM production_data pd
  INNER JOIN nba_predictions.prediction_accuracy pa
    ON pd.player_lookup = pa.player_lookup
    AND pd.game_date = pa.game_date  -- NOTE: view uses game_date, not game_id!
    AND pa.system_id = 'catboost_v9'
  WHERE pa.prediction_correct IS NOT NULL
    AND pa.is_voided IS NOT TRUE
    AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY pd.player_lookup, pd.game_id ORDER BY pa.graded_at DESC
  ) = 1
)

SELECT
  'BACKTEST (Jan 9+, game_id join)' as source,
  signal_tag,
  COUNT(*) as n,
  COUNTIF(prediction_correct) as hits,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr,
  ROUND(100.0 * SUM(profit_loss) / COUNT(*), 1) as roi
FROM backtest_graded
GROUP BY signal_tag

UNION ALL

SELECT
  'PRODUCTION (Last 30d, game_date join)' as source,
  signal_tag,
  COUNT(*) as n,
  COUNTIF(prediction_correct) as hits,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr,
  ROUND(100.0 * SUM(profit_loss) / COUNT(*), 1) as roi
FROM production_graded
GROUP BY signal_tag

ORDER BY signal_tag, source
