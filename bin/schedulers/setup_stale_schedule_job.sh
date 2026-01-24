#!/bin/bash
# ============================================================================
# setup_stale_schedule_job.sh
#
# Creates a Cloud Scheduler job to automatically fix stale schedule data.
# Runs every 4 hours to mark old in-progress games as Final.
#
# Usage:
#   ./bin/schedulers/setup_stale_schedule_job.sh
#   ./bin/schedulers/setup_stale_schedule_job.sh --delete  # Remove the job
#
# Created: Jan 23, 2026
# ============================================================================

set -e

# Configuration
PROJECT_ID="nba-props-platform"
REGION="us-west2"
SERVICE_NAME="nba-scrapers"
JOB_NAME="fix-stale-schedule"
SCHEDULE="0 */4 * * *"  # Every 4 hours (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 ET)
TIME_ZONE="America/New_York"
SERVICE_ACCOUNT="scheduler-orchestration@${PROJECT_ID}.iam.gserviceaccount.com"

echo "============================================"
echo "Stale Schedule Fix - Cloud Scheduler Setup"
echo "============================================"
echo ""
echo "Configuration:"
echo "  Project: ${PROJECT_ID}"
echo "  Region: ${REGION}"
echo "  Service: ${SERVICE_NAME}"
echo "  Job Name: ${JOB_NAME}"
echo "  Schedule: ${SCHEDULE} (${TIME_ZONE})"
echo ""

# Handle --delete flag
if [[ "$1" == "--delete" ]]; then
    echo "Deleting job ${JOB_NAME}..."
    gcloud scheduler jobs delete ${JOB_NAME} \
        --location=${REGION} \
        --project=${PROJECT_ID} \
        --quiet 2>/dev/null && echo "✅ Job deleted" || echo "⚠️ Job not found or already deleted"
    exit 0
fi

# Get Cloud Run service URL
echo "Getting Cloud Run service URL..."
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
    --region=${REGION} \
    --format="value(status.url)" \
    --project=${PROJECT_ID} 2>/dev/null)

if [[ -z "${SERVICE_URL}" ]]; then
    echo "❌ ERROR: Could not get service URL for ${SERVICE_NAME}"
    echo "   Make sure the Cloud Run service exists in ${REGION}"
    exit 1
fi

echo "  Service URL: ${SERVICE_URL}"

# Ensure service account exists
echo ""
echo "Checking service account..."
if ! gcloud iam service-accounts describe ${SERVICE_ACCOUNT} \
    --project=${PROJECT_ID} &>/dev/null; then
    echo "Creating service account..."
    gcloud iam service-accounts create scheduler-orchestration \
        --display-name="Cloud Scheduler - Orchestration Jobs" \
        --project=${PROJECT_ID}
fi
echo "  ✅ Service account exists"

# Ensure service account has Cloud Run invoker permission
echo ""
echo "Checking IAM permissions..."
gcloud run services add-iam-policy-binding ${SERVICE_NAME} \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/run.invoker" \
    --region=${REGION} \
    --project=${PROJECT_ID} \
    --quiet 2>/dev/null || true
echo "  ✅ IAM permissions configured"

# Create or update the scheduler job
echo ""
echo "Creating/updating scheduler job..."

ENDPOINT="${SERVICE_URL}/fix-stale-schedule"

if gcloud scheduler jobs describe ${JOB_NAME} \
    --location=${REGION} \
    --project=${PROJECT_ID} &>/dev/null; then

    # Update existing job
    echo "  Updating existing job..."
    gcloud scheduler jobs update http ${JOB_NAME} \
        --location=${REGION} \
        --schedule="${SCHEDULE}" \
        --time-zone="${TIME_ZONE}" \
        --uri="${ENDPOINT}" \
        --http-method=POST \
        --oidc-service-account-email="${SERVICE_ACCOUNT}" \
        --oidc-token-audience="${SERVICE_URL}" \
        --headers="Content-Type=application/json" \
        --message-body='{}' \
        --attempt-deadline=300s \
        --project=${PROJECT_ID} \
        --quiet
    echo "  ✅ Job updated"
else
    # Create new job
    echo "  Creating new job..."
    gcloud scheduler jobs create http ${JOB_NAME} \
        --location=${REGION} \
        --schedule="${SCHEDULE}" \
        --time-zone="${TIME_ZONE}" \
        --uri="${ENDPOINT}" \
        --http-method=POST \
        --oidc-service-account-email="${SERVICE_ACCOUNT}" \
        --oidc-token-audience="${SERVICE_URL}" \
        --headers="Content-Type=application/json" \
        --message-body='{}' \
        --attempt-deadline=300s \
        --description="Fix stale schedule data - marks old in-progress games as Final (every 4 hours)" \
        --project=${PROJECT_ID} \
        --quiet
    echo "  ✅ Job created"
fi

# Show job details
echo ""
echo "============================================"
echo "Job Details:"
echo "============================================"
gcloud scheduler jobs describe ${JOB_NAME} \
    --location=${REGION} \
    --project=${PROJECT_ID} \
    --format="table(name,schedule,timeZone,state,httpTarget.uri)"

echo ""
echo "============================================"
echo "Next Steps:"
echo "============================================"
echo "1. Deploy the updated main_scraper_service.py to Cloud Run:"
echo "   gcloud run deploy ${SERVICE_NAME} --source=. --region=${REGION}"
echo ""
echo "2. Test the endpoint manually:"
echo "   curl -X POST -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \\"
echo "     \"${ENDPOINT}\""
echo ""
echo "3. Trigger job manually (optional):"
echo "   gcloud scheduler jobs run ${JOB_NAME} --location=${REGION}"
echo ""
echo "4. View job logs:"
echo "   gcloud logging read 'resource.type=cloud_scheduler_job AND resource.labels.job_id=${JOB_NAME}' --limit=10"
echo ""
