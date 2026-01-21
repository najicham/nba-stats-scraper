#!/bin/bash
# Quick Win #1 Validation Script (CORRECTED)
# Validates Phase 3 Analytics weight boost: 75 → 87
# Compares Jan 19 (baseline, weight=75) vs Jan 20 (test, weight=87)

echo "=== QUICK WIN #1 VALIDATION (CORRECTED) ==="
echo "Comparing Jan 19 (baseline, weight=75) vs Jan 20 (test, weight=87)"
echo ""
echo "Current time: $(date)"
echo ""

# Check props were scraped
echo "1. Checking props data..."
bq query --use_legacy_sql=false --location=us-west2 --format=pretty '
SELECT
  game_date,
  COUNT(*) as props_count,
  COUNT(DISTINCT player_lookup) as unique_players
FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
WHERE game_date IN ("2026-01-19", "2026-01-20")
GROUP BY game_date
ORDER BY game_date
'

echo ""
echo "2. Checking Phase 3 Analytics data (player_game_summary)..."
bq query --use_legacy_sql=false --location=us-west2 --format=pretty '
SELECT
  game_date,
  COUNT(*) as player_summaries,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(DISTINCT game_id) as unique_games
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date IN ("2026-01-19", "2026-01-20")
GROUP BY game_date
ORDER BY game_date
'

echo ""
echo "3. Checking Phase 4 ML Feature Store (where quality scores live)..."
bq query --use_legacy_sql=false --location=us-west2 --format=pretty '
SELECT
  game_date,
  COUNT(*) as records,
  COUNT(DISTINCT player_lookup) as players,
  ROUND(AVG(feature_quality_score), 2) as avg_quality,
  ROUND(MIN(feature_quality_score), 2) as min_quality,
  ROUND(MAX(feature_quality_score), 2) as max_quality,
  ROUND(STDDEV(feature_quality_score), 2) as stddev_quality
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date IN ("2026-01-19", "2026-01-20")
GROUP BY game_date
ORDER BY game_date
'

echo ""
echo "4. Checking Phase 5 Predictions generated..."
bq query --use_legacy_sql=false --location=us-west2 --format=pretty '
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(DISTINCT system_id) as systems,
  ROUND(AVG(confidence_score), 2) as avg_confidence
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date IN ("2026-01-19", "2026-01-20")
GROUP BY game_date
ORDER BY game_date
'

echo ""
echo "5. Calculating quality improvement (THE KEY METRIC)..."
bq query --use_legacy_sql=false --location=us-west2 --format=csv '
WITH quality_by_date AS (
  SELECT
    game_date,
    AVG(feature_quality_score) as avg_quality
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  WHERE game_date IN ("2026-01-19", "2026-01-20")
  GROUP BY game_date
)
SELECT
  baseline.game_date as baseline_date,
  ROUND(baseline.avg_quality, 2) as baseline_quality,
  test.game_date as test_date,
  ROUND(test.avg_quality, 2) as test_quality,
  ROUND((test.avg_quality - baseline.avg_quality), 2) as absolute_improvement,
  ROUND((test.avg_quality - baseline.avg_quality) / baseline.avg_quality * 100, 2) as improvement_percent
FROM quality_by_date baseline
CROSS JOIN quality_by_date test
WHERE baseline.game_date = "2026-01-19"
  AND test.game_date = "2026-01-20"
'

echo ""
echo "6. Distribution of quality scores (to verify weight impact)..."
bq query --use_legacy_sql=false --location=us-west2 --format=pretty '
SELECT
  game_date,
  quality_tier,
  COUNT(*) as player_count,
  ROUND(AVG(feature_quality_score), 2) as avg_score
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date IN ("2026-01-19", "2026-01-20")
GROUP BY game_date, quality_tier
ORDER BY game_date, quality_tier
'

echo ""
echo "=== VALIDATION COMPLETE ==="
echo ""
echo "EXPECTED RESULTS:"
echo "  - Jan 19 (baseline): avg_quality ~64-65 (weight=75)"
echo "  - Jan 20 (test): avg_quality ~72-75 (weight=87)"
echo "  - Improvement: 10-12% increase in quality scores"
echo ""
echo "ACTUAL RESULTS (preliminary check):"
echo "  - Jan 19: 64.83"
echo "  - Jan 20: 67.45"
echo "  - Improvement: 4.04%"
echo ""
echo "⚠️  POSSIBLE ISSUES IF IMPROVEMENT < 10%:"
echo "  1. Weight change not fully deployed to all Phase 3 processors"
echo "  2. Data from Jan 20 processed before deployment"
echo "  3. Different player pool between dates (51 vs 26 players)"
echo "  4. Weight affects specific analytics, may not show in aggregate"
echo ""
echo "NEXT STEPS:"
echo "  - Review deployment timing of weight change (commit e8fb8e72)"
echo "  - Check Phase 3 processor logs for weight value"
echo "  - Validate specific analytics affected by weight (e.g., zone matchup)"
