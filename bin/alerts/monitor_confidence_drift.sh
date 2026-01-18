#!/bin/bash

# NBA Prediction Platform - Confidence Distribution Drift Monitor
# Checks for unusual confidence score patterns
# Designed to run via Cloud Scheduler every 2 hours
# Usage: ./bin/alerts/monitor_confidence_drift.sh

set -euo pipefail

PROJECT="nba-props-platform"
DRIFT_THRESHOLD=30  # Percent of predictions outside normal range
LOOKBACK_HOURS=2    # Check predictions from last 2 hours

# Check confidence distribution
RESULT=$(bq query --use_legacy_sql=false --project_id="$PROJECT" --format=json '
WITH recent_predictions AS (
  SELECT
    confidence_score,
    CASE
      WHEN confidence_score < 0.75 OR confidence_score > 0.95 THEN 1
      ELSE 0
    END as outside_range
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE system_id = "catboost_v8"
    AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL '"$LOOKBACK_HOURS"' HOUR)
)
SELECT
  COUNT(*) as total_predictions,
  ROUND(AVG(confidence_score) * 100, 1) as avg_confidence,
  ROUND(MIN(confidence_score) * 100, 1) as min_confidence,
  ROUND(MAX(confidence_score) * 100, 1) as max_confidence,
  SUM(outside_range) as outside_normal_range,
  ROUND(100.0 * SUM(outside_range) / NULLIF(COUNT(*), 0), 1) as drift_pct,
  COUNTIF(confidence_score = 0.50) as fallback_count
FROM recent_predictions
' 2>/dev/null)

TOTAL=$(echo "$RESULT" | jq -r '.[0].total_predictions // "0"')
AVG_CONF=$(echo "$RESULT" | jq -r '.[0].avg_confidence // "0"')
DRIFT_PCT=$(echo "$RESULT" | jq -r '.[0].drift_pct // "0"')
FALLBACK=$(echo "$RESULT" | jq -r '.[0].fallback_count // "0"')
MIN_CONF=$(echo "$RESULT" | jq -r '.[0].min_confidence // "0"')
MAX_CONF=$(echo "$RESULT" | jq -r '.[0].max_confidence // "0"')

# Skip check if no predictions in lookback window (normal during off-hours)
if [ "$TOTAL" -eq 0 ]; then
    echo "INFO: No predictions in last $LOOKBACK_HOURS hours (normal during off-season/off-hours)"
    echo "{\"severity\":\"INFO\",\"message\":\"NBA_CONFIDENCE_CHECK_SKIPPED\",\"status\":\"SKIPPED\",\"reason\":\"No predictions in lookback window\",\"lookback_hours\":$LOOKBACK_HOURS}" | \
        gcloud logging write nba-confidence-drift-monitor --severity=INFO --project="$PROJECT" -
    exit 0
fi

# Log to Cloud Logging (structured logging for metric creation)
if [ "$TOTAL" -gt 0 ] && [ "$FALLBACK" == "$TOTAL" ]; then
    # CRITICAL: All predictions are fallback (model not loaded)
    echo "{\"severity\":\"ERROR\",\"message\":\"NBA_CONFIDENCE_ALL_FALLBACK\",\"total_predictions\":$TOTAL,\"fallback_count\":$FALLBACK,\"status\":\"CRITICAL\",\"reason\":\"All predictions are fallback mode (50% confidence) - model not loaded\"}" | \
        gcloud logging write nba-confidence-drift-monitor --severity=ERROR --project="$PROJECT" -
    echo "CRITICAL: All $TOTAL predictions are fallback mode - model not loaded"
    exit 1
elif [ "$(echo "$DRIFT_PCT >= $DRIFT_THRESHOLD" | bc -l)" -eq 1 ]; then
    # WARNING: High drift detected
    echo "{\"severity\":\"WARNING\",\"message\":\"NBA_CONFIDENCE_DRIFT_HIGH\",\"total_predictions\":$TOTAL,\"drift_pct\":$DRIFT_PCT,\"avg_confidence\":$AVG_CONF,\"min_confidence\":$MIN_CONF,\"max_confidence\":$MAX_CONF,\"fallback_count\":$FALLBACK,\"status\":\"WARNING\",\"reason\":\"High drift: ${DRIFT_PCT}% outside normal range (threshold: ${DRIFT_THRESHOLD}%)\"}" | \
        gcloud logging write nba-confidence-drift-monitor --severity=WARNING --project="$PROJECT" -
    echo "WARNING: High confidence drift detected: ${DRIFT_PCT}% outside normal range"
    exit 1
else
    # OK: Normal distribution
    echo "{\"severity\":\"INFO\",\"message\":\"NBA_CONFIDENCE_HEALTHY\",\"total_predictions\":$TOTAL,\"drift_pct\":$DRIFT_PCT,\"avg_confidence\":$AVG_CONF,\"min_confidence\":$MIN_CONF,\"max_confidence\":$MAX_CONF,\"fallback_count\":$FALLBACK,\"status\":\"OK\"}" | \
        gcloud logging write nba-confidence-drift-monitor --severity=INFO --project="$PROJECT" -
    echo "OK: Confidence distribution healthy (drift: ${DRIFT_PCT}%, avg: ${AVG_CONF}%)"
fi

exit 0
