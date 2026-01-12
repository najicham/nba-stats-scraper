#!/bin/bash
# Deploy Phase 4 Timeout Check to Google Cloud Functions
#
# This function runs every 30 minutes to check for stale Phase 4 states.
# If Phase 4 processors haven't completed after 4 hours, it forces Phase 5 trigger.
#
# This catches edge cases where ALL Phase 4 processors fail silently,
# causing no messages to arrive at the Phase 4→5 orchestrator.
#
# Usage:
#   ./bin/orchestrators/deploy_phase4_timeout_check.sh
#   ./bin/orchestrators/deploy_phase4_timeout_check.sh --skip-scheduler
#
# Environment Variables:
#   SLACK_WEBHOOK_URL - Required for timeout alerts

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
FUNCTION_NAME="phase4-timeout-check"
REGION="us-west2"
RUNTIME="python311"
ENTRY_POINT="check_phase4_timeouts"
MEMORY="256MB"
TIMEOUT="60s"
MAX_INSTANCES="1"
MIN_INSTANCES="0"

# Scheduler configuration
SCHEDULER_NAME="phase4-timeout-check-job"
SCHEDULER_SCHEDULE="*/30 * * * *"  # Every 30 minutes
SCHEDULER_TIMEZONE="America/New_York"

SOURCE_DIR="orchestration/cloud_functions/phase4_timeout_check"

# Prediction coordinator URL
PREDICTION_COORDINATOR_URL="https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app"

# Slack webhook URL for alerts
SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}"
if [ -z "$SLACK_WEBHOOK_URL" ]; then
    echo -e "${YELLOW}Warning: SLACK_WEBHOOK_URL not set. Staleness alerts will be disabled.${NC}"
    echo -e "${YELLOW}To enable alerts, run: export SLACK_WEBHOOK_URL=<your-webhook-url>${NC}"
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
echo -e "${BLUE}Phase 4 Timeout Check Deployment${NC}"
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
echo "  Coordinator URL:      $PREDICTION_COORDINATOR_URL"
echo "  Slack Alerts:         $([ -n "$SLACK_WEBHOOK_URL" ] && echo "Enabled" || echo "Disabled")"
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
ENV_VARS="GCP_PROJECT=$PROJECT_ID,PREDICTION_COORDINATOR_URL=$PREDICTION_COORDINATOR_URL"
if [ -n "$SLACK_WEBHOOK_URL" ]; then
    ENV_VARS="$ENV_VARS,SLACK_WEBHOOK_URL=$SLACK_WEBHOOK_URL"
    echo -e "${GREEN}✓ SLACK_WEBHOOK_URL configured for staleness alerts${NC}"
fi

gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime $RUNTIME \
    --region $REGION \
    --source $SOURCE_DIR \
    --entry-point $ENTRY_POINT \
    --trigger-http \
    --allow-unauthenticated \
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
echo -e "${YELLOW}Trigger Flow:${NC}"
echo "  Cloud Scheduler (every 30 minutes)"
echo "       ↓"
echo "  phase4-timeout-check (this function)"
echo "       ↓ (checks Firestore for stale states)"
echo "  If stale: trigger Phase 5 predictions + Slack alert"
echo ""

echo -e "${YELLOW}Next Steps:${NC}"
echo "1. View logs:"
echo "   ${BLUE}gcloud functions logs read $FUNCTION_NAME --region $REGION --limit 50${NC}"
echo ""
echo "2. Test by calling directly:"
echo "   ${BLUE}curl $FUNCTION_URL${NC}"
echo ""
echo "3. Run scheduler job immediately:"
echo "   ${BLUE}gcloud scheduler jobs run $SCHEDULER_NAME --location $REGION${NC}"
echo ""
echo "4. Check Firestore state:"
echo "   ${BLUE}https://console.firebase.google.com/project/$PROJECT_ID/firestore/data/phase4_completion${NC}"
echo ""
echo -e "${GREEN}✓ Phase 4 timeout check deployed successfully!${NC}"
