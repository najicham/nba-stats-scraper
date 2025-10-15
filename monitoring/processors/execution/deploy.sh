#!/bin/bash
# File: monitoring/processor_execution_monitoring/deploy.sh
# Deploy Processor Execution Monitor to Cloud Run Jobs

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Load environment variables from .env file
if [ -f "${PROJECT_ROOT}/.env" ]; then
    echo "Loading environment variables from .env file..."
    export $(grep -v '^#' "${PROJECT_ROOT}/.env" | grep -v '^$' | xargs)
else
    echo "WARNING: No .env file found - notifications may not work"
fi

source "${SCRIPT_DIR}/job-config.env"

echo "========================================="
echo "Processor Execution Monitor Deployment"
echo "========================================="
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Job Name: ${JOB_NAME}"
echo ""

# Build environment variables string
ENV_VARS="GCP_PROJECT_ID=${PROJECT_ID}"
ENV_VARS="${ENV_VARS},EMAIL_ALERTS_ENABLED=${EMAIL_ALERTS_ENABLED:-true}"
ENV_VARS="${ENV_VARS},EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO}"
ENV_VARS="${ENV_VARS},EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO:-${EMAIL_ALERTS_TO}}"
ENV_VARS="${ENV_VARS},BREVO_SMTP_HOST=${BREVO_SMTP_HOST:-smtp-relay.brevo.com}"
ENV_VARS="${ENV_VARS},BREVO_SMTP_PORT=${BREVO_SMTP_PORT:-587}"
ENV_VARS="${ENV_VARS},BREVO_SMTP_USERNAME=${BREVO_SMTP_USERNAME}"
ENV_VARS="${ENV_VARS},BREVO_SMTP_PASSWORD=${BREVO_SMTP_PASSWORD}"
ENV_VARS="${ENV_VARS},BREVO_FROM_EMAIL=${BREVO_FROM_EMAIL}"
ENV_VARS="${ENV_VARS},BREVO_FROM_NAME=${BREVO_FROM_NAME:-Execution Monitor}"
ENV_VARS="${ENV_VARS},SLACK_ALERTS_ENABLED=${SLACK_ALERTS_ENABLED:-true}"
ENV_VARS="${ENV_VARS},SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL}"
ENV_VARS="${ENV_VARS},SLACK_WEBHOOK_URL_ERROR=${SLACK_WEBHOOK_EXECUTION_ERROR:-${SLACK_WEBHOOK_URL}}"
ENV_VARS="${ENV_VARS},SLACK_WEBHOOK_URL_WARNING=${SLACK_WEBHOOK_EXECUTION_WARNING:-${SLACK_WEBHOOK_URL}}"
ENV_VARS="${ENV_VARS},SLACK_WEBHOOK_URL_CRITICAL=${SLACK_WEBHOOK_EXECUTION_CRITICAL:-${SLACK_WEBHOOK_URL}}"

# Backup existing root Dockerfile if it exists
cd "${PROJECT_ROOT}"
if [ -f "Dockerfile" ]; then
    echo "Backing up existing root Dockerfile..."
    mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Copy monitoring Dockerfile to root for Cloud Build
echo "Copying docker/monitoring.Dockerfile to root..."
cp docker/monitoring.Dockerfile ./Dockerfile

# Deploy Cloud Run Job with Cloud Build
echo "Deploying Cloud Run Job with Cloud Build..."
gcloud run jobs deploy "${JOB_NAME}" \
  --source=. \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --service-account="${SERVICE_ACCOUNT}" \
  --cpu="${CPU}" \
  --memory="${MEMORY}" \
  --max-retries="${MAX_RETRIES}" \
  --task-timeout="${TIMEOUT}" \
  --args="${DEFAULT_ARGS}" \
  --set-env-vars="${ENV_VARS}"

DEPLOY_STATUS=$?

# Cleanup temporary Dockerfile
echo "Cleaning up temporary Dockerfile..."
rm ./Dockerfile

# Display results
if [ $DEPLOY_STATUS -eq 0 ]; then
    echo ""
    echo "========================================="
    echo "Deployment Complete!"
    echo "========================================="
    echo ""
    echo "Cloud Run Job: ${JOB_NAME}"
    echo "Region: ${REGION}"
    echo ""
    echo "Notification Status:"
    echo "  Email: ${EMAIL_ALERTS_TO}"
    echo "  Slack: $([ ! -z "${SLACK_WEBHOOK_EXECUTION_ERROR}" ] && echo "#processor-health" || echo "Using fallback")"
    echo ""
    echo "Manual execution:"
    echo "  gcloud run jobs execute ${JOB_NAME} --region=${REGION}"
    echo ""
    echo "Check last 14 days:"
    echo "  gcloud run jobs execute ${JOB_NAME} --region=${REGION} \\"
    echo "    --args=\"--lookback-days=14\""
    echo ""
    echo "Check latest execution:"
    echo "  gcloud run jobs executions list --job=${JOB_NAME} --region=${REGION} --limit=5"
    echo ""
    echo "NOTE: Cloud Scheduler not configured."
    echo "To add scheduling, run: ./setup-scheduler.sh"
    echo ""
else
    echo ""
    echo "Deployment failed!"
    echo "Check logs with: gcloud logging read \"resource.type=cloud_run_job\" --limit=50"
    exit 1
fi