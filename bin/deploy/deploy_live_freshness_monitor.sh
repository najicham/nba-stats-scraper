#!/bin/bash
# Deploy Live Freshness Monitor Cloud Function and Scheduler
#
# This monitors live data freshness and triggers self-healing when stale.
# Runs every 5 minutes during game hours (4 PM - 1 AM ET).
#
# Usage:
#   ./bin/deploy/deploy_live_freshness_monitor.sh

set -euo pipefail

# Configuration
PROJECT_ID="${GCP_PROJECT:-nba-props-platform}"
REGION="us-west2"
FUNCTION_NAME="live-freshness-monitor"
SERVICE_ACCOUNT="processor-sa@${PROJECT_ID}.iam.gserviceaccount.com"

# Slack webhook URL for alerts
SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}"
if [ -z "$SLACK_WEBHOOK_URL" ]; then
    echo "Warning: SLACK_WEBHOOK_URL not set. Staleness alerts will be disabled."
    echo "To enable alerts, run: export SLACK_WEBHOOK_URL=<your-webhook-url>"
fi

echo "=== Live Freshness Monitor Deployment ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Function: $FUNCTION_NAME"
echo ""

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
FUNC_SRC="$PROJECT_ROOT/orchestration/cloud_functions/live_freshness_monitor"

echo "=== Deploying Cloud Function ==="

# Build env vars string
ENV_VARS="GCP_PROJECT=$PROJECT_ID"
if [ -n "$SLACK_WEBHOOK_URL" ]; then
    ENV_VARS="$ENV_VARS,SLACK_WEBHOOK_URL=$SLACK_WEBHOOK_URL"
    echo "SLACK_WEBHOOK_URL configured for staleness alerts"
fi

# Deploy the function
gcloud functions deploy "$FUNCTION_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --runtime=python311 \
    --memory=256MB \
    --timeout=180s \
    --max-instances=1 \
    --min-instances=0 \
    --entry-point=main \
    --trigger-http \
    --allow-unauthenticated \
    --service-account="$SERVICE_ACCOUNT" \
    --source="$FUNC_SRC" \
    --set-env-vars="$ENV_VARS" \
    --no-gen2

# Get the function URL
FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --format="value(httpsTrigger.url)")

echo "Function URL: $FUNCTION_URL"
echo ""

echo "=== Deploying Cloud Scheduler ==="

# Delete existing scheduler if exists
gcloud scheduler jobs delete "live-freshness-monitor" \
    --project="$PROJECT_ID" \
    --location="$REGION" \
    --quiet 2>/dev/null || true

# Create scheduler - every 5 min during game hours (4 PM - 1 AM ET)
gcloud scheduler jobs create http "live-freshness-monitor" \
    --project="$PROJECT_ID" \
    --location="$REGION" \
    --schedule="*/5 16-23,0-1 * * *" \
    --time-zone="America/New_York" \
    --uri="$FUNCTION_URL" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body='{}' \
    --attempt-deadline=180s \
    --description="Monitor live data freshness and trigger self-healing (4 PM - 1 AM ET)"

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Scheduler: */5 16-23,0-1 * * * America/New_York"
echo "           (Every 5 min from 4 PM to 1 AM ET)"
echo ""
echo "To test manually:"
echo "  curl -X POST '$FUNCTION_URL'"
echo ""
echo "To check logs:"
echo "  gcloud functions logs read $FUNCTION_NAME --project=$PROJECT_ID --region=$REGION --limit=20"
echo ""
