-- Comprehensive segmentation analysis for harmful signals
-- Signals: prop_value_gap_extreme, edge_spread_optimal, cold_snap

WITH signal_data AS (
  SELECT
    pst.player_lookup,
    pst.game_date,
    pst.game_id,
    signal
  FROM nba_predictions.pick_signal_tags pst,
  UNNEST(pst.signal_tags) AS signal
  WHERE pst.game_date >= '2026-01-09'
    AND pst.system_id = 'catboost_v9'
    AND signal IN ('prop_value_gap_extreme', 'edge_spread_optimal', 'cold_snap')
),

v9_preds AS (
  SELECT
    pa.player_lookup,
    pa.game_id,
    pa.game_date,
    pa.predicted_points,
    pa.line_value,
    pa.recommendation,
    CAST(pa.predicted_points - pa.line_value AS FLOAT64) AS edge,
    pa.actual_points,
    pa.prediction_correct AS hit,
    CASE WHEN pa.prediction_correct THEN 0.91 ELSE -1.0 END AS profit_loss,
    pa.team_abbr
  FROM nba_predictions.prediction_accuracy pa
  WHERE pa.game_date >= '2026-01-09'
    AND pa.system_id = 'catboost_v9'
    AND pa.recommendation IN ('OVER', 'UNDER')
    AND pa.is_voided IS NOT TRUE
    AND pa.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
    AND pa.prediction_correct IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY pa.player_lookup, pa.game_id ORDER BY pa.graded_at DESC
  ) = 1
),

feature_data AS (
  SELECT
    fs.player_lookup,
    fs.game_date,
    fs.feature_29_value AS avg_minutes_l5
  FROM nba_predictions.ml_feature_store_v2 fs
  WHERE fs.game_date >= '2026-01-09'
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY fs.player_lookup, fs.game_date ORDER BY fs.updated_at DESC
  ) = 1
),

signal_picks AS (
  SELECT
    sd.signal,
    vp.*,
    fd.avg_minutes_l5,
    -- Player tier based on line value
    CASE
      WHEN vp.line_value >= 25 THEN 'Star (25+)'
      WHEN vp.line_value >= 15 THEN 'Mid (15-25)'
      ELSE 'Role (<15)'
    END AS player_tier,
    -- Minutes tier
    CASE
      WHEN fd.avg_minutes_l5 >= 32 THEN 'Heavy (32+)'
      WHEN fd.avg_minutes_l5 >= 25 THEN 'Starter (25-32)'
      WHEN fd.avg_minutes_l5 IS NOT NULL THEN 'Bench (<25)'
      ELSE 'Unknown'
    END AS minutes_tier,
    -- Edge tier
    CASE
      WHEN vp.edge < 4 THEN 'Small (<4)'
      WHEN vp.edge < 6 THEN 'Medium (4-6)'
      ELSE 'Large (6+)'
    END AS edge_tier,
    -- Eval window
    CASE
      WHEN vp.game_date BETWEEN '2026-01-05' AND '2026-01-18' THEN 'W2 (Jan 5-18)'
      WHEN vp.game_date BETWEEN '2026-01-19' AND '2026-01-31' THEN 'W3 (Jan 19-31)'
      WHEN vp.game_date >= '2026-02-01' THEN 'W4 (Feb 1-13)'
    END AS eval_window
  FROM signal_data sd
  INNER JOIN v9_preds vp
    ON sd.player_lookup = vp.player_lookup
    AND sd.game_id = vp.game_id
  LEFT JOIN feature_data fd
    ON vp.player_lookup = fd.player_lookup
    AND vp.game_date = fd.game_date
)

SELECT
  signal,
  'OVERALL' AS dimension,
  'All' AS segment,
  COUNT(*) AS n,
  COUNTIF(hit) AS hits,
  ROUND(100.0 * COUNTIF(hit) / COUNT(*), 1) AS hr,
  ROUND(SUM(profit_loss), 2) AS total_pl,
  ROUND(100.0 * SUM(profit_loss) / COUNT(*), 1) AS roi
FROM signal_picks
GROUP BY signal

UNION ALL

-- Player tier segmentation
SELECT
  signal,
  'Player Tier' AS dimension,
  player_tier AS segment,
  COUNT(*) AS n,
  COUNTIF(hit) AS hits,
  ROUND(100.0 * COUNTIF(hit) / COUNT(*), 1) AS hr,
  ROUND(SUM(profit_loss), 2) AS total_pl,
  ROUND(100.0 * SUM(profit_loss) / COUNT(*), 1) AS roi
FROM signal_picks
GROUP BY signal, player_tier
HAVING n >= 5

UNION ALL

-- Minutes tier segmentation
SELECT
  signal,
  'Minutes Tier' AS dimension,
  minutes_tier AS segment,
  COUNT(*) AS n,
  COUNTIF(hit) AS hits,
  ROUND(100.0 * COUNTIF(hit) / COUNT(*), 1) AS hr,
  ROUND(SUM(profit_loss), 2) AS total_pl,
  ROUND(100.0 * SUM(profit_loss) / COUNT(*), 1) AS roi
FROM signal_picks
WHERE minutes_tier != 'Unknown'
GROUP BY signal, minutes_tier
HAVING n >= 5

UNION ALL

-- Edge tier segmentation
SELECT
  signal,
  'Edge Tier' AS dimension,
  edge_tier AS segment,
  COUNT(*) AS n,
  COUNTIF(hit) AS hits,
  ROUND(100.0 * COUNTIF(hit) / COUNT(*), 1) AS hr,
  ROUND(SUM(profit_loss), 2) AS total_pl,
  ROUND(100.0 * SUM(profit_loss) / COUNT(*), 1) AS roi
FROM signal_picks
GROUP BY signal, edge_tier
HAVING n >= 5

UNION ALL

-- Recommendation segmentation
SELECT
  signal,
  'Recommendation' AS dimension,
  recommendation AS segment,
  COUNT(*) AS n,
  COUNTIF(hit) AS hits,
  ROUND(100.0 * COUNTIF(hit) / COUNT(*), 1) AS hr,
  ROUND(SUM(profit_loss), 2) AS total_pl,
  ROUND(100.0 * SUM(profit_loss) / COUNT(*), 1) AS roi
FROM signal_picks
GROUP BY signal, recommendation
HAVING n >= 5

UNION ALL

-- Eval window segmentation
SELECT
  signal,
  'Eval Window' AS dimension,
  eval_window AS segment,
  COUNT(*) AS n,
  COUNTIF(hit) AS hits,
  ROUND(100.0 * COUNTIF(hit) / COUNT(*), 1) AS hr,
  ROUND(SUM(profit_loss), 2) AS total_pl,
  ROUND(100.0 * SUM(profit_loss) / COUNT(*), 1) AS roi
FROM signal_picks
GROUP BY signal, eval_window
HAVING n >= 5

ORDER BY signal, dimension, segment
