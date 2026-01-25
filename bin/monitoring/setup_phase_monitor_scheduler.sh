#!/bin/bash
# Setup Cloud Scheduler for Phase Transition Monitor
#
# This creates a Cloud Scheduler job that runs the phase transition monitor
# every 10 minutes, sending Slack alerts for critical issues.
#
# Usage:
#   ./bin/monitoring/setup_phase_monitor_scheduler.sh
#
# Prerequisites:
#   - gcloud CLI authenticated
#   - Cloud Scheduler API enabled
#   - SLACK_WEBHOOK_URL environment variable set
#
# Created: 2026-01-25

set -e

PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"
REGION="us-central1"
JOB_NAME="phase-transition-monitor"
SCHEDULE="*/10 * * * *"  # Every 10 minutes
TIMEZONE="America/New_York"

echo "Setting up Phase Transition Monitor Cloud Scheduler Job"
echo "======================================================="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Schedule: $SCHEDULE (every 10 minutes)"
echo ""

# Check if job exists
if gcloud scheduler jobs describe $JOB_NAME --project=$PROJECT_ID --location=$REGION &>/dev/null; then
    echo "Job '$JOB_NAME' already exists. Updating..."
    ACTION="update"
else
    echo "Creating new job '$JOB_NAME'..."
    ACTION="create"
fi

# Get the Cloud Run service URL for the validation runner
# If you have a Cloud Run service for validation, use it here
# Otherwise, we'll use Pub/Sub to trigger a Cloud Function

# Option 1: HTTP Target (if you have a Cloud Run service)
# gcloud scheduler jobs $ACTION http $JOB_NAME \
#     --project=$PROJECT_ID \
#     --location=$REGION \
#     --schedule="$SCHEDULE" \
#     --time-zone="$TIMEZONE" \
#     --uri="https://phase-monitor-xxxxx.run.app/run" \
#     --http-method=POST \
#     --oidc-service-account-email="${PROJECT_ID}@appspot.gserviceaccount.com"

# Option 2: Pub/Sub Target (trigger a Cloud Function)
TOPIC_NAME="phase-transition-monitor-trigger"

# Create topic if it doesn't exist
if ! gcloud pubsub topics describe $TOPIC_NAME --project=$PROJECT_ID &>/dev/null; then
    echo "Creating Pub/Sub topic: $TOPIC_NAME"
    gcloud pubsub topics create $TOPIC_NAME --project=$PROJECT_ID
fi

gcloud scheduler jobs $ACTION pubsub $JOB_NAME \
    --project=$PROJECT_ID \
    --location=$REGION \
    --schedule="$SCHEDULE" \
    --time-zone="$TIMEZONE" \
    --topic=$TOPIC_NAME \
    --message-body='{"action": "run_phase_monitor", "alert": true}'

echo ""
echo "Cloud Scheduler job configured!"
echo ""
echo "Next steps:"
echo "1. Create a Cloud Function that subscribes to '$TOPIC_NAME'"
echo "2. The function should run: python bin/monitoring/phase_transition_monitor.py --alert"
echo "3. Ensure SLACK_WEBHOOK_URL is set in the function's environment"
echo ""
echo "To manually trigger the job:"
echo "  gcloud scheduler jobs run $JOB_NAME --project=$PROJECT_ID --location=$REGION"
echo ""
echo "To view job status:"
echo "  gcloud scheduler jobs describe $JOB_NAME --project=$PROJECT_ID --location=$REGION"
