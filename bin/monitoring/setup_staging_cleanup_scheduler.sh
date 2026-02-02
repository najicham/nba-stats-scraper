#!/bin/bash
# setup_staging_cleanup_scheduler.sh - Set up automated staging table cleanup
#
# Creates a Cloud Scheduler job that runs daily at 3 AM ET to clean up
# orphaned staging tables from failed or incomplete prediction batches.
#
# Usage: ./bin/monitoring/setup_staging_cleanup_scheduler.sh [--dry-run]

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
JOB_NAME="nba-staging-table-cleanup"
SCHEDULE="0 8 * * *"  # 3 AM ET = 8 AM UTC

# The Cloud Run service that will handle the cleanup
# We'll use the prediction-coordinator since it has BigQuery access
SERVICE_URL="https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app"

DRY_RUN=false
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=true
    echo "DRY RUN MODE - No changes will be made"
fi

echo "========================================"
echo "Staging Table Cleanup Scheduler Setup"
echo "========================================"
echo "Job Name: $JOB_NAME"
echo "Schedule: $SCHEDULE (3 AM ET)"
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
    echo "    --uri=\"$SERVICE_URL/cleanup-staging\" \\"
    echo "    --http-method=POST \\"
    echo "    --oidc-service-account-email=scheduler-invoker@$PROJECT_ID.iam.gserviceaccount.com \\"
    echo "    --oidc-token-audience=\"$SERVICE_URL\""
    exit 0
fi

echo ""
echo "${ACTION^}ing scheduler job..."

gcloud scheduler jobs $ACTION "$JOB_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --schedule="$SCHEDULE" \
    --time-zone="UTC" \
    --uri="$SERVICE_URL/cleanup-staging" \
    --http-method=POST \
    --oidc-service-account-email="scheduler-invoker@$PROJECT_ID.iam.gserviceaccount.com" \
    --oidc-token-audience="$SERVICE_URL" \
    --description="Daily cleanup of orphaned staging tables from prediction batches" \
    --attempt-deadline="300s"

echo ""
echo "========================================"
echo "Scheduler job ${ACTION}d successfully!"
echo "========================================"
echo ""
echo "To test manually:"
echo "  gcloud scheduler jobs run $JOB_NAME --location=$REGION"
echo ""
echo "To check status:"
echo "  gcloud scheduler jobs describe $JOB_NAME --location=$REGION"
echo ""
echo "NOTE: The prediction-coordinator needs a /cleanup-staging endpoint."
echo "      If not implemented, add it or use a Cloud Run Job instead."
