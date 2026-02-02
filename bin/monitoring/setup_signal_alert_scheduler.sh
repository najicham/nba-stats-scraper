#!/bin/bash
# setup_signal_alert_scheduler.sh - Set up automated signal anomaly alerting
#
# Creates a Cloud Scheduler job that runs at 8 AM ET to check for
# extreme prediction signals and send alerts via Slack.
#
# Usage: ./bin/monitoring/setup_signal_alert_scheduler.sh [--dry-run]

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
JOB_NAME="nba-signal-anomaly-check"
SCHEDULE="0 13 * * *"  # 8 AM ET = 1 PM UTC

# Cloud Function that processes the signal check
# This should call check_prediction_signals.sh and send Slack alert if RED
SERVICE_URL="https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app"

DRY_RUN=false
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=true
    echo "DRY RUN MODE - No changes will be made"
fi

echo "========================================"
echo "Signal Alert Scheduler Setup"
echo "========================================"
echo "Job Name: $JOB_NAME"
echo "Schedule: $SCHEDULE (8 AM ET)"
echo "Region: $REGION"
echo ""

# Check if job exists
EXISTING=$(gcloud scheduler jobs describe "$JOB_NAME" --location="$REGION" --project="$PROJECT_ID" 2>/dev/null || echo "")

if [ -n "$EXISTING" ]; then
    echo "Job '$JOB_NAME' already exists."
    echo ""
    gcloud scheduler jobs describe "$JOB_NAME" --location="$REGION" --project="$PROJECT_ID" \
        --format="table(name, schedule, state, httpTarget.uri)"
    echo ""
    read -p "Update existing job? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
    ACTION="update"
else
    ACTION="create"
fi

if [ "$DRY_RUN" = true ]; then
    echo ""
    echo "Would $ACTION scheduler job:"
    echo "  gcloud scheduler jobs $ACTION $JOB_NAME \\"
    echo "    --location=$REGION \\"
    echo "    --schedule=\"$SCHEDULE\" \\"
    echo "    --uri=\"$SERVICE_URL/check-signal\" \\"
    echo "    --http-method=POST"
    exit 0
fi

echo ""
echo "${ACTION^}ing scheduler job..."

gcloud scheduler jobs $ACTION "$JOB_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --schedule="$SCHEDULE" \
    --time-zone="UTC" \
    --uri="$SERVICE_URL/check-signal" \
    --http-method=POST \
    --oidc-service-account-email="scheduler-invoker@$PROJECT_ID.iam.gserviceaccount.com" \
    --oidc-token-audience="$SERVICE_URL" \
    --description="Daily check for extreme prediction signal anomalies" \
    --attempt-deadline="120s"

echo ""
echo "========================================"
echo "Scheduler job ${ACTION}d successfully!"
echo "========================================"
echo ""
echo "To test manually:"
echo "  gcloud scheduler jobs run $JOB_NAME --location=$REGION"
echo ""
echo "NOTE: The prediction-coordinator needs a /check-signal endpoint."
echo "      See bin/monitoring/check_prediction_signals.sh for the logic."
