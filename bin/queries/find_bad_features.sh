#!/bin/bash
# Find features with low quality for a specific date
# Usage: ./bin/queries/find_bad_features.sh [YYYY-MM-DD] [threshold]

DATE="${1:-$(date +%Y-%m-%d)}"
THRESHOLD="${2:-50}"

echo "=== Features with quality < $THRESHOLD for $DATE ==="
echo ""

bq query --use_legacy_sql=false --format=pretty "
-- Check critical composite factors (Session 132 issue)
SELECT
  'Composite Factors (5-8)' as feature_group,
  ROUND(AVG(feature_5_quality), 1) as feature_5_avg,
  ROUND(AVG(feature_6_quality), 1) as feature_6_avg,
  ROUND(AVG(feature_7_quality), 1) as feature_7_avg,
  ROUND(AVG(feature_8_quality), 1) as feature_8_avg,
  COUNTIF(feature_5_quality < $THRESHOLD OR feature_6_quality < $THRESHOLD
          OR feature_7_quality < $THRESHOLD OR feature_8_quality < $THRESHOLD) as players_affected
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$DATE'

UNION ALL

-- Check opponent defense
SELECT
  'Opponent Defense (13-14)' as feature_group,
  ROUND(AVG(feature_13_quality), 1),
  ROUND(AVG(feature_14_quality), 1),
  NULL as feature_7_avg,
  NULL as feature_8_avg,
  COUNTIF(feature_13_quality < $THRESHOLD OR feature_14_quality < $THRESHOLD)
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$DATE';

-- Show details for players with bad composite factors
SELECT
  player_lookup,
  feature_5_quality, feature_5_source,
  feature_6_quality, feature_6_source,
  feature_7_quality, feature_7_source,
  feature_8_quality, feature_8_source,
  matchup_quality_pct,
  quality_alert_level
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$DATE'
  AND (feature_5_quality < $THRESHOLD OR feature_6_quality < $THRESHOLD
       OR feature_7_quality < $THRESHOLD OR feature_8_quality < $THRESHOLD)
ORDER BY matchup_quality_pct ASC
LIMIT 20;
"
