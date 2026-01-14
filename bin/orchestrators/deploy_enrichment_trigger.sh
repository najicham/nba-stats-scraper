#!/bin/bash
# Deploy Enrichment Trigger Cloud Function
#
# This function runs the prediction line enrichment processor to backfill
# betting lines into predictions that were generated before props were scraped.
#
# Schedule: 18:40 UTC daily (after props scraped at 18:00 UTC)
#
# Usage:
#   ./bin/orchestrators/deploy_enrichment_trigger.sh
#
# Manual trigger:
#   curl "https://us-west2-nba-props-platform.cloudfunctions.net/enrichment-trigger?date=2026-01-14"

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
FUNCTION_NAME="enrichment-trigger"
REGION="us-west2"
PROJECT_ID="nba-props-platform"
RUNTIME="python311"
ENTRY_POINT="trigger_enrichment"
SOURCE_DIR="orchestration/cloud_functions/enrichment_trigger"
SCHEDULER_JOB_NAME="enrichment-daily"
SCHEDULE="40 18 * * *"  # 18:40 UTC daily

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deploying Enrichment Trigger${NC}"
echo -e "${GREEN}========================================${NC}"

# Check if we're in the right directory
if [ ! -d "$SOURCE_DIR" ]; then
    echo -e "${RED}Error: Source directory not found: $SOURCE_DIR${NC}"
    echo "Please run from the repository root directory"
    exit 1
fi

# Check gcloud auth
echo -e "\n${YELLOW}Checking authentication...${NC}"
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -1; then
    echo -e "${RED}Error: Not authenticated with gcloud${NC}"
    echo "Run: gcloud auth login"
    exit 1
fi

# Set project
echo -e "\n${YELLOW}Setting project to ${PROJECT_ID}...${NC}"
gcloud config set project $PROJECT_ID

# Deploy Cloud Function
echo -e "\n${YELLOW}Deploying Cloud Function: ${FUNCTION_NAME}...${NC}"
gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime $RUNTIME \
    --region $REGION \
    --source $SOURCE_DIR \
    --entry-point $ENTRY_POINT \
    --trigger-http \
    --allow-unauthenticated \
    --set-env-vars "GCP_PROJECT=$PROJECT_ID" \
    --memory 512MB \
    --timeout 300s \
    --max-instances 1

echo -e "${GREEN}Cloud Function deployed successfully!${NC}"

# Get the function URL
FUNCTION_URL=$(gcloud functions describe $FUNCTION_NAME --region=$REGION --gen2 --format="value(serviceConfig.uri)")
echo -e "\n${GREEN}Function URL: ${FUNCTION_URL}${NC}"

# Create or update Cloud Scheduler job
echo -e "\n${YELLOW}Creating/updating Cloud Scheduler job: ${SCHEDULER_JOB_NAME}...${NC}"

# Check if job exists
if gcloud scheduler jobs describe $SCHEDULER_JOB_NAME --location=$REGION >/dev/null 2>&1; then
    echo "Updating existing scheduler job..."
    gcloud scheduler jobs update http $SCHEDULER_JOB_NAME \
        --location=$REGION \
        --schedule="$SCHEDULE" \
        --time-zone="UTC" \
        --uri="${FUNCTION_URL}" \
        --http-method=GET \
        --attempt-deadline=300s
else
    echo "Creating new scheduler job..."
    gcloud scheduler jobs create http $SCHEDULER_JOB_NAME \
        --location=$REGION \
        --schedule="$SCHEDULE" \
        --time-zone="UTC" \
        --uri="${FUNCTION_URL}" \
        --http-method=GET \
        --attempt-deadline=300s
fi

echo -e "${GREEN}Cloud Scheduler job configured!${NC}"

# Summary
echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "\nFunction: ${FUNCTION_NAME}"
echo -e "URL: ${FUNCTION_URL}"
echo -e "Schedule: ${SCHEDULE} (UTC)"
echo -e "\nManual trigger:"
echo -e "  curl '${FUNCTION_URL}'"
echo -e "  curl '${FUNCTION_URL}?date=2026-01-14'"
echo -e "  curl '${FUNCTION_URL}?date=2026-01-14&dry_run=true'"
echo -e "\nHealth check:"
echo -e "  curl '${FUNCTION_URL/trigger_enrichment/health}'"
