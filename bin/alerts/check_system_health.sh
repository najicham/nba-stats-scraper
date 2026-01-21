#!/bin/bash

# NBA Prediction Platform - System Health Check
# Comprehensive health check for all monitoring metrics
# Usage: ./bin/alerts/check_system_health.sh

set -euo pipefail

PROJECT="nba-props-platform"
REGION="us-west2"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Thresholds
PREDICTION_STALE_THRESHOLD_MINUTES=120
FEATURE_STALE_THRESHOLD_HOURS=4
DLQ_DEPTH_THRESHOLD=50
DRIFT_THRESHOLD_PERCENT=30

echo "========================================="
echo "NBA Prediction Platform - Health Check"
echo "========================================="
echo "Project: $PROJECT"
echo "Time: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo ""

# Function to print status
print_status() {
    local status=$1
    local message=$2
    if [ "$status" == "OK" ]; then
        echo -e "${GREEN}✅ OK${NC}: $message"
    elif [ "$status" == "WARNING" ]; then
        echo -e "${YELLOW}⚠️  WARNING${NC}: $message"
    elif [ "$status" == "CRITICAL" ]; then
        echo -e "${RED}❌ CRITICAL${NC}: $message"
    else
        echo -e "${BLUE}ℹ️  INFO${NC}: $message"
    fi
}

# Function to run BigQuery query quietly
run_bq_query() {
    bq query --use_legacy_sql=false --project_id="$PROJECT" --format=json "$1" 2>/dev/null
}

# =========================================
# 1. PREDICTION FRESHNESS CHECK
# =========================================
echo "---"
echo "1. PREDICTION FRESHNESS CHECK"
echo "---"

PREDICTION_QUERY='
SELECT
  MAX(created_at) as last_prediction,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), MINUTE) as minutes_ago,
  COUNT(*) as total_predictions_24h
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = "catboost_v8"
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
'

PREDICTION_RESULT=$(run_bq_query "$PREDICTION_QUERY")
MINUTES_AGO=$(echo "$PREDICTION_RESULT" | jq -r '.[0].minutes_ago // "null"')
TOTAL_24H=$(echo "$PREDICTION_RESULT" | jq -r '.[0].total_predictions_24h // "0"')
LAST_PREDICTION=$(echo "$PREDICTION_RESULT" | jq -r '.[0].last_prediction // "never"')

if [ "$MINUTES_AGO" == "null" ]; then
    print_status "CRITICAL" "No predictions found in last 24 hours"
elif [ "$MINUTES_AGO" -gt "$PREDICTION_STALE_THRESHOLD_MINUTES" ]; then
    print_status "WARNING" "Last prediction was $MINUTES_AGO minutes ago (threshold: $PREDICTION_STALE_THRESHOLD_MINUTES min)"
    echo "   Last prediction: $LAST_PREDICTION"
else
    print_status "OK" "Last prediction was $MINUTES_AGO minutes ago"
    echo "   Last prediction: $LAST_PREDICTION"
    echo "   Predictions in last 24h: $TOTAL_24H"
fi

# =========================================
# 2. DLQ DEPTH CHECK
# =========================================
echo ""
echo "---"
echo "2. DEAD LETTER QUEUE (DLQ) CHECK"
echo "---"

DLQ_DEPTH=$(gcloud pubsub subscriptions describe prediction-request-dlq-sub \
    --project="$PROJECT" \
    --format="value(numUndeliveredMessages)" 2>/dev/null || echo "0")

# Handle empty response
if [ -z "$DLQ_DEPTH" ]; then
    DLQ_DEPTH=0
fi

if [ "$DLQ_DEPTH" -gt "$DLQ_DEPTH_THRESHOLD" ]; then
    print_status "WARNING" "DLQ has $DLQ_DEPTH undelivered messages (threshold: $DLQ_DEPTH_THRESHOLD)"
elif [ "$DLQ_DEPTH" -gt 0 ]; then
    print_status "OK" "DLQ has $DLQ_DEPTH messages (below threshold)"
else
    print_status "OK" "DLQ is empty (0 messages)"
fi

# =========================================
# 3. FEATURE FRESHNESS CHECK
# =========================================
echo ""
echo "---"
echo "3. FEATURE PIPELINE FRESHNESS CHECK"
echo "---"

FEATURE_QUERY='
SELECT
  MAX(created_at) as last_feature_update,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), HOUR) as hours_ago,
  COUNT(DISTINCT player_lookup) as players_with_features,
  MIN(game_date) as earliest_game,
  MAX(game_date) as latest_game
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= CURRENT_DATE()
'

FEATURE_RESULT=$(run_bq_query "$FEATURE_QUERY")
HOURS_AGO=$(echo "$FEATURE_RESULT" | jq -r '.[0].hours_ago // "null"')
PLAYER_COUNT=$(echo "$FEATURE_RESULT" | jq -r '.[0].players_with_features // "0"')
LAST_FEATURE=$(echo "$FEATURE_RESULT" | jq -r '.[0].last_feature_update // "never"')

if [ "$HOURS_AGO" == "null" ]; then
    print_status "CRITICAL" "No features found for current/upcoming games"
elif [ "$HOURS_AGO" -ge "$FEATURE_STALE_THRESHOLD_HOURS" ]; then
    print_status "WARNING" "Features are $HOURS_AGO hours old (threshold: $FEATURE_STALE_THRESHOLD_HOURS hours)"
    echo "   Last feature update: $LAST_FEATURE"
elif [ "$HOURS_AGO" -ge 2 ]; then
    print_status "OK" "Features are $HOURS_AGO hours old (acceptable)"
    echo "   Last feature update: $LAST_FEATURE"
    echo "   Players with features: $PLAYER_COUNT"
else
    print_status "OK" "Features are fresh ($HOURS_AGO hours old)"
    echo "   Last feature update: $LAST_FEATURE"
    echo "   Players with features: $PLAYER_COUNT"
fi

# =========================================
# 4. CONFIDENCE DISTRIBUTION CHECK
# =========================================
echo ""
echo "---"
echo "4. CONFIDENCE DISTRIBUTION DRIFT CHECK"
echo "---"

CONFIDENCE_QUERY='
WITH recent_predictions AS (
  SELECT
    confidence_score,
    CASE
      WHEN confidence_score < 0.75 OR confidence_score > 0.95 THEN 1
      ELSE 0
    END as outside_range
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE system_id = "catboost_v8"
    AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
)
SELECT
  COUNT(*) as total_predictions,
  ROUND(AVG(confidence_score) * 100, 1) as avg_confidence,
  ROUND(MIN(confidence_score) * 100, 1) as min_confidence,
  ROUND(MAX(confidence_score) * 100, 1) as max_confidence,
  SUM(outside_range) as outside_normal_range,
  ROUND(100.0 * SUM(outside_range) / COUNT(*), 1) as drift_pct,
  COUNTIF(confidence_score = 0.50) as fallback_count
FROM recent_predictions
'

CONFIDENCE_RESULT=$(run_bq_query "$CONFIDENCE_QUERY")
AVG_CONF=$(echo "$CONFIDENCE_RESULT" | jq -r '.[0].avg_confidence // "0"')
MIN_CONF=$(echo "$CONFIDENCE_RESULT" | jq -r '.[0].min_confidence // "0"')
MAX_CONF=$(echo "$CONFIDENCE_RESULT" | jq -r '.[0].max_confidence // "0"')
DRIFT_PCT=$(echo "$CONFIDENCE_RESULT" | jq -r '.[0].drift_pct // "0"')
FALLBACK_COUNT=$(echo "$CONFIDENCE_RESULT" | jq -r '.[0].fallback_count // "0"')
TOTAL_CONF=$(echo "$CONFIDENCE_RESULT" | jq -r '.[0].total_predictions // "0"')

# Check if all predictions are fallback (50%)
if [ "$TOTAL_CONF" -gt 0 ] && [ "$FALLBACK_COUNT" == "$TOTAL_CONF" ]; then
    print_status "CRITICAL" "All predictions are fallback mode (50% confidence)"
    echo "   This indicates model not loaded correctly"
elif [ "$(echo "$DRIFT_PCT >= $DRIFT_THRESHOLD_PERCENT" | bc -l)" -eq 1 ]; then
    print_status "WARNING" "High confidence drift: ${DRIFT_PCT}% outside normal range (threshold: ${DRIFT_THRESHOLD_PERCENT}%)"
    echo "   Avg: ${AVG_CONF}%, Min: ${MIN_CONF}%, Max: ${MAX_CONF}%"
    echo "   Fallback predictions: $FALLBACK_COUNT"
elif [ "$(echo "$DRIFT_PCT >= 15" | bc -l)" -eq 1 ]; then
    print_status "OK" "Moderate drift: ${DRIFT_PCT}% outside normal range (acceptable)"
    echo "   Avg: ${AVG_CONF}%, Min: ${MIN_CONF}%, Max: ${MAX_CONF}%"
    echo "   Fallback predictions: $FALLBACK_COUNT"
else
    print_status "OK" "Confidence distribution healthy (drift: ${DRIFT_PCT}%)"
    echo "   Avg: ${AVG_CONF}%, Min: ${MIN_CONF}%, Max: ${MAX_CONF}%"
    echo "   Predictions in last 24h: $TOTAL_CONF"
    echo "   Fallback predictions: $FALLBACK_COUNT"
fi

# =========================================
# 5. MODEL LOADING STATUS CHECK
# =========================================
echo ""
echo "---"
echo "5. MODEL LOADING STATUS CHECK"
echo "---"

# Check environment variable is set
ENV_VAR=$(gcloud run services describe prediction-worker \
    --region="$REGION" \
    --project="$PROJECT" \
    --format="json" 2>/dev/null | jq -r '.spec.template.spec.containers[0].env[] | select(.name=="CATBOOST_V8_MODEL_PATH") | .value // "NOT_SET"')

if [ "$ENV_VAR" == "NOT_SET" ] || [ -z "$ENV_VAR" ]; then
    print_status "CRITICAL" "CATBOOST_V8_MODEL_PATH environment variable is NOT SET"
else
    print_status "OK" "CATBOOST_V8_MODEL_PATH is set"
    echo "   Path: $ENV_VAR"

    # Check recent model loading logs
    MODEL_LOAD_SUCCESS=$(gcloud logging read 'resource.labels.service_name="prediction-worker"
        AND (textPayload=~"✓ CATBOOST_V8_MODEL_PATH" OR textPayload=~"model loaded successfully")
        AND timestamp>="'$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%S)'Z"' \
        --project="$PROJECT" \
        --limit=1 \
        --format=json 2>/dev/null | jq -r 'length')

    if [ "$MODEL_LOAD_SUCCESS" -gt 0 ]; then
        print_status "OK" "Model loading successful in last 24 hours"
    else
        print_status "WARNING" "No successful model load logs in last 24 hours (may be normal if no restarts)"
    fi
fi

# =========================================
# 6. ALERT STATUS CHECK
# =========================================
echo ""
echo "---"
echo "6. ALERT STATUS CHECK"
echo "---"

ALERTS=$(gcloud alpha monitoring policies list \
    --project="$PROJECT" \
    --format=json 2>/dev/null | jq -r '.[] | select(.displayName | contains("NBA")) | {name: .displayName, enabled: .enabled} | "\(.name)|\(.enabled)"')

ALERT_COUNT=0
ENABLED_COUNT=0

while IFS='|' read -r name enabled; do
    ALERT_COUNT=$((ALERT_COUNT + 1))
    if [ "$enabled" == "true" ]; then
        ENABLED_COUNT=$((ENABLED_COUNT + 1))
        echo "   ✅ $name"
    else
        echo "   ❌ $name (DISABLED)"
    fi
done <<< "$ALERTS"

if [ "$ENABLED_COUNT" -eq "$ALERT_COUNT" ] && [ "$ALERT_COUNT" -gt 0 ]; then
    print_status "OK" "All $ALERT_COUNT NBA alerts are enabled"
elif [ "$ALERT_COUNT" -eq 0 ]; then
    print_status "WARNING" "No NBA alerts found"
else
    print_status "WARNING" "$ENABLED_COUNT of $ALERT_COUNT alerts enabled"
fi

# =========================================
# 7. SERVICE STATUS CHECK
# =========================================
echo ""
echo "---"
echo "7. SERVICE STATUS CHECK"
echo "---"

SERVICE_STATUS=$(gcloud run services describe prediction-worker \
    --region="$REGION" \
    --project="$PROJECT" \
    --format=json 2>/dev/null | jq -r '.status.conditions[] | select(.type=="Ready") | .status')

LATEST_REVISION=$(gcloud run services describe prediction-worker \
    --region="$REGION" \
    --project="$PROJECT" \
    --format="value(status.latestReadyRevisionName)" 2>/dev/null)

if [ "$SERVICE_STATUS" == "True" ]; then
    print_status "OK" "prediction-worker service is Ready"
    echo "   Latest revision: $LATEST_REVISION"
else
    print_status "CRITICAL" "prediction-worker service is NOT Ready"
    echo "   Status: $SERVICE_STATUS"
fi

# =========================================
# SUMMARY
# =========================================
echo ""
echo "========================================="
echo "HEALTH CHECK SUMMARY"
echo "========================================="
echo ""

# Count issues
CRITICAL_COUNT=$(grep -c "❌ CRITICAL" <<< "$(print_status 'test' 'test')" 2>/dev/null || echo "0")
WARNING_COUNT=$(grep -c "⚠️  WARNING" <<< "$(print_status 'test' 'test')" 2>/dev/null || echo "0")

echo "Health check completed at $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo ""
echo "For detailed investigation, see:"
echo "  docs/04-deployment/ALERT-RUNBOOKS.md"
echo ""
echo "To check individual alerts:"
echo "  gcloud alpha monitoring policies list --project=$PROJECT"
echo ""

exit 0
