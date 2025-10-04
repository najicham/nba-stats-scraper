#!/bin/bash
# Setup Cloud Scheduler for Processing Gap Monitor
# Run this separately when ready for automated monitoring

set -e
source "$(dirname "$0")/job-config.env"

# Fixed cron schedule for season (hourly 10 AM - 6 PM PT)
SCHEDULE="0 10-18 * 10-6 *"
SCHEDULE_TIMEZONE="America/Los_Angeles"

echo "Setting up Cloud Scheduler for ${JOB_NAME}..."

gcloud scheduler jobs create http "${JOB_NAME}-scheduler" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --schedule="${SCHEDULE}" \
  --time-zone="${SCHEDULE_TIMEZONE}" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
  --http-method="POST" \
  --oauth-service-account-email="${SERVICE_ACCOUNT}"

echo "Scheduler created! Job will run hourly from 10 AM - 6 PM PT during season."
