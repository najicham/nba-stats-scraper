#!/bin/bash
set -euo pipefail
# Quick Win #1 Validation Script
# Run at 11:00 AM PST (2:00 PM ET) after Phase 3 completes

echo "=== QUICK WIN #1 VALIDATION ==="
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
echo "2. Checking Phase 3 Analytics data..."
bq query --use_legacy_sql=false --location=us-west2 --format=pretty '
SELECT
  game_date,
  COUNT(*) as analytics_records,
  COUNT(DISTINCT game_id) as games_processed
FROM `nba-props-platform.nba_analytics.game_analytics`
WHERE game_date IN ("2026-01-19", "2026-01-20")
GROUP BY game_date
ORDER BY game_date
'

echo ""
echo "3. Comparing prediction quality scores..."
bq query --use_legacy_sql=false --location=us-west2 --format=pretty '
SELECT
  game_date,
  AVG(quality_score) as avg_quality,
  MIN(quality_score) as min_quality,
  MAX(quality_score) as max_quality,
  COUNT(*) as prediction_count,
  COUNT(DISTINCT game_id) as games_covered
FROM `nba-props-platform.nba_predictions.game_predictions`
WHERE game_date IN ("2026-01-19", "2026-01-20")
GROUP BY game_date
ORDER BY game_date
'

echo ""
echo "4. Calculating quality improvement..."
bq query --use_legacy_sql=false --location=us-west2 --format=csv '
WITH quality_by_date AS (
  SELECT
    game_date,
    AVG(quality_score) as avg_quality
  FROM `nba-props-platform.nba_predictions.game_predictions`
  WHERE game_date IN ("2026-01-19", "2026-01-20")
  GROUP BY game_date
)
SELECT
  baseline.game_date as baseline_date,
  baseline.avg_quality as baseline_quality,
  test.game_date as test_date,
  test.avg_quality as test_quality,
  ROUND((test.avg_quality - baseline.avg_quality) / baseline.avg_quality * 100, 2) as improvement_percent
FROM quality_by_date baseline
CROSS JOIN quality_by_date test
WHERE baseline.game_date = "2026-01-19"
  AND test.game_date = "2026-01-20"
'

echo ""
echo "=== VALIDATION COMPLETE ==="
echo "Expected: 10-12% improvement in quality scores"
echo "If improvement is in range, Quick Win #1 is validated! ✅"
