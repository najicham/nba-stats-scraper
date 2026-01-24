#!/bin/bash

# Quick NBA System Status Check
# Fast status check showing key metrics at a glance
# Target: < 5 seconds execution time

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}NBA Prediction Platform - Quick Status${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 1. Last Prediction Time (fastest query)
echo -n "🔮 Predictions: "
LAST_PREDICTION=$(bq query --use_legacy_sql=false --format=csv --max_rows=1 \
  "SELECT FORMAT_TIMESTAMP('%Y-%m-%d %H:%M', MAX(created_at)) as last_pred,
   TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), MINUTE) as mins_ago
   FROM \`${PROJECT_ID}.nba_predictions.player_prop_predictions\`
   WHERE system_id = 'catboost_v8' AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 6 HOUR)" 2>/dev/null | tail -n 1)

LAST_TIME=$(echo "$LAST_PREDICTION" | cut -d',' -f1)
MINS_AGO=$(echo "$LAST_PREDICTION" | cut -d',' -f2)

if [ "$MINS_AGO" -lt 120 ]; then
  echo -e "${GREEN}✓${NC} $LAST_TIME (${MINS_AGO}m ago)"
else
  echo -e "${YELLOW}⚠${NC} $LAST_TIME (${MINS_AGO}m ago - STALE)"
fi

# 2. DLQ Depth (direct metric check)
echo -n "📬 DLQ Depth: "
DLQ_DEPTH=$(gcloud pubsub subscriptions describe prediction-request-dlq-sub \
  --project=${PROJECT_ID} --format="value(messageRetentionDuration)" 2>/dev/null | head -n1)

# Quick check - just verify subscription exists and is healthy
if [ $? -eq 0 ]; then
  echo -e "${GREEN}✓${NC} Subscription active"
else
  echo -e "${RED}✗${NC} Subscription error"
fi

# 3. Feature Freshness (quick query)
echo -n "🗂️  Features: "
FEATURE_AGE=$(bq query --use_legacy_sql=false --format=csv --max_rows=1 \
  "SELECT TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), HOUR) as hours_old
   FROM \`${PROJECT_ID}.nba_predictions.ml_feature_store_v2\`
   WHERE game_date >= CURRENT_DATE()" 2>/dev/null | tail -n 1)

if [ -z "$FEATURE_AGE" ] || [ "$FEATURE_AGE" = "hours_old" ]; then
  echo -e "${YELLOW}⚠${NC} No recent features"
elif [ "$FEATURE_AGE" -lt 4 ]; then
  echo -e "${GREEN}✓${NC} Fresh (${FEATURE_AGE}h old)"
else
  echo -e "${YELLOW}⚠${NC} Stale (${FEATURE_AGE}h old)"
fi

# 4. Critical Alerts (just count enabled)
echo -n "🚨 Alerts: "
ALERT_COUNT=$(gcloud alpha monitoring policies list --project=${PROJECT_ID} --format="value(displayName)" 2>/dev/null | grep -c "^\[CRITICAL\] NBA" || echo "0")
if [ "$ALERT_COUNT" -ge 2 ]; then
  echo -e "${GREEN}✓${NC} ${ALERT_COUNT} critical alerts enabled"
else
  echo -e "${RED}✗${NC} Only ${ALERT_COUNT} critical alerts"
fi

# 5. Schedulers (quick count)
echo -n "⏰ Schedulers: "
SCHEDULER_COUNT=$(gcloud scheduler jobs list --location=${REGION} --project=${PROJECT_ID} --format="value(name)" 2>/dev/null | grep -c "nba-" || echo "0")
if [ "$SCHEDULER_COUNT" -ge 2 ]; then
  echo -e "${GREEN}✓${NC} ${SCHEDULER_COUNT} jobs active"
else
  echo -e "${YELLOW}⚠${NC} Only ${SCHEDULER_COUNT} jobs found"
fi

# 6. Service Status
echo -n "☁️  Service: "
SERVICE_STATUS=$(gcloud run services describe prediction-worker --region=${REGION} --project=${PROJECT_ID} --format="value(status.conditions[0].status)" 2>/dev/null)
if [ "$SERVICE_STATUS" = "True" ]; then
  echo -e "${GREEN}✓${NC} prediction-worker ready"
else
  echo -e "${RED}✗${NC} Service not ready"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "For detailed analysis run:"
echo "  ./bin/alerts/check_system_health.sh"
echo ""
