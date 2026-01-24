#!/bin/bash
# Deploy Scraper Health Dashboard to Google Cloud Functions
#
# This function provides a visual HTML dashboard showing scraper health:
# - Gap counts per scraper with color-coded severity
# - Last successful run times
# - Recent errors
# - Proxy health metrics
#
# Access: https://us-west2-nba-props-platform.cloudfunctions.net/scraper-dashboard
#
# Usage:
#   ./bin/orchestrators/deploy_scraper_dashboard.sh
#
# Created: 2026-01-24 (Jan 24 Session improvements)

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ID="nba-props-platform"
FUNCTION_NAME="scraper-dashboard"
REGION="us-west2"
RUNTIME="python311"
ENTRY_POINT="scraper_dashboard"
MEMORY="256MB"
TIMEOUT="60s"
MAX_INSTANCES="5"
MIN_INSTANCES="0"

# Source directory (relative to project root)
SOURCE_DIR="orchestration/cloud_functions/scraper_dashboard"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Scraper Health Dashboard Deployment${NC}"
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
echo -e "${GREEN}OK Authenticated${NC}"
echo ""

# Verify project
echo -e "${YELLOW}Verifying project...${NC}"
CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null)
if [ "$CURRENT_PROJECT" != "$PROJECT_ID" ]; then
    echo -e "${YELLOW}Current project is $CURRENT_PROJECT, switching to $PROJECT_ID${NC}"
    gcloud config set project $PROJECT_ID
fi
echo -e "${GREEN}OK Project set to $PROJECT_ID${NC}"
echo ""

# Create requirements.txt if it doesn't exist
REQUIREMENTS_FILE="$SOURCE_DIR/requirements.txt"
if [ ! -f "$REQUIREMENTS_FILE" ]; then
    echo -e "${YELLOW}Creating requirements.txt...${NC}"
    cat > "$REQUIREMENTS_FILE" << 'EOF'
functions-framework>=3.0.0
google-cloud-bigquery>=3.0.0
flask>=2.0.0
EOF
    echo -e "${GREEN}OK Created requirements.txt${NC}"
fi

# Deploy function (HTTP trigger for dashboard access)
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
    --trigger-http \
    --allow-unauthenticated \
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
echo -e "${YELLOW}Dashboard URL:${NC}"
echo -e "${BLUE}https://${REGION}-${PROJECT_ID}.cloudfunctions.net/${FUNCTION_NAME}${NC}"
echo ""
echo -e "${YELLOW}View logs:${NC}"
echo -e "${BLUE}gcloud functions logs read $FUNCTION_NAME --region $REGION --limit 50${NC}"
echo ""
echo -e "${GREEN}OK Scraper Dashboard deployed successfully!${NC}"
