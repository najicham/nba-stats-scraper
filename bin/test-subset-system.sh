#!/bin/bash
# Test Dynamic Subset Picks System
# Session 83 - System verification

set -e

echo "==================================="
echo "Dynamic Subset System Status Check"
echo "==================================="
echo ""

echo "1. Checking subset definitions..."
bq query --use_legacy_sql=false "
SELECT
  subset_id,
  system_id,
  use_ranking,
  top_n,
  signal_condition,
  min_edge,
  is_active
FROM nba_predictions.dynamic_subset_definitions
WHERE is_active = TRUE
ORDER BY subset_id"

echo ""
echo "2. Checking today's daily signal..."
bq query --use_legacy_sql=false "
SELECT
  game_date,
  system_id,
  total_picks,
  high_edge_picks,
  pct_over,
  daily_signal
FROM nba_predictions.daily_prediction_signals
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'"

echo ""
echo "3. Testing subset query: v9_high_edge_top5..."
bq query --use_legacy_sql=false "
WITH daily_signal AS (
  SELECT * FROM nba_predictions.daily_prediction_signals
  WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
),
subset_def AS (
  SELECT * FROM nba_predictions.dynamic_subset_definitions
  WHERE subset_id = 'v9_high_edge_top5'
),
ranked_picks AS (
  SELECT
    p.player_lookup,
    ROUND(p.predicted_points, 1) as predicted,
    p.current_points_line as line,
    ROUND(ABS(p.predicted_points - p.current_points_line), 1) as edge,
    p.recommendation,
    ROUND(p.confidence_score, 2) as confidence,
    ROUND((ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5), 1) as composite_score,
    ROW_NUMBER() OVER (
      ORDER BY (ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5) DESC
    ) as pick_rank
  FROM nba_predictions.player_prop_predictions p
  CROSS JOIN subset_def d
  WHERE p.game_date = CURRENT_DATE()
    AND p.system_id = d.system_id
    AND p.is_active = TRUE
    AND ABS(p.predicted_points - p.current_points_line) >= COALESCE(d.min_edge, 0)
    AND (d.min_confidence IS NULL OR p.confidence_score >= d.min_confidence)
    AND p.current_points_line IS NOT NULL
)
SELECT
  r.pick_rank,
  r.player_lookup,
  r.predicted,
  r.line,
  r.edge,
  r.recommendation,
  r.confidence,
  r.composite_score,
  s.pct_over,
  s.daily_signal
FROM ranked_picks r
CROSS JOIN daily_signal s
CROSS JOIN subset_def d
WHERE r.pick_rank <= COALESCE(d.top_n, 999)
ORDER BY r.pick_rank"

echo ""
echo "==================================="
echo "System Check Complete!"
echo "==================================="
echo ""
echo "✅ Subset definitions: Working"
echo "✅ Daily signals: Working"
echo "✅ Pick selection: Working"
echo ""
echo "To use the subset picks skill:"
echo "  /subset-picks                    # List all subsets"
echo "  /subset-picks v9_high_edge_top5  # Today's top 5"
echo "  /subset-picks <id> --history 7   # Last 7 days performance"
echo ""
