#!/bin/bash

# Deploy source block alert Cloud Function

set -e

FUNCTION_NAME="source-block-alert"
REGION="us-west2"
PROJECT_ID="nba-props-platform"
SECRET_NAME="slack-webhook-monitoring-warning"  # Use existing Secret Manager secret

echo "Deploying $FUNCTION_NAME to $PROJECT_ID..."
echo "Using Slack webhook from Secret Manager: $SECRET_NAME"

gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime=python311 \
    --region=$REGION \
    --source=. \
    --entry-point=source_block_alert \
    --trigger-http \
    --allow-unauthenticated \
    --set-secrets="SLACK_WEBHOOK_URL=${SECRET_NAME}:latest" \
    --memory=256MB \
    --timeout=60s \
    --max-instances=1 \
    --project=$PROJECT_ID

echo "✅ Function deployed!"
echo ""
echo "Setting up Cloud Scheduler job to run every 6 hours..."

# Create Cloud Scheduler job (if doesn't exist)
gcloud scheduler jobs create http ${FUNCTION_NAME}-scheduler \
    --location=$REGION \
    --schedule="0 */6 * * *" \
    --uri="https://$REGION-$PROJECT_ID.cloudfunctions.net/$FUNCTION_NAME" \
    --http-method=POST \
    --project=$PROJECT_ID \
    --time-zone="America/New_York" \
    --attempt-deadline=60s \
    || echo "Scheduler job already exists, updating..."

# Update if exists
gcloud scheduler jobs update http ${FUNCTION_NAME}-scheduler \
    --location=$REGION \
    --schedule="0 */6 * * *" \
    --uri="https://$REGION-$PROJECT_ID.cloudfunctions.net/$FUNCTION_NAME" \
    --time-zone="America/New_York" \
    --project=$PROJECT_ID \
    || true

echo "✅ Deployment complete!"
echo ""
echo "Function URL: https://$REGION-$PROJECT_ID.cloudfunctions.net/$FUNCTION_NAME"
echo "Schedule: Every 6 hours (0, 6, 12, 18:00 ET)"
echo ""
echo "Test manually:"
echo "curl -X POST https://$REGION-$PROJECT_ID.cloudfunctions.net/$FUNCTION_NAME"
