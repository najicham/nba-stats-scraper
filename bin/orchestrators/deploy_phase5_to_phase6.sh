#!/bin/bash
# Deploy Phase 5 → Phase 6 Orchestrator to Google Cloud Functions
#
# This orchestrator triggers Phase 6 publishing (export to GCS) when Phase 5
# predictions complete.
#
# Usage:
#   ./bin/orchestrators/deploy_phase5_to_phase6.sh

set -e  # Exit on error

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
PROJECT_ID="nba-props-platform"
FUNCTION_NAME="phase5-to-phase6-orchestrator"
REGION="us-west2"
RUNTIME="python311"
ENTRY_POINT="orchestrate_phase5_to_phase6"
TRIGGER_TOPIC="nba-phase5-predictions-complete"
MEMORY="256MB"
TIMEOUT="60s"
MAX_INSTANCES="10"
MIN_INSTANCES="0"

SOURCE_DIR="orchestration/cloud_functions/phase5_to_phase6"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Phase 5→6 Orchestrator Deployment${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check source directory
if [ ! -d "$SOURCE_DIR" ]; then
    echo -e "${RED}Error: Source directory not found: $SOURCE_DIR${NC}"
    exit 1
fi

if [ ! -f "$SOURCE_DIR/main.py" ]; then
    echo -e "${RED}Error: main.py not found in $SOURCE_DIR${NC}"
    exit 1
fi

echo -e "${YELLOW}Configuration:${NC}"
echo "  Project ID:      $PROJECT_ID"
echo "  Function Name:   $FUNCTION_NAME"
echo "  Region:          $REGION"
echo "  Trigger Topic:   $TRIGGER_TOPIC"
echo ""

# Check authentication
echo -e "${YELLOW}Checking authentication...${NC}"
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
    echo -e "${RED}Error: Not authenticated with gcloud${NC}"
    echo "Run: gcloud auth login"
    exit 1
fi
echo -e "${GREEN}✓ Authenticated${NC}"
echo ""

# Set project
CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null)
if [ "$CURRENT_PROJECT" != "$PROJECT_ID" ]; then
    echo -e "${YELLOW}Switching to project $PROJECT_ID${NC}"
    gcloud config set project $PROJECT_ID
fi
echo -e "${GREEN}✓ Project set to $PROJECT_ID${NC}"
echo ""

# Check Pub/Sub topics
echo -e "${YELLOW}Checking Pub/Sub topics...${NC}"

if gcloud pubsub topics describe $TRIGGER_TOPIC --project=$PROJECT_ID &>/dev/null; then
    echo -e "${GREEN}✓ Input topic exists: $TRIGGER_TOPIC${NC}"
else
    echo -e "${RED}✗ Input topic not found: $TRIGGER_TOPIC${NC}"
    echo -e "${YELLOW}Creating topic...${NC}"
    gcloud pubsub topics create $TRIGGER_TOPIC --project=$PROJECT_ID
    echo -e "${GREEN}✓ Created topic: $TRIGGER_TOPIC${NC}"
fi

OUTPUT_TOPIC="nba-phase6-export-trigger"
if gcloud pubsub topics describe $OUTPUT_TOPIC --project=$PROJECT_ID &>/dev/null; then
    echo -e "${GREEN}✓ Output topic exists: $OUTPUT_TOPIC${NC}"
else
    echo -e "${RED}✗ Output topic not found: $OUTPUT_TOPIC${NC}"
    echo -e "${YELLOW}Creating topic...${NC}"
    gcloud pubsub topics create $OUTPUT_TOPIC --project=$PROJECT_ID
    echo -e "${GREEN}✓ Created topic: $OUTPUT_TOPIC${NC}"
fi

# Also check for Phase 6 export complete topic (for monitoring)
COMPLETE_TOPIC="nba-phase6-export-complete"
if gcloud pubsub topics describe $COMPLETE_TOPIC --project=$PROJECT_ID &>/dev/null; then
    echo -e "${GREEN}✓ Complete topic exists: $COMPLETE_TOPIC${NC}"
else
    echo -e "${RED}✗ Complete topic not found: $COMPLETE_TOPIC${NC}"
    echo -e "${YELLOW}Creating topic...${NC}"
    gcloud pubsub topics create $COMPLETE_TOPIC --project=$PROJECT_ID
    echo -e "${GREEN}✓ Created topic: $COMPLETE_TOPIC${NC}"
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

# Get function details
echo -e "${YELLOW}Function Details:${NC}"
gcloud functions describe $FUNCTION_NAME \
    --region $REGION \
    --gen2 \
    --project $PROJECT_ID \
    --format="table(name,state,updateTime)"

echo ""
echo -e "${YELLOW}Trigger Flow:${NC}"
echo "  Phase 5 Predictions Complete"
echo "       ↓"
echo "  nba-phase5-predictions-complete (Pub/Sub)"
echo "       ↓"
echo "  phase5-to-phase6-orchestrator (this function)"
echo "       ↓"
echo "  nba-phase6-export-trigger (Pub/Sub)"
echo "       ↓"
echo "  Phase 6 Export Cloud Function"
echo ""

echo -e "${YELLOW}Next Steps:${NC}"
echo "1. View logs:"
echo "   ${BLUE}gcloud functions logs read $FUNCTION_NAME --region $REGION --limit 50${NC}"
echo ""
echo "2. Test by simulating Phase 5 completion:"
echo "   ${BLUE}gcloud pubsub topics publish nba-phase5-predictions-complete --message='{\"game_date\":\"2024-12-12\",\"status\":\"success\",\"metadata\":{\"completion_pct\":100}}'${NC}"
echo ""
echo "3. Check export status:"
echo "   ${BLUE}gsutil ls gs://nba-props-platform-api/v1/tonight/${NC}"
echo ""
echo -e "${GREEN}✓ Orchestrator deployed successfully!${NC}"
