#!/bin/bash
# Deploy Zero Workflow Monitor to Google Cloud Functions
#
# This function runs every hour and alerts if zero workflows have executed
# in the last 2 hours, catching orchestration system failures.
#
# Usage:
#   ./bin/deploy/deploy_zero_workflow_monitor.sh
#   ./bin/deploy/deploy_zero_workflow_monitor.sh --skip-scheduler
#
# Environment Variables:
#   SLACK_WEBHOOK_URL_ERROR - Required for critical alerts (to #app-error-alerts)
#   SLACK_WEBHOOK_URL - Fallback webhook (to #daily-orchestration)

set -e  # Exit on error

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configuration
PROJECT_ID="nba-props-platform"
FUNCTION_NAME="zero-workflow-monitor"
REGION="us-west2"
RUNTIME="python311"
ENTRY_POINT="zero_workflow_monitor"
SERVICE_ACCOUNT="756957797294-compute@developer.gserviceaccount.com"
MEMORY="256MB"
TIMEOUT="60s"
MAX_INSTANCES="1"
MIN_INSTANCES="0"

# Scheduler configuration
SCHEDULER_NAME="zero-workflow-monitor-hourly"
SCHEDULER_SCHEDULE="0 * * * *"  # Every hour on the hour
SCHEDULER_TIMEZONE="America/New_York"

SOURCE_DIR="orchestration/cloud_functions/zero_workflow_monitor"

# Slack webhook URLs
SLACK_WEBHOOK_URL_ERROR="${SLACK_WEBHOOK_URL_ERROR:-}"
SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}"

if [ -z "$SLACK_WEBHOOK_URL_ERROR" ] && [ -z "$SLACK_WEBHOOK_URL" ]; then
    echo -e "${YELLOW}Warning: No SLACK_WEBHOOK_URL configured. Alerts will not be sent.${NC}"
    echo -e "${YELLOW}Set SLACK_WEBHOOK_URL_ERROR or SLACK_WEBHOOK_URL to enable alerts.${NC}"
fi

# Parse arguments
SKIP_SCHEDULER=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-scheduler)
            SKIP_SCHEDULER=true
            shift
            ;;
        *)
            shift
            ;;
    esac
done

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Zero Workflow Monitor Deployment${NC}"
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
echo "  Scheduler:            $SCHEDULER_SCHEDULE ($SCHEDULER_TIMEZONE)"
echo "  Error Alerts:         $([ -n "$SLACK_WEBHOOK_URL_ERROR" ] && echo "Enabled" || echo "Disabled")"
echo "  Fallback Alerts:      $([ -n "$SLACK_WEBHOOK_URL" ] && echo "Enabled" || echo "Disabled")"
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

# Deploy function
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Deploying Cloud Function...${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Build env vars string
ENV_VARS="GCP_PROJECT_ID=$PROJECT_ID"
if [ -n "$SLACK_WEBHOOK_URL_ERROR" ]; then
    ENV_VARS="$ENV_VARS,SLACK_WEBHOOK_URL_ERROR=$SLACK_WEBHOOK_URL_ERROR"
    echo -e "${GREEN}✓ SLACK_WEBHOOK_URL_ERROR configured${NC}"
fi
if [ -n "$SLACK_WEBHOOK_URL" ]; then
    ENV_VARS="$ENV_VARS,SLACK_WEBHOOK_URL=$SLACK_WEBHOOK_URL"
    echo -e "${GREEN}✓ SLACK_WEBHOOK_URL configured (fallback)${NC}"
fi

# Create temp directory for deployment
TEMP_DIR=$(mktemp -d)
trap "rm -rf ${TEMP_DIR}" EXIT

echo -e "${YELLOW}Preparing deployment package...${NC}"

# Copy main function files
cp "$SOURCE_DIR/main.py" "${TEMP_DIR}/"
cp "$SOURCE_DIR/requirements.txt" "${TEMP_DIR}/"

# Copy shared module from project root
REPO_ROOT="$(cd "$(dirname "$SOURCE_DIR")/../.." && pwd)"

# Copy only what we need for this lightweight function
mkdir -p "${TEMP_DIR}/shared/utils"
mkdir -p "${TEMP_DIR}/shared/config"
mkdir -p "${TEMP_DIR}/shared/clients"

# Copy essential files
cp "$REPO_ROOT/shared/__init__.py" "${TEMP_DIR}/shared/" 2>/dev/null || echo "" > "${TEMP_DIR}/shared/__init__.py"
cp "$REPO_ROOT/shared/utils/__init__.py" "${TEMP_DIR}/shared/utils/" 2>/dev/null || echo "" > "${TEMP_DIR}/shared/utils/__init__.py"
cp "$REPO_ROOT/shared/config/__init__.py" "${TEMP_DIR}/shared/config/" 2>/dev/null || echo "" > "${TEMP_DIR}/shared/config/__init__.py"
cp "$REPO_ROOT/shared/clients/__init__.py" "${TEMP_DIR}/shared/clients/" 2>/dev/null || echo "" > "${TEMP_DIR}/shared/clients/__init__.py"

# Copy orchestration shared utils for slack retry
mkdir -p "${TEMP_DIR}/orchestration/shared/utils"
echo "" > "${TEMP_DIR}/orchestration/__init__.py"
echo "" > "${TEMP_DIR}/orchestration/shared/__init__.py"
echo "" > "${TEMP_DIR}/orchestration/shared/utils/__init__.py"
cp "$REPO_ROOT/orchestration/shared/utils/slack_retry.py" "${TEMP_DIR}/orchestration/shared/utils/" 2>/dev/null || true

# Remove pycache
find "${TEMP_DIR}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "${TEMP_DIR}" -type f -name "*.pyc" -delete 2>/dev/null || true

echo -e "${GREEN}✓ Deployment package prepared ($(find ${TEMP_DIR} -type f | wc -l) files)${NC}"

gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime $RUNTIME \
    --region $REGION \
    --source $TEMP_DIR \
    --entry-point $ENTRY_POINT \
    --trigger-http \
    --allow-unauthenticated \
    --service-account=$SERVICE_ACCOUNT \
    --set-env-vars "$ENV_VARS" \
    --memory $MEMORY \
    --timeout $TIMEOUT \
    --max-instances $MAX_INSTANCES \
    --min-instances $MIN_INSTANCES \
    --project $PROJECT_ID

echo ""
echo -e "${GREEN}✓ Cloud Function deployed${NC}"
echo ""

# Get function URL
FUNCTION_URL=$(gcloud functions describe $FUNCTION_NAME \
    --region $REGION \
    --gen2 \
    --project $PROJECT_ID \
    --format="value(serviceConfig.uri)")

echo -e "${CYAN}Function URL: $FUNCTION_URL${NC}"
echo ""

# Deploy Cloud Scheduler job
if [ "$SKIP_SCHEDULER" = false ]; then
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Deploying Cloud Scheduler Job...${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""

    # Check if scheduler job exists
    if gcloud scheduler jobs describe $SCHEDULER_NAME --location=$REGION --project=$PROJECT_ID &>/dev/null; then
        echo -e "${YELLOW}Scheduler job exists, updating...${NC}"
        gcloud scheduler jobs update http $SCHEDULER_NAME \
            --location=$REGION \
            --schedule="$SCHEDULER_SCHEDULE" \
            --time-zone="$SCHEDULER_TIMEZONE" \
            --uri="$FUNCTION_URL" \
            --http-method=GET \
            --project=$PROJECT_ID
    else
        echo -e "${YELLOW}Creating new scheduler job...${NC}"
        gcloud scheduler jobs create http $SCHEDULER_NAME \
            --location=$REGION \
            --schedule="$SCHEDULER_SCHEDULE" \
            --time-zone="$SCHEDULER_TIMEZONE" \
            --uri="$FUNCTION_URL" \
            --http-method=GET \
            --project=$PROJECT_ID
    fi
    echo ""
    echo -e "${GREEN}✓ Cloud Scheduler job deployed${NC}"
    echo ""
fi

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

if [ "$SKIP_SCHEDULER" = false ]; then
    echo ""
    echo -e "${YELLOW}Scheduler Job:${NC}"
    gcloud scheduler jobs describe $SCHEDULER_NAME \
        --location=$REGION \
        --project=$PROJECT_ID \
        --format="table(name,schedule,state,lastAttemptTime)"
fi

echo ""
echo -e "${YELLOW}What this monitor does:${NC}"
echo "  - Runs every hour"
echo "  - Checks nba_orchestration.workflow_executions for last 2 hours"
echo "  - Skips alerts during off-hours (2-6 AM ET)"
echo "  - Sends CRITICAL alert to Slack if zero workflows found"
echo "  - Includes investigation steps in alert"
echo ""

echo -e "${YELLOW}Next Steps:${NC}"
echo "1. View logs:"
echo "   ${BLUE}gcloud functions logs read $FUNCTION_NAME --region $REGION --limit 50${NC}"
echo ""
echo "2. Test by calling directly:"
echo "   ${BLUE}curl $FUNCTION_URL${NC}"
echo ""
echo "3. Force check during off-hours:"
echo "   ${BLUE}curl \"$FUNCTION_URL?force=true\"${NC}"
echo ""
echo "4. Run scheduler job immediately:"
echo "   ${BLUE}gcloud scheduler jobs run $SCHEDULER_NAME --location $REGION${NC}"
echo ""
echo -e "${GREEN}✓ Zero workflow monitor deployed successfully!${NC}"
