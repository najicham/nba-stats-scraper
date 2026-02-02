#!/bin/bash
# =============================================================================
# File: bin/monitoring/setup_weekly_drift_check_scheduler.sh
# Purpose: Set up weekly scheduler for model drift detection
# Usage: ./bin/monitoring/setup_weekly_drift_check_scheduler.sh
# =============================================================================
#
# Creates a Cloud Scheduler job that:
# - Runs weekly on Mondays at 9:00 AM ET
# - Executes Cloud Run Job to check model performance over 4 weeks
# - Sends Slack alerts if drift detected (hit rate < 60% or < 55%)
#
# Prerequisites:
# 1. Deploy Cloud Run Job: ./bin/deploy-monitoring-job.sh weekly-model-drift-check
# 2. Set environment variables in Cloud Run Job:
#    - SLACK_WEBHOOK_URL_WARNING (for warnings)
#    - SLACK_WEBHOOK_URL_ERROR (for critical alerts)
#
# =============================================================================

set -euo pipefail

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"
REGION="us-west2"
SERVICE_ACCOUNT="756957797294-compute@developer.gserviceaccount.com"

# Cloud Run Job name
JOB_NAME="nba-weekly-model-drift-check"

echo "========================================"
echo "Setting up Weekly Model Drift Check"
echo "========================================"
echo ""
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo ""

# Create or update the scheduler job
SCHEDULER_NAME="weekly-model-drift-check"
SCHEDULE="0 14 * * 1"  # 9:00 AM ET on Mondays (14:00 UTC)
TIMEZONE="America/New_York"

echo "Creating scheduler job: $SCHEDULER_NAME"
echo "  Schedule: Mondays 9:00 AM ET"
echo "  Target: Cloud Run Job $JOB_NAME"
echo ""

# Check if scheduler job exists
if gcloud scheduler jobs describe "$SCHEDULER_NAME" --location="$REGION" &>/dev/null; then
    echo "Scheduler job exists, deleting to recreate..."
    gcloud scheduler jobs delete "$SCHEDULER_NAME" --location="$REGION" --quiet
fi

# Create the scheduler job that executes the Cloud Run Job
gcloud scheduler jobs create http "$SCHEDULER_NAME" \
    --location="$REGION" \
    --schedule="$SCHEDULE" \
    --time-zone="$TIMEZONE" \
    --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
    --http-method=POST \
    --oauth-service-account-email="$SERVICE_ACCOUNT" \
    --attempt-deadline="600s" \
    --description="Weekly model drift check - monitors performance degradation (Mondays 9 AM ET)"

echo ""
echo "========================================"
echo "Scheduler Setup Complete"
echo "========================================"
echo ""
echo "Scheduler Job: $SCHEDULER_NAME"
echo "Schedule: Mondays at 9:00 AM ET"
echo "Cloud Run Job: $JOB_NAME"
echo ""
echo "To test manually:"
echo "  gcloud scheduler jobs run $SCHEDULER_NAME --location=$REGION"
echo ""
echo "To view job executions:"
echo "  gcloud run jobs executions list --job=$JOB_NAME --region=$REGION --limit=5"
echo ""
echo "To view logs:"
echo "  gcloud logging read 'resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$JOB_NAME\"' --limit=50"
echo ""
echo "NOTE: Make sure to set Slack webhook environment variables in the Cloud Run Job:"
echo "  SLACK_WEBHOOK_URL_WARNING"
echo "  SLACK_WEBHOOK_URL_ERROR"
echo ""
