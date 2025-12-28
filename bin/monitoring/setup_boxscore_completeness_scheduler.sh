#!/bin/bash
# =============================================================================
# File: bin/monitoring/setup_boxscore_completeness_scheduler.sh
# Purpose: Set up daily scheduler for boxscore completeness monitoring
# Usage: ./bin/monitoring/setup_boxscore_completeness_scheduler.sh
# =============================================================================
#
# Creates a Cloud Scheduler job that:
# - Runs daily at 6:00 AM ET (after all games complete)
# - Calls the Phase 2 service with completeness check endpoint
# - Sends alerts if coverage is below threshold
#
# =============================================================================

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"
REGION="us-west2"
SERVICE_ACCOUNT="nba-cloud-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"

# Service URL (Phase 2 raw processors handle monitoring)
PHASE2_URL="https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app"

echo "========================================"
echo "Setting up Boxscore Completeness Monitor"
echo "========================================"
echo ""
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo ""

# Create or update the scheduler job
JOB_NAME="boxscore-completeness-daily"
SCHEDULE="0 6 * * *"  # 6:00 AM ET daily (games finish by ~1 AM ET)
TIMEZONE="America/New_York"

echo "Creating scheduler job: $JOB_NAME"
echo "  Schedule: $SCHEDULE ($TIMEZONE)"
echo ""

# Check if job exists
if gcloud scheduler jobs describe "$JOB_NAME" --location="$REGION" &>/dev/null; then
    echo "Job exists, updating..."
    ACTION="update"
else
    echo "Creating new job..."
    ACTION="create"
fi

# Create/update the job
gcloud scheduler jobs $ACTION http "$JOB_NAME" \
    --location="$REGION" \
    --schedule="$SCHEDULE" \
    --time-zone="$TIMEZONE" \
    --uri="${PHASE2_URL}/monitoring/boxscore-completeness" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body='{"check_days": 1, "alert_on_gaps": true}' \
    --oidc-service-account-email="$SERVICE_ACCOUNT" \
    --oidc-token-audience="${PHASE2_URL}" \
    --attempt-deadline="300s" \
    --description="Daily boxscore completeness check - alerts if coverage below 90%"

echo ""
echo "========================================"
echo "Scheduler Setup Complete"
echo "========================================"
echo ""
echo "Job Name: $JOB_NAME"
echo "Schedule: Daily at 6:00 AM ET"
echo "Endpoint: ${PHASE2_URL}/monitoring/boxscore-completeness"
echo ""
echo "To test manually:"
echo "  gcloud scheduler jobs run $JOB_NAME --location=$REGION"
echo ""
echo "To view logs:"
echo "  gcloud logging read 'resource.labels.service_name=\"nba-phase2-raw-processors\" AND \"completeness\"' --limit=10"
echo ""
