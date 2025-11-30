#!/bin/bash
# Deploy Pipeline Health Summary Cloud Function
#
# This function sends a daily email summarizing pipeline health.
# Triggered by Cloud Scheduler at 6 AM Pacific Time.
#
# Usage:
#   ./bin/monitoring/deploy/deploy_health_summary.sh
#
# Prerequisites:
#   - gcloud CLI authenticated
#   - AWS SES credentials set as secrets in Secret Manager
#   - Cloud Scheduler API enabled

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT:-nba-props-platform}"
REGION="${GCP_REGION:-us-west2}"
FUNCTION_NAME="pipeline-health-summary"
RUNTIME="python311"
MEMORY="256MB"
TIMEOUT="120s"
SERVICE_ACCOUNT="nba-cloud-functions@${PROJECT_ID}.iam.gserviceaccount.com"

# Scheduler configuration
SCHEDULER_NAME="daily-pipeline-health-summary"
SCHEDULER_SCHEDULE="0 6 * * *"  # 6 AM every day
SCHEDULER_TIMEZONE="America/Los_Angeles"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deploying Pipeline Health Summary Function${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Function: ${FUNCTION_NAME}"
echo ""

# Check if we're in the right directory
if [ ! -f "monitoring/health_summary/main.py" ]; then
    echo -e "${RED}Error: Run this script from the repository root${NC}"
    echo "Expected to find: monitoring/health_summary/main.py"
    exit 1
fi

# Check for required secrets (AWS SES credentials)
echo -e "${YELLOW}Checking for required secrets...${NC}"

check_secret() {
    local secret_name=$1
    if gcloud secrets describe "${secret_name}" --project="${PROJECT_ID}" &>/dev/null; then
        echo -e "  ${GREEN}✓${NC} ${secret_name}"
        return 0
    else
        echo -e "  ${RED}✗${NC} ${secret_name} - NOT FOUND"
        return 1
    fi
}

SECRETS_OK=true
check_secret "aws-ses-access-key-id" || SECRETS_OK=false
check_secret "aws-ses-secret-access-key" || SECRETS_OK=false

if [ "$SECRETS_OK" = false ]; then
    echo ""
    echo -e "${YELLOW}Creating missing secrets...${NC}"
    echo "You'll need to provide the AWS SES credentials."
    echo ""

    if ! gcloud secrets describe "aws-ses-access-key-id" --project="${PROJECT_ID}" &>/dev/null; then
        read -p "Enter AWS_SES_ACCESS_KEY_ID: " AWS_KEY_ID
        echo -n "${AWS_KEY_ID}" | gcloud secrets create "aws-ses-access-key-id" \
            --project="${PROJECT_ID}" \
            --data-file=- \
            --replication-policy="automatic"
    fi

    if ! gcloud secrets describe "aws-ses-secret-access-key" --project="${PROJECT_ID}" &>/dev/null; then
        read -sp "Enter AWS_SES_SECRET_ACCESS_KEY: " AWS_SECRET
        echo ""
        echo -n "${AWS_SECRET}" | gcloud secrets create "aws-ses-secret-access-key" \
            --project="${PROJECT_ID}" \
            --data-file=- \
            --replication-policy="automatic"
    fi
fi

# Deploy the Cloud Function
echo ""
echo -e "${YELLOW}Deploying Cloud Function...${NC}"

# Create a temporary directory with all required files
TEMP_DIR=$(mktemp -d)
trap "rm -rf ${TEMP_DIR}" EXIT

# Copy function code
cp monitoring/health_summary/main.py "${TEMP_DIR}/"
cp monitoring/health_summary/requirements.txt "${TEMP_DIR}/"

# Copy shared modules needed by the function
mkdir -p "${TEMP_DIR}/shared/utils"
cp shared/__init__.py "${TEMP_DIR}/shared/" 2>/dev/null || echo "" > "${TEMP_DIR}/shared/__init__.py"
cp shared/utils/__init__.py "${TEMP_DIR}/shared/utils/" 2>/dev/null || echo "" > "${TEMP_DIR}/shared/utils/__init__.py"
cp shared/utils/email_alerting_ses.py "${TEMP_DIR}/shared/utils/"

# Deploy from temp directory
gcloud functions deploy "${FUNCTION_NAME}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --runtime="${RUNTIME}" \
    --memory="${MEMORY}" \
    --timeout="${TIMEOUT}" \
    --entry-point="pipeline_health_summary" \
    --trigger-http \
    --allow-unauthenticated=false \
    --service-account="${SERVICE_ACCOUNT}" \
    --source="${TEMP_DIR}" \
    --set-env-vars="GCP_PROJECT=${PROJECT_ID}" \
    --set-secrets="AWS_SES_ACCESS_KEY_ID=aws-ses-access-key-id:latest,AWS_SES_SECRET_ACCESS_KEY=aws-ses-secret-access-key:latest" \
    --set-env-vars="AWS_SES_REGION=us-west-2,AWS_SES_FROM_EMAIL=alert@989.ninja,EMAIL_ALERTS_TO=nchammas@gmail.com"

echo ""
echo -e "${GREEN}✓ Cloud Function deployed successfully${NC}"

# Get the function URL
FUNCTION_URL=$(gcloud functions describe "${FUNCTION_NAME}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --format='value(httpsTrigger.url)')

echo "Function URL: ${FUNCTION_URL}"

# Create or update Cloud Scheduler job
echo ""
echo -e "${YELLOW}Setting up Cloud Scheduler...${NC}"

# Check if scheduler job exists
if gcloud scheduler jobs describe "${SCHEDULER_NAME}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" &>/dev/null; then
    echo "Updating existing scheduler job..."
    gcloud scheduler jobs update http "${SCHEDULER_NAME}" \
        --project="${PROJECT_ID}" \
        --location="${REGION}" \
        --schedule="${SCHEDULER_SCHEDULE}" \
        --time-zone="${SCHEDULER_TIMEZONE}" \
        --uri="${FUNCTION_URL}" \
        --http-method=POST \
        --oidc-service-account-email="${SERVICE_ACCOUNT}" \
        --oidc-token-audience="${FUNCTION_URL}"
else
    echo "Creating new scheduler job..."
    gcloud scheduler jobs create http "${SCHEDULER_NAME}" \
        --project="${PROJECT_ID}" \
        --location="${REGION}" \
        --schedule="${SCHEDULER_SCHEDULE}" \
        --time-zone="${SCHEDULER_TIMEZONE}" \
        --uri="${FUNCTION_URL}" \
        --http-method=POST \
        --oidc-service-account-email="${SERVICE_ACCOUNT}" \
        --oidc-token-audience="${FUNCTION_URL}"
fi

echo ""
echo -e "${GREEN}✓ Cloud Scheduler configured${NC}"
echo "Schedule: ${SCHEDULER_SCHEDULE} (${SCHEDULER_TIMEZONE})"

# Summary
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Function: ${FUNCTION_NAME}"
echo "URL: ${FUNCTION_URL}"
echo "Scheduler: ${SCHEDULER_NAME}"
echo "Schedule: Daily at 6:00 AM Pacific"
echo ""
echo "To test manually:"
echo "  gcloud scheduler jobs run ${SCHEDULER_NAME} --project=${PROJECT_ID} --location=${REGION}"
echo ""
echo "Or invoke directly:"
echo "  curl -X POST ${FUNCTION_URL} -H \"Authorization: bearer \$(gcloud auth print-identity-token)\""
