#!/bin/bash
# Check training data quality for a date range
# Usage: ./bin/queries/training_quality_check.sh [START_DATE] [END_DATE]

START="${1:-$(date -d '30 days ago' +%Y-%m-%d)}"
END="${2:-$(date +%Y-%m-%d)}"

echo "=== Training Quality Check: $START to $END ==="
echo ""

bq query --use_legacy_sql=false --format=pretty "
SELECT
  COUNT(*) as total_records,
  COUNTIF(is_training_ready) as training_ready_count,
  ROUND(COUNTIF(is_training_ready) / COUNT(*) * 100, 1) as training_ready_pct,
  COUNTIF(critical_features_training_quality) as critical_quality_count,
  ROUND(COUNTIF(critical_features_training_quality) / COUNT(*) * 100, 1) as critical_quality_pct,
  ROUND(AVG(training_quality_feature_count), 1) as avg_training_features,
  ROUND(AVG(feature_quality_score), 1) as avg_overall_quality,
  ROUND(AVG(matchup_quality_pct), 1) as avg_matchup_quality
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN '$START' AND '$END';
"
