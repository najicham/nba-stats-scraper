#!/bin/bash
# Setup Cloud Scheduler for Processing Gap Monitor
# Run this when ready for automated monitoring

set -e
source "$(dirname "$0")/job-config.env"

# Hourly during business hours (10 AM - 6 PM PT)
# Runs year-round (adjust manually for off-season if needed)
SCHEDULE="0 10-18 * * *"
SCHEDULE_TIMEZONE="America/Los_Angeles"

echo "Setting up Cloud Scheduler for ${JOB_NAME}..."

# Check if already exists
if gcloud scheduler jobs describe "${JOB_NAME}-scheduler" \
    --location="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then
    echo "Scheduler already exists. Updating..."
    gcloud scheduler jobs update http "${JOB_NAME}-scheduler" \
        --location="${REGION}" \
        --project="${PROJECT_ID}" \
        --schedule="${SCHEDULE}" \
        --time-zone="${SCHEDULE_TIMEZONE}"
else
    echo "Creating new scheduler..."
    gcloud scheduler jobs create http "${JOB_NAME}-scheduler" \
        --location="${REGION}" \
        --project="${PROJECT_ID}" \
        --schedule="${SCHEDULE}" \
        --time-zone="${SCHEDULE_TIMEZONE}" \
        --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
        --http-method="POST" \
        --oauth-service-account-email="${SERVICE_ACCOUNT}"
fi

echo ""
echo "Scheduler configured: Hourly 10 AM - 6 PM PT"
echo "To pause:  gcloud scheduler jobs pause ${JOB_NAME}-scheduler --location=${REGION}"
echo "To resume: gcloud scheduler jobs resume ${JOB_NAME}-scheduler --location=${REGION}"
