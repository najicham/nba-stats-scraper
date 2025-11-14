#!/bin/bash
# Creates all 4 Cloud Scheduler jobs for Phase 1
# Save this as: bin/orchestration/add_scheduler_jobs_v2.sh

set -e

PROJECT_ID="nba-props-platform"
REGION="us-west2"
SERVICE_ACCOUNT="scheduler-orchestration@${PROJECT_ID}.iam.gserviceaccount.com"

# Get Cloud Run service URL
echo "Getting Cloud Run service URL..."
SERVICE_URL=$(gcloud run services describe nba-scrapers \
  --region=$REGION \
  --format="value(status.url)")

if [ -z "$SERVICE_URL" ]; then
    echo "❌ Error: Could not get Cloud Run service URL"
    exit 1
fi

echo "✅ Service URL: $SERVICE_URL"
echo ""

# Job 1: Daily Schedule Locker (5:00 AM ET)
echo "1️⃣  Creating: daily-schedule-locker"
gcloud scheduler jobs create http daily-schedule-locker \
  --location=$REGION \
  --schedule="0 10 * * *" \
  --time-zone="America/New_York" \
  --uri="${SERVICE_URL}/generate-daily-schedule" \
  --http-method=POST \
  --oidc-service-account-email=$SERVICE_ACCOUNT \
  --oidc-token-audience=$SERVICE_URL \
  --attempt-deadline=180s \
  --description="Generate daily workflow plan (5 AM ET)" \
  2>/dev/null && echo "✅ Created" || {
    echo "Job exists, updating..."
    gcloud scheduler jobs update http daily-schedule-locker \
      --location=$REGION \
      --schedule="0 10 * * *" \
      --uri="${SERVICE_URL}/generate-daily-schedule"
    echo "✅ Updated"
  }

# Job 2: Master Controller (hourly 6 AM-11 PM)
echo ""
echo "2️⃣  Creating: master-controller-hourly"
gcloud scheduler jobs create http master-controller-hourly \
  --location=$REGION \
  --schedule="0 6-23 * * *" \
  --time-zone="America/New_York" \
  --uri="${SERVICE_URL}/evaluate" \
  --http-method=POST \
  --oidc-service-account-email=$SERVICE_ACCOUNT \
  --oidc-token-audience=$SERVICE_URL \
  --attempt-deadline=180s \
  --description="Evaluate workflows hourly" \
  2>/dev/null && echo "✅ Created" || {
    echo "Job exists, updating..."
    gcloud scheduler jobs update http master-controller-hourly \
      --location=$REGION \
      --schedule="0 6-23 * * *" \
      --uri="${SERVICE_URL}/evaluate"
    echo "✅ Updated"
  }

# Job 3: Execute Workflows (5 min after controller)
echo ""
echo "3️⃣  Creating: execute-workflows"
gcloud scheduler jobs create http execute-workflows \
  --location=$REGION \
  --schedule="5 6-23 * * *" \
  --time-zone="America/New_York" \
  --uri="${SERVICE_URL}/execute-workflows" \
  --http-method=POST \
  --oidc-service-account-email=$SERVICE_ACCOUNT \
  --oidc-token-audience=$SERVICE_URL \
  --attempt-deadline=180s \
  --description="Execute workflows" \
  2>/dev/null && echo "✅ Created" || {
    echo "Job exists, updating..."
    gcloud scheduler jobs update http execute-workflows \
      --location=$REGION \
      --schedule="5 6-23 * * *" \
      --uri="${SERVICE_URL}/execute-workflows"
    echo "✅ Updated"
  }

# Job 4: Cleanup Processor (every 15 min)
echo ""
echo "4️⃣  Creating: cleanup-processor"
gcloud scheduler jobs create http cleanup-processor \
  --location=$REGION \
  --schedule="*/15 * * * *" \
  --time-zone="America/New_York" \
  --uri="${SERVICE_URL}/cleanup" \
  --http-method=POST \
  --oidc-service-account-email=$SERVICE_ACCOUNT \
  --oidc-token-audience=$SERVICE_URL \
  --attempt-deadline=180s \
  --description="Self-healing cleanup" \
  2>/dev/null && echo "✅ Created" || {
    echo "Job exists, updating..."
    gcloud scheduler jobs update http cleanup-processor \
      --location=$REGION \
      --schedule="*/15 * * * *" \
      --uri="${SERVICE_URL}/cleanup"
    echo "✅ Updated"
  }

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ All jobs created/updated!"
echo ""
echo "Verify with:"
echo "  gcloud scheduler jobs list --location=$REGION"
