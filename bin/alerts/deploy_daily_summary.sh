#!/bin/bash

#####################################################################
# NBA Prediction Worker - Deploy Daily Summary Cloud Function
#
# Deploys a Cloud Function that sends daily Slack summaries with:
# - Yesterday's prediction stats
# - System health metrics
# - Top 5 high-confidence picks
# - Alert count
#
# Also creates Cloud Scheduler job to trigger daily at 9 AM ET.
#
# Usage:
#   ./bin/alerts/deploy_daily_summary.sh [PROJECT_ID] [REGION] [ENVIRONMENT]
#
# Arguments:
#   PROJECT_ID   - GCP project ID (default: nba-props-platform)
#   REGION       - GCP region (default: us-west2)
#   ENVIRONMENT  - Environment: prod, staging, dev (default: prod)
#
# Environment Variables (must be set):
#   SLACK_WEBHOOK_URL - Slack incoming webhook URL
#
# Example:
#   SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..." \
#     ./bin/alerts/deploy_daily_summary.sh nba-props-platform us-west2 prod
#
# Requirements:
#   - gcloud CLI installed and authenticated
#   - Secret Manager secret: nba-daily-summary-slack-webhook
#   - Permissions: cloudfunctions.functions.create, scheduler.jobs.create
#
# Created: 2026-01-17 (Week 3 - Option B Implementation)
#####################################################################

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
PROJECT_ID="${1:-nba-props-platform}"
REGION="${2:-us-west2}"
ENVIRONMENT="${3:-prod}"

# Cloud Function configuration
FUNCTION_NAME="nba-daily-summary-${ENVIRONMENT}"
RUNTIME="python311"
ENTRY_POINT="send_daily_summary"
MEMORY="512MB"
TIMEOUT="60s"

# Cloud Scheduler configuration
SCHEDULER_JOB_NAME="nba-daily-summary-${ENVIRONMENT}"
SCHEDULER_TIMEZONE="America/New_York"
SCHEDULER_SCHEDULE="0 9 * * *"  # 9 AM ET daily

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${SCRIPT_DIR}/daily_summary"

# Secret name
SECRET_NAME="nba-daily-summary-slack-webhook"

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  NBA Prediction Worker - Daily Summary Deployment${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "Project ID:       ${GREEN}${PROJECT_ID}${NC}"
echo -e "Region:           ${GREEN}${REGION}${NC}"
echo -e "Environment:      ${GREEN}${ENVIRONMENT}${NC}"
echo -e "Function Name:    ${GREEN}${FUNCTION_NAME}${NC}"
echo -e "Source Directory: ${GREEN}${SOURCE_DIR}${NC}"
echo ""

# Verify source directory exists
if [ ! -d "$SOURCE_DIR" ]; then
  echo -e "${RED}ERROR: Source directory not found: ${SOURCE_DIR}${NC}"
  exit 1
fi

# Verify required files exist
for file in main.py requirements.txt; do
  if [ ! -f "${SOURCE_DIR}/${file}" ]; then
    echo -e "${RED}ERROR: Required file not found: ${SOURCE_DIR}/${file}${NC}"
    exit 1
  fi
done

# Step 1: Create or update Secret Manager secret
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Step 1: Configure Secret Manager${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Check if SLACK_WEBHOOK_URL is provided
if [ -z "$SLACK_WEBHOOK_URL" ]; then
  echo -e "${YELLOW}⚠️  SLACK_WEBHOOK_URL environment variable not set${NC}"
  echo -e "${YELLOW}   Checking if secret already exists...${NC}"

  if gcloud secrets describe "$SECRET_NAME" --project="$PROJECT_ID" &>/dev/null; then
    echo -e "${GREEN}✓ Secret ${SECRET_NAME} already exists, skipping${NC}"
  else
    echo -e "${RED}ERROR: SLACK_WEBHOOK_URL must be set for initial deployment${NC}"
    echo ""
    echo "Set it like this:"
    echo "  export SLACK_WEBHOOK_URL='https://hooks.slack.com/services/YOUR/WEBHOOK/URL'"
    echo "  ./bin/alerts/deploy_daily_summary.sh"
    echo ""
    exit 1
  fi
else
  # Check if secret exists
  if gcloud secrets describe "$SECRET_NAME" --project="$PROJECT_ID" &>/dev/null; then
    echo -e "${YELLOW}➜${NC} Updating existing secret ${SECRET_NAME}..."

    # Add new version
    echo -n "$SLACK_WEBHOOK_URL" | gcloud secrets versions add "$SECRET_NAME" \
      --project="$PROJECT_ID" \
      --data-file=-

    echo -e "${GREEN}✓ Secret updated with new version${NC}"
  else
    echo -e "${YELLOW}➜${NC} Creating new secret ${SECRET_NAME}..."

    # Create secret
    gcloud secrets create "$SECRET_NAME" \
      --project="$PROJECT_ID" \
      --replication-policy="automatic" \
      --data-file=- <<< "$SLACK_WEBHOOK_URL"

    echo -e "${GREEN}✓ Secret created${NC}"
  fi
fi

echo ""

# Step 2: Deploy Cloud Function
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Step 2: Deploy Cloud Function${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo -e "${YELLOW}➜${NC} Deploying Cloud Function: ${FUNCTION_NAME}..."

gcloud functions deploy "$FUNCTION_NAME" \
  --gen2 \
  --runtime="$RUNTIME" \
  --region="$REGION" \
  --source="$SOURCE_DIR" \
  --entry-point="$ENTRY_POINT" \
  --trigger-http \
  --allow-unauthenticated \
  --memory="$MEMORY" \
  --timeout="$TIMEOUT" \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID}" \
  --set-secrets="SLACK_WEBHOOK_URL=${SECRET_NAME}:latest" \
  --project="$PROJECT_ID"

echo -e "${GREEN}✓ Cloud Function deployed${NC}"
echo ""

# Get Cloud Function URL
FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --gen2 \
  --format='value(serviceConfig.uri)')

echo -e "Function URL: ${BLUE}${FUNCTION_URL}${NC}"
echo ""

# Step 3: Create Cloud Scheduler Job
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Step 3: Create Cloud Scheduler Job${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Check if scheduler job already exists
if gcloud scheduler jobs describe "$SCHEDULER_JOB_NAME" \
  --location="$REGION" \
  --project="$PROJECT_ID" &>/dev/null; then

  echo -e "${YELLOW}➜${NC} Updating existing scheduler job: ${SCHEDULER_JOB_NAME}..."

  gcloud scheduler jobs update http "$SCHEDULER_JOB_NAME" \
    --location="$REGION" \
    --schedule="$SCHEDULER_SCHEDULE" \
    --uri="$FUNCTION_URL" \
    --http-method=POST \
    --time-zone="$SCHEDULER_TIMEZONE" \
    --project="$PROJECT_ID"

  echo -e "${GREEN}✓ Scheduler job updated${NC}"

else
  echo -e "${YELLOW}➜${NC} Creating scheduler job: ${SCHEDULER_JOB_NAME}..."

  gcloud scheduler jobs create http "$SCHEDULER_JOB_NAME" \
    --location="$REGION" \
    --schedule="$SCHEDULER_SCHEDULE" \
    --uri="$FUNCTION_URL" \
    --http-method=POST \
    --time-zone="$SCHEDULER_TIMEZONE" \
    --project="$PROJECT_ID"

  echo -e "${GREEN}✓ Scheduler job created${NC}"
fi

echo ""

# Step 4: Test the function (optional)
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Step 4: Test Function (Optional)${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo -e "${YELLOW}To test the function manually, run:${NC}"
echo ""
echo -e "  ${BLUE}curl -X POST ${FUNCTION_URL}${NC}"
echo ""
echo -e "${YELLOW}To trigger the scheduler job manually, run:${NC}"
echo ""
echo -e "  ${BLUE}gcloud scheduler jobs run ${SCHEDULER_JOB_NAME} --location=${REGION} --project=${PROJECT_ID}${NC}"
echo ""

# Summary
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Deployment Summary${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${GREEN}✓ Cloud Function deployed: ${FUNCTION_NAME}${NC}"
echo -e "${GREEN}✓ Cloud Scheduler configured: ${SCHEDULER_JOB_NAME}${NC}"
echo -e "${GREEN}✓ Schedule: ${SCHEDULER_SCHEDULE} (${SCHEDULER_TIMEZONE})${NC}"
echo -e "${GREEN}✓ Next run: Daily at 9:00 AM Eastern Time${NC}"
echo ""
echo -e "${GREEN}📨 Daily summaries will be sent to Slack automatically!${NC}"
echo ""
