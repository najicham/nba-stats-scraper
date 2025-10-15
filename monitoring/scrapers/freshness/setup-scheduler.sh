#!/bin/bash
# File: monitoring/scrapers/freshness/setup-scheduler.sh
#
# Set up Cloud Scheduler to trigger freshness monitoring hourly

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Setting Up Cloud Scheduler${NC}"
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
    "SCHEDULER_NAME"
    "SCHEDULE"
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
echo "  Job Name: ${SERVICE_NAME}"
echo "  Scheduler Name: ${SCHEDULER_NAME}"
echo "  Schedule: ${SCHEDULE}"
echo "  Timezone: ${SCHEDULER_TIMEZONE}"
echo ""

# Check if scheduler job exists
SCHEDULER_EXISTS=$(gcloud scheduler jobs describe "${SCHEDULER_NAME}" \
    --location="${REGION}" \
    --project="${GCP_PROJECT_ID}" \
    2>/dev/null && echo "yes" || echo "no")

if [ "${SCHEDULER_EXISTS}" = "yes" ]; then
    echo -e "${YELLOW}Scheduler job already exists. Updating...${NC}"
    
    gcloud scheduler jobs update http "${SCHEDULER_NAME}" \
        --location="${REGION}" \
        --schedule="${SCHEDULE}" \
        --time-zone="${SCHEDULER_TIMEZONE}" \
        --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${GCP_PROJECT_ID}/jobs/${SERVICE_NAME}:run" \
        --http-method="POST" \
        --oauth-service-account-email="${GCP_PROJECT_ID}@appspot.gserviceaccount.com" \
        --project="${GCP_PROJECT_ID}"
else
    echo -e "${GREEN}Creating new scheduler job...${NC}"
    
    gcloud scheduler jobs create http "${SCHEDULER_NAME}" \
        --location="${REGION}" \
        --schedule="${SCHEDULE}" \
        --time-zone="${SCHEDULER_TIMEZONE}" \
        --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${GCP_PROJECT_ID}/jobs/${SERVICE_NAME}:run" \
        --http-method="POST" \
        --oauth-service-account-email="${GCP_PROJECT_ID}@appspot.gserviceaccount.com" \
        --project="${GCP_PROJECT_ID}"
fi

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}================================${NC}"
    echo -e "${GREEN}Scheduler Setup Complete!${NC}"
    echo -e "${GREEN}================================${NC}"
    echo ""
    echo "Scheduler Name: ${SCHEDULER_NAME}"
    echo "Schedule: ${SCHEDULE}"
    echo "Timezone: ${SCHEDULER_TIMEZONE}"
    echo ""
    echo "The freshness monitor will now run automatically according to the schedule."
    echo ""
    echo "To manually trigger the job:"
    echo "  gcloud scheduler jobs run ${SCHEDULER_NAME} --location=${REGION}"
    echo ""
    echo "To view scheduler logs:"
    echo "  gcloud logging read \"resource.type=cloud_scheduler_job AND resource.labels.job_name=${SCHEDULER_NAME}\" --limit=50"
    echo ""
    echo "To pause the scheduler:"
    echo "  gcloud scheduler jobs pause ${SCHEDULER_NAME} --location=${REGION}"
    echo ""
    echo "To resume the scheduler:"
    echo "  gcloud scheduler jobs resume ${SCHEDULER_NAME} --location=${REGION}"
    echo ""
else
    echo -e "${RED}Scheduler setup failed${NC}"
    exit 1
fi
