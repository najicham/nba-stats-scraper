#!/bin/bash
# deploy_phase6_function.sh
#
# Deploy Phase 6 Export Cloud Function
# This function receives Pub/Sub messages and triggers exports to GCS.
#
# Usage:
#   ./bin/deploy/deploy_phase6_function.sh              # Deploy function
#   ./bin/deploy/deploy_phase6_function.sh --dry-run    # Show what would be deployed
#
# Prerequisites:
#   - gcloud CLI authenticated
#   - Pub/Sub topic nba-phase6-export-trigger exists

set -e

PROJECT_ID="nba-props-platform"
REGION="us-west2"
FUNCTION_NAME="phase6-export"
ENTRY_POINT="main"
RUNTIME="python311"
TOPIC="nba-phase6-export-trigger"
SERVICE_ACCOUNT="756957797294-compute@developer.gserviceaccount.com"
TIMEOUT="540s"
MEMORY="2Gi"
MAX_INSTANCES="5"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

DRY_RUN=false
if [[ "$1" == "--dry-run" ]]; then
    DRY_RUN=true
fi

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}Phase 6 Export Cloud Function Deployment${NC}"
echo -e "${CYAN}============================================${NC}"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Function: $FUNCTION_NAME"
echo "Trigger: Pub/Sub ($TOPIC)"
echo "Timeout: $TIMEOUT"
echo "Memory: $MEMORY"
echo "Dry Run: $DRY_RUN"
echo ""

# Check topic exists
echo -e "${YELLOW}Checking Pub/Sub topic...${NC}"
if ! gcloud pubsub topics describe $TOPIC --project=$PROJECT_ID >/dev/null 2>&1; then
    echo "Creating topic: $TOPIC"
    if ! $DRY_RUN; then
        gcloud pubsub topics create $TOPIC --project=$PROJECT_ID --labels="phase=6,type=export-trigger"
    fi
else
    echo "Topic exists: $TOPIC"
fi

# Navigate to project root
cd "$PROJECT_ROOT"

# Create a temporary directory with just the required files
DEPLOY_DIR=$(mktemp -d)
echo -e "${YELLOW}Preparing deployment package in $DEPLOY_DIR...${NC}"

# Copy cloud function entry point
cp orchestration/cloud_functions/phase6_export/main.py "$DEPLOY_DIR/"
cp orchestration/cloud_functions/phase6_export/requirements.txt "$DEPLOY_DIR/"

# Copy required source directories
cp -r data_processors "$DEPLOY_DIR/"
cp -r backfill_jobs "$DEPLOY_DIR/"
cp -r shared "$DEPLOY_DIR/"

# Create __init__.py files if missing
touch "$DEPLOY_DIR/data_processors/__init__.py"
touch "$DEPLOY_DIR/data_processors/publishing/__init__.py"
touch "$DEPLOY_DIR/backfill_jobs/__init__.py"
touch "$DEPLOY_DIR/backfill_jobs/publishing/__init__.py"
touch "$DEPLOY_DIR/shared/__init__.py"

# Add additional dependencies to requirements.txt
cat >> "$DEPLOY_DIR/requirements.txt" << 'EOF'
# Additional dependencies for exporters
pytz>=2023.0
pandas>=2.0.0
EOF

echo "Deployment package contents:"
ls -la "$DEPLOY_DIR/"

if $DRY_RUN; then
    echo -e "${YELLOW}[DRY RUN] Would deploy function: $FUNCTION_NAME${NC}"
    rm -rf "$DEPLOY_DIR"
    exit 0
fi

# Deploy function
echo ""
echo -e "${YELLOW}Deploying function...${NC}"

gcloud functions deploy $FUNCTION_NAME \
    --project=$PROJECT_ID \
    --region=$REGION \
    --gen2 \
    --runtime=$RUNTIME \
    --entry-point=$ENTRY_POINT \
    --trigger-topic=$TOPIC \
    --service-account=$SERVICE_ACCOUNT \
    --timeout=$TIMEOUT \
    --memory=$MEMORY \
    --max-instances=$MAX_INSTANCES \
    --set-env-vars="GCP_PROJECT=$PROJECT_ID,GCS_BUCKET=nba-props-platform-api" \
    --source="$DEPLOY_DIR"

# Cleanup
rm -rf "$DEPLOY_DIR"

echo ""
echo -e "${GREEN}✓ Deployment complete!${NC}"
echo ""
echo "To test manually:"
echo "  gcloud pubsub topics publish $TOPIC --message='{\"export_types\": [\"trends-hot-cold\"], \"target_date\": \"today\"}'"
echo ""
echo "To view logs:"
echo "  gcloud functions logs read $FUNCTION_NAME --region=$REGION --limit=20"
echo ""
