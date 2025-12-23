#!/bin/bash
# Deploy Phase 2 → Phase 3 Orchestrator to Google Cloud Functions
#
# MONITORING MODE (v2.0): This orchestrator now only tracks processor completions
# for observability. Phase 3 is triggered directly via Pub/Sub subscription
# (nba-phase3-analytics-sub), NOT by this orchestrator.
#
# Usage:
#   ./bin/orchestrators/deploy_phase2_to_phase3.sh
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - Pub/Sub topic: nba-phase2-raw-complete (input for event trigger)
#   - Firestore database initialized

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ID="nba-props-platform"
FUNCTION_NAME="phase2-to-phase3-orchestrator"
REGION="us-west2"
RUNTIME="python311"
ENTRY_POINT="orchestrate_phase2_to_phase3"
TRIGGER_TOPIC="nba-phase2-raw-complete"
MEMORY="256MB"
TIMEOUT="60s"
MAX_INSTANCES="10"
MIN_INSTANCES="0"

# Source directory (relative to project root)
SOURCE_DIR="orchestration/cloud_functions/phase2_to_phase3"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Phase 2→3 Orchestrator Deployment${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if source directory exists
if [ ! -d "$SOURCE_DIR" ]; then
    echo -e "${RED}Error: Source directory not found: $SOURCE_DIR${NC}"
    echo "Run this script from the project root directory."
    exit 1
fi

# Check if main.py exists
if [ ! -f "$SOURCE_DIR/main.py" ]; then
    echo -e "${RED}Error: main.py not found in $SOURCE_DIR${NC}"
    exit 1
fi

echo -e "${YELLOW}Configuration:${NC}"
echo "  Project ID:      $PROJECT_ID"
echo "  Function Name:   $FUNCTION_NAME"
echo "  Region:          $REGION"
echo "  Runtime:         $RUNTIME"
echo "  Entry Point:     $ENTRY_POINT"
echo "  Trigger Topic:   $TRIGGER_TOPIC"
echo "  Memory:          $MEMORY"
echo "  Timeout:         $TIMEOUT"
echo "  Max Instances:   $MAX_INSTANCES"
echo ""

# Check if authenticated
echo -e "${YELLOW}Checking authentication...${NC}"
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
    echo -e "${RED}Error: Not authenticated with gcloud${NC}"
    echo "Run: gcloud auth login"
    exit 1
fi
echo -e "${GREEN}✓ Authenticated${NC}"
echo ""

# Verify project
echo -e "${YELLOW}Verifying project...${NC}"
CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null)
if [ "$CURRENT_PROJECT" != "$PROJECT_ID" ]; then
    echo -e "${YELLOW}Current project is $CURRENT_PROJECT, switching to $PROJECT_ID${NC}"
    gcloud config set project $PROJECT_ID
fi
echo -e "${GREEN}✓ Project set to $PROJECT_ID${NC}"
echo ""

# Check if Pub/Sub topics exist
echo -e "${YELLOW}Checking Pub/Sub topics...${NC}"

if gcloud pubsub topics describe $TRIGGER_TOPIC --project=$PROJECT_ID &>/dev/null; then
    echo -e "${GREEN}✓ Input topic exists: $TRIGGER_TOPIC${NC}"
else
    echo -e "${RED}✗ Input topic not found: $TRIGGER_TOPIC${NC}"
    echo -e "${YELLOW}Creating topic...${NC}"
    gcloud pubsub topics create $TRIGGER_TOPIC --project=$PROJECT_ID
    echo -e "${GREEN}✓ Created topic: $TRIGGER_TOPIC${NC}"
fi

OUTPUT_TOPIC="nba-phase3-trigger"
if gcloud pubsub topics describe $OUTPUT_TOPIC --project=$PROJECT_ID &>/dev/null; then
    echo -e "${GREEN}✓ Output topic exists: $OUTPUT_TOPIC${NC}"
else
    echo -e "${RED}✗ Output topic not found: $OUTPUT_TOPIC${NC}"
    echo -e "${YELLOW}Creating topic...${NC}"
    gcloud pubsub topics create $OUTPUT_TOPIC --project=$PROJECT_ID
    echo -e "${GREEN}✓ Created topic: $OUTPUT_TOPIC${NC}"
fi
echo ""

# Check if Firestore is initialized
echo -e "${YELLOW}Checking Firestore...${NC}"
# Note: This is a basic check - assumes if Firestore is accessible, it's initialized
if gcloud firestore databases list --project=$PROJECT_ID &>/dev/null; then
    echo -e "${GREEN}✓ Firestore initialized${NC}"
else
    echo -e "${YELLOW}⚠ Cannot verify Firestore - ensure it's initialized in GCP console${NC}"
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
    --format="table(
        name,
        state,
        updateTime
    )"

echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "1. Verify function is active:"
echo "   ${BLUE}gcloud functions describe $FUNCTION_NAME --region $REGION --gen2${NC}"
echo ""
echo "2. View logs:"
echo "   ${BLUE}gcloud functions logs read $FUNCTION_NAME --region $REGION --limit 50${NC}"
echo ""
echo "3. Test by triggering Phase 2 processors and checking Firestore:"
echo "   ${BLUE}python orchestration/cloud_functions/phase2_to_phase3/main.py <game_date>${NC}"
echo ""
echo "4. Monitor Firestore state:"
echo "   ${BLUE}https://console.firebase.google.com/project/$PROJECT_ID/firestore/data/phase2_completion${NC}"
echo ""
echo -e "${GREEN}✓ Orchestrator deployed successfully!${NC}"
