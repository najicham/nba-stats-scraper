#!/bin/bash
# deploy_nba_grading_alerts.sh - Deploy NBA Grading Alerts Cloud Function
#
# Deploys alerting service that monitors grading health and sends Slack alerts.
#
# Prerequisites:
# - Slack webhook URL stored in Secret Manager: nba-grading-slack-webhook
#
# Usage: ./bin/alerts/deploy_nba_grading_alerts.sh

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
FUNCTION_NAME="nba-grading-alerts"
SERVICE_ACCOUNT="${PROJECT_ID}@appspot.gserviceaccount.com"

echo "========================================"
echo " Deploying NBA Grading Alerts"
echo "========================================"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Function: $FUNCTION_NAME"
echo ""

# Check if webhook secret exists
echo "Checking for webhook URL in Secret Manager..."
if ! gcloud secrets describe nba-grading-slack-webhook --project=$PROJECT_ID &>/dev/null; then
    echo ""
    echo "❌ ERROR: Slack webhook not found in Secret Manager"
    echo ""
    echo "Please create the secret first:"
    echo "  1. Get your Slack webhook URL from https://api.slack.com/apps"
    echo "  2. Run:"
    echo "     echo 'YOUR_WEBHOOK_URL' | gcloud secrets create nba-grading-slack-webhook \\"
    echo "       --data-file=- --replication-policy=automatic --project=$PROJECT_ID"
    echo ""
    exit 1
fi

echo "✅ Webhook secret found"

# Grant service account access to secret if not already granted
echo "Granting secret access to service account..."
gcloud secrets add-iam-policy-binding nba-grading-slack-webhook \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor" \
    --project=$PROJECT_ID \
    --quiet 2>/dev/null || echo "  (Permission already exists)"

echo "✅ Service account has secret access"
echo ""

# Deploy Cloud Function
echo "Deploying Cloud Function..."
echo ""

gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime=python311 \
    --region=$REGION \
    --source=services/nba_grading_alerts \
    --entry-point=main \
    --trigger-http \
    --allow-unauthenticated \
    --set-secrets="SLACK_WEBHOOK_URL=nba-grading-slack-webhook:latest" \
    --set-env-vars="ALERT_THRESHOLD_ACCURACY_MIN=55,ALERT_THRESHOLD_UNGRADEABLE_MAX=20,ALERT_THRESHOLD_DAYS=7,SEND_DAILY_SUMMARY=false" \
    --timeout=60s \
    --memory=256Mi \
    --max-instances=1 \
    --project=$PROJECT_ID

echo ""
echo "✅ Cloud Function deployed"

# Get function URL
FUNCTION_URL=$(gcloud functions describe $FUNCTION_NAME --region=$REGION --gen2 --format='value(serviceConfig.uri)' --project=$PROJECT_ID)
echo "Function URL: $FUNCTION_URL"
echo ""

# Create or update Cloud Scheduler job
echo "Setting up Cloud Scheduler job..."

# Schedule: 12:30 PM PT = 20:30 UTC (standard time) or 19:30 UTC (daylight)
# Using 20:30 UTC to be safe
SCHEDULE="30 20 * * *"

if gcloud scheduler jobs describe nba-grading-alerts-daily --location=$REGION --project=$PROJECT_ID &>/dev/null; then
    echo "Updating existing scheduler job..."
    gcloud scheduler jobs update http nba-grading-alerts-daily \
        --location=$REGION \
        --schedule="$SCHEDULE" \
        --uri="$FUNCTION_URL" \
        --http-method=POST \
        --time-zone="America/Los_Angeles" \
        --project=$PROJECT_ID \
        --quiet
else
    echo "Creating new scheduler job..."
    gcloud scheduler jobs create http nba-grading-alerts-daily \
        --location=$REGION \
        --schedule="$SCHEDULE" \
        --uri="$FUNCTION_URL" \
        --http-method=POST \
        --time-zone="America/Los_Angeles" \
        --description="Daily NBA grading health check and Slack alerts" \
        --project=$PROJECT_ID
fi

echo "✅ Scheduler job configured"
echo ""

# Test the function
echo "Testing Cloud Function..."
echo ""

RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" "$FUNCTION_URL")
HTTP_STATUS=$(echo "$RESPONSE" | grep "HTTP_STATUS" | cut -d: -f2)
BODY=$(echo "$RESPONSE" | sed '/HTTP_STATUS/d')

if [ "$HTTP_STATUS" = "200" ]; then
    echo "✅ Function test successful!"
    echo ""
    echo "Response:"
    echo "$BODY" | python3 -m json.tool 2>/dev/null || echo "$BODY"
else
    echo "⚠️  Function returned status: $HTTP_STATUS"
    echo "$BODY"
fi

echo ""
echo "========================================"
echo " Deployment Complete!"
echo "========================================"
echo ""
echo "📋 Summary:"
echo "  Function: $FUNCTION_NAME"
echo "  URL: $FUNCTION_URL"
echo "  Schedule: Daily at 12:30 PM PT"
echo "  Thresholds:"
echo "    - Accuracy minimum: 55%"
echo "    - Ungradeable maximum: 20%"
echo "    - Check period: 7 days"
echo ""
echo "🧪 Testing:"
echo "  Manual trigger:"
echo "    gcloud scheduler jobs run nba-grading-alerts-daily --location=$REGION"
echo ""
echo "  View logs:"
echo "    gcloud functions logs read $FUNCTION_NAME --region=$REGION --limit=50"
echo ""
echo "  View scheduler:"
echo "    gcloud scheduler jobs describe nba-grading-alerts-daily --location=$REGION"
echo ""
echo "⚙️  Configuration:"
echo "  To enable daily summary:"
echo "    gcloud functions deploy $FUNCTION_NAME --update-env-vars SEND_DAILY_SUMMARY=true --region=$REGION --gen2"
echo ""
echo "  To change thresholds:"
echo "    gcloud functions deploy $FUNCTION_NAME --update-env-vars ALERT_THRESHOLD_ACCURACY_MIN=50 --region=$REGION --gen2"
echo ""
echo "✅ Check Slack channel #nba-grading-alerts for test message!"
echo ""
