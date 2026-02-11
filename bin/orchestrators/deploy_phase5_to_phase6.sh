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
MEMORY="512MB"
TIMEOUT="60s"
MAX_INSTANCES="10"
MIN_INSTANCES="0"

SOURCE_DIR="orchestration/cloud_functions/phase5_to_phase6"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Phase 5→6 Orchestrator Deployment${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Pre-deployment validation
echo -e "${YELLOW}Running pre-deployment validations...${NC}"
if python bin/validation/validate_cloud_function_imports.py --function phase5_to_phase6 2>/dev/null; then
    echo -e "${GREEN}✓ Cloud Function import validation passed${NC}"
else
    echo -e "${RED}✗ Cloud Function import validation FAILED${NC}"
    exit 1
fi
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

# Create temporary build directory with dereferenced symlinks
echo -e "${YELLOW}Creating deployment package (dereferencing symlinks)...${NC}"
BUILD_DIR=$(mktemp -d)
trap "rm -rf $BUILD_DIR" EXIT

# Copy source with dereferenced symlinks using rsync
rsync -aL --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
    "$SOURCE_DIR/" "$BUILD_DIR/"

# Copy shared modules to support imports from shared.* (post-consolidation: Jan 30, 2026)
# orchestration/shared/ was deleted - all utilities now in shared/ only
echo -e "${YELLOW}Including shared modules (utils, clients, validation, config)...${NC}"
rsync -aL --exclude='__pycache__' --exclude='*.pyc' --exclude='tests/' \
    "shared/utils/" "$BUILD_DIR/shared/utils/"
rsync -aL --exclude='__pycache__' --exclude='*.pyc' --exclude='tests/' \
    "shared/clients/" "$BUILD_DIR/shared/clients/"
rsync -aL --exclude='__pycache__' --exclude='*.pyc' --exclude='tests/' \
    "shared/validation/" "$BUILD_DIR/shared/validation/"
rsync -aL --exclude='__pycache__' --exclude='*.pyc' --exclude='tests/' \
    "shared/config/" "$BUILD_DIR/shared/config/"

echo -e "${GREEN}✓ Build directory created: $BUILD_DIR${NC}"
echo -e "${GREEN}✓ Shared modules included (utils, clients, validation, config)${NC}"
echo -e "${YELLOW}Deploying from build directory...${NC}"
echo ""

gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime $RUNTIME \
    --region $REGION \
    --source $BUILD_DIR \
    --entry-point $ENTRY_POINT \
    --trigger-topic $TRIGGER_TOPIC \
    --set-env-vars GCP_PROJECT=$PROJECT_ID \
    --memory $MEMORY \
    --timeout $TIMEOUT \
    --max-instances $MAX_INSTANCES \
    --min-instances $MIN_INSTANCES \
    --project $PROJECT_ID

echo ""
echo -e "${YELLOW}Setting IAM permissions for Pub/Sub invocation...${NC}"
# Session 205: Ensure service account can invoke the Cloud Function
# Without this, Pub/Sub cannot deliver messages to the function
SERVICE_ACCOUNT="756957797294-compute@developer.gserviceaccount.com"
gcloud run services add-iam-policy-binding $FUNCTION_NAME \
    --region=$REGION \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/run.invoker" \
    --project=$PROJECT_ID

echo -e "${GREEN}✓ IAM permissions configured${NC}"
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
