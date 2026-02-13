#!/bin/bash
# Feb 19 Phase 4 Quality Validation Script
#
# Monitors Phase 4 feature quality for the Feb 19 game day (10 games)
# Alerts if quality degrades below thresholds
#
# Usage: ./bin/monitoring/validate_phase4_quality_feb19.sh

set -e

GAME_DATE="${1:-2026-02-19}"
ALERT_THRESHOLD_QUALITY_READY=70  # Alert if < 70% quality_ready
ALERT_THRESHOLD_AVG_DEFAULTS=5.0   # Alert if avg defaults > 5.0

echo "=== Phase 4 Quality Validation for $GAME_DATE ==="
echo "Thresholds: quality_ready >= ${ALERT_THRESHOLD_QUALITY_READY}%, avg_defaults <= ${ALERT_THRESHOLD_AVG_DEFAULTS}"
echo ""

# Query Phase 4 quality metrics
QUERY="
WITH quality_metrics AS (
  SELECT
    game_date,
    COUNT(*) as total_players,
    COUNTIF(is_quality_ready) as quality_ready_count,
    ROUND(100.0 * COUNTIF(is_quality_ready) / COUNT(*), 1) as pct_quality_ready,
    ROUND(AVG(default_feature_count), 1) as avg_defaults,
    ROUND(AVG(feature_quality_score), 1) as avg_quality_score,
    COUNTIF(quality_alert_level = 'red') as red_alerts,
    COUNTIF(quality_alert_level = 'yellow') as yellow_alerts,
    COUNTIF(quality_alert_level = 'green') as green_alerts,
    -- Check for days_rest NULL issue (Session 236 root cause)
    COUNTIF(feature_39_quality < 100) as days_rest_missing
  FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
  WHERE game_date = '$GAME_DATE'
)
SELECT * FROM quality_metrics
"

echo "Querying Phase 4 quality metrics..."
RESULT=$(bq query --nouse_legacy_sql --format=csv "$QUERY")

echo "$RESULT"
echo ""

# Parse results
PCT_QUALITY_READY=$(echo "$RESULT" | tail -n 1 | cut -d',' -f4)
AVG_DEFAULTS=$(echo "$RESULT" | tail -n 1 | cut -d',' -f5)
DAYS_REST_MISSING=$(echo "$RESULT" | tail -n 1 | cut -d',' -f10)

# Check thresholds
ALERT=false

if (( $(echo "$PCT_QUALITY_READY < $ALERT_THRESHOLD_QUALITY_READY" | bc -l) )); then
  echo "🔴 ALERT: Quality ready ${PCT_QUALITY_READY}% < threshold ${ALERT_THRESHOLD_QUALITY_READY}%"
  ALERT=true
fi

if (( $(echo "$AVG_DEFAULTS > $ALERT_THRESHOLD_AVG_DEFAULTS" | bc -l) )); then
  echo "🔴 ALERT: Avg defaults ${AVG_DEFAULTS} > threshold ${ALERT_THRESHOLD_AVG_DEFAULTS}"
  ALERT=true
fi

if [[ "$DAYS_REST_MISSING" -gt 0 ]]; then
  echo "⚠️ WARNING: ${DAYS_REST_MISSING} players missing days_rest (Session 236 issue recurring)"
  ALERT=true
fi

if [[ "$ALERT" == "false" ]]; then
  echo "✅ All quality thresholds met for $GAME_DATE"
  exit 0
else
  echo ""
  echo "Run /validate-daily for full diagnostic"
  exit 1
fi
