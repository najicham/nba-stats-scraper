#!/bin/bash
#
# Feature Store Weekly Report
#
# Generates a comprehensive weekly report on feature store health,
# trends, and quality metrics.
#
# Usage:
#   ./bin/monitoring/feature_store_weekly_report.sh
#

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

echo "📊 Feature Store Weekly Report"
echo "Generated: $(date)"
echo "=" | awk '{s=sprintf("%80s",""); gsub(/ /,"=",$0); print}'
echo ""

# Last 7 days coverage
echo "📅 Coverage (Last 7 Days)"
echo "-" | awk '{s=sprintf("%80s",""); gsub(/ /,"-",$0); print}'
bq query --use_legacy_sql=false --format=pretty "
SELECT
  cache_date,
  COUNT(*) as records,
  COUNT(DISTINCT player_lookup) as players,
  COUNTIF(is_production_ready = TRUE) as ready,
  ROUND(100.0 * COUNTIF(is_production_ready = TRUE) / COUNT(*), 1) as pct_ready,
  ROUND(AVG(quality_score), 1) as avg_quality
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY cache_date
ORDER BY cache_date DESC
"

echo ""
echo "📈 Quality Trends"
echo "-" | awk '{s=sprintf("%80s",""); gsub(/ /,"-",$0); print}'
bq query --use_legacy_sql=false --format=pretty "
SELECT
  cache_date,
  COUNTIF(quality_tier = 'EXCELLENT') as excellent,
  COUNTIF(quality_tier = 'GOOD') as good,
  COUNTIF(quality_tier = 'ACCEPTABLE') as acceptable,
  COUNTIF(quality_tier = 'POOR') as poor,
  COUNTIF(quality_tier IS NULL) as no_tier
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY cache_date
ORDER BY cache_date DESC
"

echo ""
echo "🔍 NULL Rate Analysis"
echo "-" | awk '{s=sprintf("%80s",""); gsub(/ /,"-",$0); print}'
bq query --use_legacy_sql=false --format=pretty "
SELECT
  cache_date,
  ROUND(100.0 * COUNTIF(points_avg_last_10 IS NULL) / COUNT(*), 2) as null_points_pct,
  ROUND(100.0 * COUNTIF(minutes_avg_last_10 IS NULL) / COUNT(*), 2) as null_minutes_pct,
  ROUND(100.0 * COUNTIF(usage_rate_last_10 IS NULL) / COUNT(*), 2) as null_usage_pct,
  ROUND(100.0 * COUNTIF(ts_pct_last_10 IS NULL) / COUNT(*), 2) as null_ts_pct
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY cache_date
ORDER BY cache_date DESC
"

echo ""
echo "⏱️  Processing Time Analysis"
echo "-" | awk '{s=sprintf("%80s",""); gsub(/ /,"-",$0); print}'
bq query --use_legacy_sql=false --format=pretty "
SELECT
  cache_date,
  MIN(processed_at) as first_processed,
  MAX(processed_at) as last_processed,
  TIMESTAMP_DIFF(MAX(processed_at), MIN(processed_at), MINUTE) as processing_duration_min
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND processed_at IS NOT NULL
GROUP BY cache_date
ORDER BY cache_date DESC
"

echo ""
echo "🎯 Downstream Impact"
echo "-" | awk '{s=sprintf("%80s",""); gsub(/ /,"-",$0); print}'
bq query --use_legacy_sql=false --format=pretty "
WITH features AS (
  SELECT cache_date, COUNT(*) as feature_records
  FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
  WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY cache_date
),
predictions AS (
  SELECT game_date, COUNT(*) as prediction_count
  FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND is_active = TRUE
  GROUP BY game_date
)
SELECT
  f.cache_date,
  f.feature_records,
  IFNULL(p.prediction_count, 0) as predictions,
  ROUND(IFNULL(p.prediction_count, 0) * 100.0 / f.feature_records, 1) as conversion_pct
FROM features f
LEFT JOIN predictions p ON f.cache_date = p.game_date
ORDER BY f.cache_date DESC
"

echo ""
echo "⚠️  Common Issues (Last 7 Days)"
echo "-" | awk '{s=sprintf("%80s",""); gsub(/ /,"-",$0); print}'
bq query --use_legacy_sql=false --format=pretty "
SELECT
  insufficient_data_reason,
  COUNT(*) as occurrence_count,
  APPROX_TOP_COUNT(cache_date, 1)[OFFSET(0)].value as most_recent_date
FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND insufficient_data_reason IS NOT NULL
GROUP BY insufficient_data_reason
ORDER BY occurrence_count DESC
LIMIT 10
"

echo ""
echo "✅ Summary"
echo "=" | awk '{s=sprintf("%80s",""); gsub(/ /,"=",$0); print}'

# Calculate summary metrics
SUMMARY=$(bq query --use_legacy_sql=false --format=csv "
SELECT
  COUNT(DISTINCT cache_date) as unique_dates,
  SUM(total) as total_records,
  ROUND(AVG(pct_ready), 1) as avg_readiness,
  MIN(pct_ready) as min_readiness,
  COUNTIF(pct_ready = 100.0) as perfect_days
FROM (
  SELECT
    cache_date,
    COUNT(*) as total,
    ROUND(100.0 * COUNTIF(is_production_ready = TRUE) / COUNT(*), 1) as pct_ready
  FROM \`nba-props-platform.nba_precompute.player_daily_cache\`
  WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY cache_date
)
" | tail -1)

echo "$SUMMARY" | awk -F',' '{
  printf "Unique Dates:      %s\n", $1
  printf "Total Records:     %s\n", $2
  printf "Avg Readiness:     %s%%\n", $3
  printf "Min Readiness:     %s%%\n", $4
  printf "Perfect Days:      %s/7\n", $5
}'

echo ""
echo "Report complete! ✅"
