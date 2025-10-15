#!/bin/bash
# File: monitoring/scrapers/freshness/deploy.sh
#
# Deploy freshness monitoring to Cloud Run as a job

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Deploying Freshness Monitor${NC}"
echo -e "${GREEN}================================${NC}"

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../../" && pwd)"

# Load environment variables
if [ -f "${PROJECT_ROOT}/.env" ]; then
    echo -e "${GREEN}Loading environment from .env${NC}"
    set -a
    source "${PROJECT_ROOT}/.env"
    set +a
else
    echo -e "${YELLOW}Warning: .env file not found at ${PROJECT_ROOT}/.env${NC}"
fi

# Load job-specific config
if [ -f "${SCRIPT_DIR}/job-config.env" ]; then
    echo -e "${GREEN}Loading job config from job-config.env${NC}"
    set -a
    source "${SCRIPT_DIR}/job-config.env"
    set +a
fi

# Required variables
REQUIRED_VARS=(
    "GCP_PROJECT_ID"
    "REGION"
    "SERVICE_NAME"
)

# Check required variables
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        echo -e "${RED}Error: Required variable $var is not set${NC}"
        exit 1
    fi
done

echo ""
echo "Configuration:"
echo "  Project ID: ${GCP_PROJECT_ID}"
echo "  Region: ${REGION}"
echo "  Service Name: ${SERVICE_NAME}"
echo "  Image: ${IMAGE_NAME}"
echo ""

# Build environment variables array for Cloud Run
ENV_VARS=()

# Email alerting configuration
if [ -n "${BREVO_SMTP_HOST}" ]; then
    ENV_VARS+=("BREVO_SMTP_HOST=${BREVO_SMTP_HOST}")
    ENV_VARS+=("BREVO_SMTP_PORT=${BREVO_SMTP_PORT}")
    ENV_VARS+=("BREVO_SMTP_USERNAME=${BREVO_SMTP_USERNAME}")
    ENV_VARS+=("BREVO_SMTP_PASSWORD=${BREVO_SMTP_PASSWORD}")
    ENV_VARS+=("BREVO_FROM_EMAIL=${BREVO_FROM_EMAIL}")
    ENV_VARS+=("BREVO_FROM_NAME=${BREVO_FROM_NAME}")
    ENV_VARS+=("EMAIL_ALERTS_ENABLED=${EMAIL_ALERTS_ENABLED:-true}")
    ENV_VARS+=("EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO}")
    ENV_VARS+=("EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO}")
fi

# Slack alerting configuration (extensible multi-tier)
if [ -n "${SLACK_WEBHOOK_URL}" ]; then
    ENV_VARS+=("SLACK_ALERTS_ENABLED=${SLACK_ALERTS_ENABLED:-true}")
    ENV_VARS+=("SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL}")
    
    # Add level-specific webhooks if configured
    [ -n "${SLACK_WEBHOOK_URL_ERROR}" ] && ENV_VARS+=("SLACK_WEBHOOK_URL_ERROR=${SLACK_WEBHOOK_URL_ERROR}")
    [ -n "${SLACK_WEBHOOK_URL_CRITICAL}" ] && ENV_VARS+=("SLACK_WEBHOOK_URL_CRITICAL=${SLACK_WEBHOOK_URL_CRITICAL}")
    [ -n "${SLACK_WEBHOOK_URL_WARNING}" ] && ENV_VARS+=("SLACK_WEBHOOK_URL_WARNING=${SLACK_WEBHOOK_URL_WARNING}")
    [ -n "${SLACK_WEBHOOK_URL_INFO}" ] && ENV_VARS+=("SLACK_WEBHOOK_URL_INFO=${SLACK_WEBHOOK_URL_INFO}")
fi

# Ball Don't Lie API key (for schedule checking)
if [ -n "${BALL_DONT_LIE_API_KEY}" ]; then
    ENV_VARS+=("BALL_DONT_LIE_API_KEY=${BALL_DONT_LIE_API_KEY}")
fi

# GCS bucket configuration
if [ -n "${GCS_RAW_DATA_BUCKET}" ]; then
    ENV_VARS+=("GCS_RAW_DATA_BUCKET=${GCS_RAW_DATA_BUCKET}")
fi

# Convert array to comma-separated string
ENV_VARS_STRING=$(IFS=,; echo "${ENV_VARS[*]}")

echo -e "${GREEN}Building Docker image...${NC}"

# Build Docker image
gcloud builds submit "${PROJECT_ROOT}" \
    --config="${SCRIPT_DIR}/cloudbuild.yaml" \
    --substitutions="_IMAGE_NAME=${IMAGE_NAME},_PROJECT_ROOT=${PROJECT_ROOT}" \
    --project="${GCP_PROJECT_ID}"

if [ $? -ne 0 ]; then
    echo -e "${RED}Docker build failed${NC}"
    exit 1
fi

echo -e "${GREEN}Image built successfully${NC}"

# Check if job exists
JOB_EXISTS=$(gcloud run jobs describe "${SERVICE_NAME}" \
    --region="${REGION}" \
    --project="${GCP_PROJECT_ID}" \
    2>/dev/null && echo "yes" || echo "no")

if [ "${JOB_EXISTS}" = "yes" ]; then
    echo -e "${GREEN}Updating existing Cloud Run job...${NC}"
    
    gcloud run jobs update "${SERVICE_NAME}" \
        --image="${IMAGE_NAME}" \
        --region="${REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --max-retries="${MAX_RETRIES}" \
        --task-timeout="${TASK_TIMEOUT}" \
        --memory="${MEMORY}" \
        --cpu="${CPU}" \
        --set-env-vars="${ENV_VARS_STRING}" \
        --labels="component=monitoring,type=freshness-check"
else
    echo -e "${GREEN}Creating new Cloud Run job...${NC}"
    
    gcloud run jobs create "${SERVICE_NAME}" \
        --image="${IMAGE_NAME}" \
        --region="${REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --max-retries="${MAX_RETRIES}" \
        --task-timeout="${TASK_TIMEOUT}" \
        --memory="${MEMORY}" \
        --cpu="${CPU}" \
        --set-env-vars="${ENV_VARS_STRING}" \
        --labels="component=monitoring,type=freshness-check"
fi

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}================================${NC}"
    echo -e "${GREEN}Deployment Successful!${NC}"
    echo -e "${GREEN}================================${NC}"
    echo ""
    echo "Job Name: ${SERVICE_NAME}"
    echo "Region: ${REGION}"
    echo "Image: ${IMAGE_NAME}"
    echo ""
    echo "To run the job manually:"
    echo "  gcloud run jobs execute ${SERVICE_NAME} --region=${REGION}"
    echo ""
    echo "To view logs:"
    echo "  gcloud logging read \"resource.type=cloud_run_job AND resource.labels.job_name=${SERVICE_NAME}\" --limit=50 --format=json"
    echo ""
    echo "Next steps:"
    echo "  1. Test the job: ./test-job.sh"
    echo "  2. Set up scheduler: ./setup-scheduler.sh"
else
    echo -e "${RED}Deployment failed${NC}"
    exit 1
fi
