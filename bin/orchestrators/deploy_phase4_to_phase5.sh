#!/bin/bash
# Deploy Phase 4 → Phase 5 Orchestrator to Google Cloud Functions
#
# This orchestrator tracks completion of all 5 Phase 4 processors and triggers
# Phase 5 (prediction coordinator) when complete.
#
# Phase 4 Processors tracked:
#   - team_defense_zone_analysis
#   - player_shot_zone_analysis
#   - player_composite_factors
#   - player_daily_cache
#   - ml_feature_store
#
# Usage:
#   ./bin/orchestrators/deploy_phase4_to_phase5.sh

set -e  # Exit on error

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
PROJECT_ID="nba-props-platform"
FUNCTION_NAME="phase4-to-phase5-orchestrator"
REGION="us-west2"
RUNTIME="python311"
ENTRY_POINT="orchestrate_phase4_to_phase5"
TRIGGER_TOPIC="nba-phase4-precompute-complete"
MEMORY="256MB"
TIMEOUT="60s"
MAX_INSTANCES="10"
MIN_INSTANCES="0"

SOURCE_DIR="orchestration/cloud_functions/phase4_to_phase5"

# Prediction coordinator URL (for direct HTTP trigger)
PREDICTION_COORDINATOR_URL="https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Phase 4→5 Orchestrator Deployment${NC}"
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
echo "  Project ID:           $PROJECT_ID"
echo "  Function Name:        $FUNCTION_NAME"
echo "  Region:               $REGION"
echo "  Trigger Topic:        $TRIGGER_TOPIC"
echo "  Coordinator URL:      $PREDICTION_COORDINATOR_URL"
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

OUTPUT_TOPIC="nba-predictions-trigger"
if gcloud pubsub topics describe $OUTPUT_TOPIC --project=$PROJECT_ID &>/dev/null; then
    echo -e "${GREEN}✓ Output topic exists: $OUTPUT_TOPIC${NC}"
else
    echo -e "${RED}✗ Output topic not found: $OUTPUT_TOPIC${NC}"
    echo -e "${YELLOW}Creating topic...${NC}"
    gcloud pubsub topics create $OUTPUT_TOPIC --project=$PROJECT_ID
    echo -e "${GREEN}✓ Created topic: $OUTPUT_TOPIC${NC}"
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
    --set-env-vars "GCP_PROJECT=$PROJECT_ID,PREDICTION_COORDINATOR_URL=$PREDICTION_COORDINATOR_URL" \
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
echo -e "${YELLOW}Next Steps:${NC}"
echo "1. View logs:"
echo "   ${BLUE}gcloud functions logs read $FUNCTION_NAME --region $REGION --limit 50${NC}"
echo ""
echo "2. Test by checking status:"
echo "   ${BLUE}python orchestration/cloud_functions/phase4_to_phase5/main.py <game_date>${NC}"
echo ""
echo "3. Monitor Firestore:"
echo "   ${BLUE}https://console.firebase.google.com/project/$PROJECT_ID/firestore/data/phase4_completion${NC}"
echo ""
echo "4. Ensure prediction-coordinator is deployed:"
echo "   ${BLUE}./bin/predictions/deploy/deploy_prediction_coordinator.sh prod${NC}"
echo ""
echo -e "${GREEN}✓ Orchestrator deployed successfully!${NC}"
