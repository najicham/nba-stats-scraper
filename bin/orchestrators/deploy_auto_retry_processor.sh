#!/bin/bash
# Deploy Auto-Retry Processor Cloud Function
#
# This function is triggered by Cloud Scheduler every 15 minutes.
# It queries the failed_processor_queue and triggers retries for eligible processors.
#
# Usage:
#   ./bin/orchestrators/deploy_auto_retry_processor.sh
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - Cloud Scheduler job created (see below)
#
# After deploying, create the Cloud Scheduler job:
#   gcloud scheduler jobs create pubsub auto-retry-processor-trigger \
#     --schedule="*/15 * * * *" \
#     --topic=auto-retry-trigger \
#     --message-body='{"action":"retry"}' \
#     --location=us-west2 \
#     --time-zone="America/New_York"

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
PROJECT_ID="nba-props-platform"
FUNCTION_NAME="auto-retry-processor"
REGION="us-west2"
RUNTIME="python311"
ENTRY_POINT="auto_retry_processors"
TRIGGER_TOPIC="auto-retry-trigger"
MEMORY="256MB"
TIMEOUT="120s"
MAX_INSTANCES="1"
MIN_INSTANCES="0"

# Source directory
SOURCE_DIR="orchestration/cloud_functions/auto_retry_processor"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Auto-Retry Processor Deployment${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if source directory exists
if [ ! -d "$SOURCE_DIR" ]; then
    echo -e "${RED}Error: Source directory not found: $SOURCE_DIR${NC}"
    exit 1
fi

echo -e "${YELLOW}Configuration:${NC}"
echo "  Project ID:      $PROJECT_ID"
echo "  Function Name:   $FUNCTION_NAME"
echo "  Region:          $REGION"
echo "  Trigger Topic:   $TRIGGER_TOPIC"
echo "  Memory:          $MEMORY"
echo "  Timeout:         $TIMEOUT"
echo ""

# Check authentication
echo -e "${YELLOW}Checking authentication...${NC}"
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
    echo -e "${RED}Error: Not authenticated with gcloud${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Authenticated${NC}"
echo ""

# Verify project
gcloud config set project $PROJECT_ID 2>/dev/null
echo -e "${GREEN}✓ Project set to $PROJECT_ID${NC}"
echo ""

# Create Pub/Sub topic if needed
echo -e "${YELLOW}Checking Pub/Sub topic...${NC}"
if gcloud pubsub topics describe $TRIGGER_TOPIC --project=$PROJECT_ID &>/dev/null; then
    echo -e "${GREEN}✓ Topic exists: $TRIGGER_TOPIC${NC}"
else
    echo -e "${YELLOW}Creating topic: $TRIGGER_TOPIC${NC}"
    gcloud pubsub topics create $TRIGGER_TOPIC --project=$PROJECT_ID
    echo -e "${GREEN}✓ Created topic: $TRIGGER_TOPIC${NC}"
fi
echo ""

# Deploy function
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Deploying Cloud Function...${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime $RUNTIME \
    --region $REGION \
    --source $SOURCE_DIR \
    --entry-point $ENTRY_POINT \
    --trigger-topic $TRIGGER_TOPIC \
    --set-env-vars GCP_PROJECT=$PROJECT_ID \
    --memory $MEMORY \
    --timeout $TIMEOUT \
    --max-instances $MAX_INSTANCES \
    --min-instances $MIN_INSTANCES \
    --project $PROJECT_ID

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if scheduler job exists
echo -e "${YELLOW}Checking Cloud Scheduler job...${NC}"
if gcloud scheduler jobs describe auto-retry-processor-trigger --location=$REGION --project=$PROJECT_ID &>/dev/null; then
    echo -e "${GREEN}✓ Scheduler job exists${NC}"
else
    echo -e "${YELLOW}Creating Cloud Scheduler job...${NC}"
    gcloud scheduler jobs create pubsub auto-retry-processor-trigger \
        --schedule="*/15 * * * *" \
        --topic=$TRIGGER_TOPIC \
        --message-body='{"action":"retry"}' \
        --location=$REGION \
        --time-zone="America/New_York" \
        --project=$PROJECT_ID
    echo -e "${GREEN}✓ Created scheduler job${NC}"
fi
echo ""

echo -e "${YELLOW}Function Details:${NC}"
gcloud functions describe $FUNCTION_NAME \
    --region $REGION \
    --gen2 \
    --project $PROJECT_ID \
    --format="table(name,state,updateTime)"

echo ""

# Post-deployment health check
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Running Post-Deployment Health Check...${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

if python bin/validation/post_deployment_health_check.py "$FUNCTION_NAME" --region "$REGION" --project "$PROJECT_ID" --timeout 60; then
    echo ""
    echo -e "${GREEN}✓ Post-deployment health check PASSED${NC}"
else
    HEALTH_EXIT_CODE=$?
    echo ""
    if [ $HEALTH_EXIT_CODE -eq 1 ]; then
        echo -e "${RED}✗ Post-deployment health check FAILED - Function may not have started correctly${NC}"
        echo -e "${YELLOW}Check logs: gcloud functions logs read $FUNCTION_NAME --region $REGION --limit 50${NC}"
        exit 1
    else
        echo -e "${YELLOW}⚠ Post-deployment health check returned unknown status${NC}"
        echo -e "${YELLOW}Manually verify: gcloud functions describe $FUNCTION_NAME --region $REGION --gen2${NC}"
    fi
fi

echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "1. View logs:"
echo "   ${BLUE}gcloud functions logs read $FUNCTION_NAME --region $REGION --limit 50${NC}"
echo ""
echo "2. Test manually:"
echo "   ${BLUE}gcloud scheduler jobs run auto-retry-processor-trigger --location=$REGION${NC}"
echo ""
echo "3. Check BigQuery queue:"
echo "   ${BLUE}bq query 'SELECT * FROM nba_orchestration.failed_processor_queue LIMIT 10'${NC}"
echo ""
echo -e "${GREEN}✓ Auto-Retry Processor deployed successfully!${NC}"
