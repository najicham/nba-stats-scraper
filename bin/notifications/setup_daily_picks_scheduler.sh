#!/bin/bash
# Setup Cloud Scheduler for Daily Subset Picks Notifications
# Session 83 (2026-02-02)
#
# Creates a Cloud Scheduler job that sends daily subset picks
# via Slack and Email at 8:30 AM ET (after predictions run at 7 AM)

set -e

PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"
REGION="${GCP_REGION:-us-west2}"

echo "====================================="
echo "Daily Subset Picks Scheduler Setup"
echo "====================================="
echo ""

# Job configuration
JOB_NAME="daily-subset-picks-notification"
SCHEDULE="30 13 * * *"  # 8:30 AM ET = 1:30 PM UTC (winter) / 12:30 PM UTC (summer)
TIMEZONE="America/New_York"
DESCRIPTION="Send daily subset picks via Slack and Email"

# Cloud Run service URL (we'll use nba-scrapers as a host for now)
# TODO: Create dedicated notification service
SERVICE_URL="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/send-daily-picks"

echo "Configuration:"
echo "  Job Name: $JOB_NAME"
echo "  Schedule: $SCHEDULE ($TIMEZONE)"
echo "  Description: $DESCRIPTION"
echo ""

# Check if job exists
if gcloud scheduler jobs describe "$JOB_NAME" --location="$REGION" &>/dev/null; then
    echo "⚠️  Job $JOB_NAME already exists"
    read -p "Delete and recreate? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Deleting existing job..."
        gcloud scheduler jobs delete "$JOB_NAME" --location="$REGION" --quiet
    else
        echo "Exiting without changes"
        exit 0
    fi
fi

echo "Creating Cloud Scheduler job..."

# For now, we'll create a simple HTTP job
# In production, you'd want to:
# 1. Create a dedicated Cloud Function or Cloud Run service
# 2. Add authentication
# 3. Add retry logic

gcloud scheduler jobs create http "$JOB_NAME" \
    --location="$REGION" \
    --schedule="$SCHEDULE" \
    --time-zone="$TIMEZONE" \
    --uri="$SERVICE_URL" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body='{"subset_id": "v9_high_edge_top5"}' \
    --description="$DESCRIPTION" \
    --attempt-deadline=300s

echo ""
echo "✅ Cloud Scheduler job created: $JOB_NAME"
echo ""

echo "Job details:"
gcloud scheduler jobs describe "$JOB_NAME" --location="$REGION"

echo ""
echo "====================================="
echo "Next Steps:"
echo "====================================="
echo ""
echo "1. TEST manually first:"
echo "   PYTHONPATH=. python bin/notifications/send_daily_picks.py --test"
echo ""
echo "2. Send test notification:"
echo "   PYTHONPATH=. python bin/notifications/send_daily_picks.py"
echo ""
echo "3. Trigger scheduler manually:"
echo "   gcloud scheduler jobs run $JOB_NAME --location=$REGION"
echo ""
echo "4. View scheduler logs:"
echo "   gcloud logging read 'resource.type=\"cloud_scheduler_job\" resource.labels.job_id=\"$JOB_NAME\"' --limit=10"
echo ""
echo "5. Monitor for errors:"
echo "   gcloud logging read 'resource.type=\"cloud_scheduler_job\" resource.labels.job_id=\"$JOB_NAME\" severity>=ERROR' --limit=10"
echo ""
echo "====================================="
echo "Configuration Notes:"
echo "====================================="
echo ""
echo "Schedule: 8:30 AM ET daily"
echo "  - Predictions run at 7:00 AM ET"
echo "  - Gives 90 minutes for predictions to complete"
echo "  - Users receive picks before 9 AM"
echo ""
echo "To change subset:"
echo "  gcloud scheduler jobs update http $JOB_NAME --location=$REGION \\"
echo "    --message-body='{\"subset_id\": \"v9_high_edge_top1\"}'"
echo ""
