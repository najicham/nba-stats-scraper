#!/bin/bash
# Setup automated deployment drift monitoring
#
# Creates:
# 1. Cloud Function to check drift
# 2. Cloud Scheduler job to trigger every 2 hours
# 3. Pub/Sub topic for scheduler → function communication

set -e

PROJECT_ID="nba-props-platform"
REGION="us-west2"
FUNCTION_NAME="deployment-drift-monitor"
TOPIC_NAME="deployment-drift-check"
SCHEDULE_NAME="deployment-drift-schedule"

# Schedule: Every 2 hours during business hours (8 AM - 8 PM PT)
# Cron: 0 8-20/2 * * * (at minute 0, every 2 hours from 8 through 20)
CRON_SCHEDULE="0 8-20/2 * * *"
TIMEZONE="America/Los_Angeles"

echo "======================================"
echo "Setup Deployment Drift Monitoring"
echo "======================================"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Schedule: $CRON_SCHEDULE ($TIMEZONE)"
echo ""

# Step 1: Create Pub/Sub topic
echo "[1/4] Creating Pub/Sub topic..."
gcloud pubsub topics create $TOPIC_NAME \
    --project=$PROJECT_ID \
    --quiet 2>/dev/null || echo "Topic already exists"

# Step 2: Deploy Cloud Function
echo "[2/4] Deploying Cloud Function..."
gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime=python311 \
    --region=$REGION \
    --source=cloud_functions/deployment_drift_monitor \
    --entry-point=deployment_drift_monitor_scheduled \
    --trigger-topic=$TOPIC_NAME \
    --timeout=60s \
    --memory=256MB \
    --set-env-vars="GCP_PROJECT=$PROJECT_ID" \
    --project=$PROJECT_ID

# Step 3: Create Cloud Scheduler job
echo "[3/4] Creating Cloud Scheduler job..."
gcloud scheduler jobs create pubsub $SCHEDULE_NAME \
    --location=$REGION \
    --schedule="$CRON_SCHEDULE" \
    --time-zone="$TIMEZONE" \
    --topic=$TOPIC_NAME \
    --message-body='{"trigger":"scheduled"}' \
    --project=$PROJECT_ID \
    --quiet 2>/dev/null || {
        echo "Scheduler job already exists, updating..."
        gcloud scheduler jobs update pubsub $SCHEDULE_NAME \
            --location=$REGION \
            --schedule="$CRON_SCHEDULE" \
            --time-zone="$TIMEZONE" \
            --project=$PROJECT_ID
    }

# Step 4: Test the function
echo "[4/4] Testing Cloud Function..."
echo "Triggering manual run..."
gcloud scheduler jobs run $SCHEDULE_NAME \
    --location=$REGION \
    --project=$PROJECT_ID

echo ""
echo "✅ Setup complete!"
echo ""
echo "Monitoring schedule:"
echo "  - Checks every 2 hours (8 AM - 8 PM PT)"
echo "  - Alerts to Slack #nba-alerts for drift"
echo ""
echo "Manual trigger:"
echo "  gcloud scheduler jobs run $SCHEDULE_NAME --location=$REGION"
echo ""
echo "View logs:"
echo "  gcloud functions logs read $FUNCTION_NAME --region=$REGION --limit=20"
echo ""
