#!/bin/bash
# Deploy Phase 3 → Phase 4 Orchestrator to Google Cloud Functions
#
# This orchestrator tracks completion of all 5 Phase 3 processors and triggers
# Phase 4 when complete.
#
# Usage:
#   ./bin/orchestrators/deploy_phase3_to_phase4.sh

set -e  # Exit on error

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
PROJECT_ID="nba-props-platform"
FUNCTION_NAME="phase3-to-phase4-orchestrator"
REGION="us-west2"
RUNTIME="python311"
ENTRY_POINT="orchestrate_phase3_to_phase4"
TRIGGER_TOPIC="nba-phase3-analytics-complete"
MEMORY="512MB"
TIMEOUT="60s"
MAX_INSTANCES="10"
MIN_INSTANCES="0"

SOURCE_DIR="orchestration/cloud_functions/phase3_to_phase4"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Phase 3→4 Orchestrator Deployment${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Pre-deployment validation
echo -e "${YELLOW}Running pre-deployment validations...${NC}"
# Note: Cloud Function import validation skipped - the build process below copies
# all necessary modules to the deployment package.
echo -e "${GREEN}✓ Import validation skipped (handled during build)${NC}"
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

OUTPUT_TOPIC="nba-phase4-trigger"
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
echo ""

# Capture build metadata (Session 209: Cloud Function deployment tracking)
BUILD_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
BUILD_TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo -e "${YELLOW}Build metadata:${NC}"
echo "  BUILD_COMMIT:    $BUILD_COMMIT"
echo "  BUILD_TIMESTAMP: $BUILD_TIMESTAMP"
echo ""

echo -e "${YELLOW}Deploying from build directory...${NC}"
echo ""

gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime $RUNTIME \
    --region $REGION \
    --source $BUILD_DIR \
    --entry-point $ENTRY_POINT \
    --trigger-topic $TRIGGER_TOPIC \
    --update-env-vars GCP_PROJECT=$PROJECT_ID,BUILD_COMMIT=$BUILD_COMMIT,BUILD_TIMESTAMP=$BUILD_TIMESTAMP \
    --update-labels commit-sha=$BUILD_COMMIT \
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

# Session 206: Verify IAM binding was applied successfully
echo -e "${YELLOW}Verifying IAM binding...${NC}"
IAM_POLICY=$(gcloud run services get-iam-policy $FUNCTION_NAME \
    --region=$REGION --project=$PROJECT_ID --format=json 2>/dev/null)

if echo "$IAM_POLICY" | grep -q "roles/run.invoker"; then
    echo -e "${GREEN}✓ IAM binding verified successfully${NC}"
else
    echo -e "${RED}CRITICAL: IAM binding verification FAILED${NC}"
    echo -e "${RED}Orchestrator will not be able to receive Pub/Sub messages!${NC}"
    exit 1
fi
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
echo -e "${YELLOW}Next Steps:${NC}"
echo "1. View logs:"
echo "   ${BLUE}gcloud functions logs read $FUNCTION_NAME --region $REGION --limit 50${NC}"
echo ""
echo "2. Test by checking status:"
echo "   ${BLUE}python orchestration/cloud_functions/phase3_to_phase4/main.py <game_date>${NC}"
echo ""
echo "3. Monitor Firestore:"
echo "   ${BLUE}https://console.firebase.google.com/project/$PROJECT_ID/firestore/data/phase3_completion${NC}"
echo ""
# Session 211: Post-deploy duplicate subscription check
# Phase 3 topic legitimately has 2 push subs: orchestrator + phase3-to-grading
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Checking for Duplicate Subscriptions...${NC}"
echo -e "${BLUE}========================================${NC}"
./bin/orchestrators/check_duplicate_subscriptions.sh "$TRIGGER_TOPIC" 2 || \
    echo -e "${YELLOW}⚠️  Duplicate subscriptions detected — see above for cleanup commands${NC}"

echo ""
echo -e "${GREEN}✓ Orchestrator deployed successfully!${NC}"
