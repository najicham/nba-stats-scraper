#!/bin/bash
# Deploy Validation Runner Cloud Function
#
# This function runs scheduled validation checks and posts digests to Slack:
# - 6 AM ET: Post-overnight validation
# - 8 AM ET: Pre-game preparation check
# - 6 PM ET: Pre-game final check
#
# Usage:
#   ./bin/deploy/deploy_validation_runner.sh
#   ./bin/deploy/deploy_validation_runner.sh --skip-scheduler
#
# Environment Variables:
#   SLACK_WEBHOOK_URL_ORCHESTRATION_HEALTH - For daily digest summaries
#   SLACK_WEBHOOK_URL_ERROR - For critical alerts

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
FUNCTION_NAME="validation-runner"
REGION="us-west2"
RUNTIME="python311"
ENTRY_POINT="run_validation"
SERVICE_ACCOUNT="nba-orchestration@nba-props-platform.iam.gserviceaccount.com"
MEMORY="1024MB"
TIMEOUT="300s"
MAX_INSTANCES="3"
MIN_INSTANCES="0"

SOURCE_DIR="orchestration/cloud_functions/validation_runner"

# Scheduler configurations (multiple jobs)
declare -A SCHEDULERS=(
    ["validation-post-overnight"]="0 6 * * *:post_overnight"
    ["validation-pre-game-prep"]="0 8 * * *:pre_game_prep"
    ["validation-pre-game-final"]="0 18 * * *:pre_game_final"
)
SCHEDULER_TIMEZONE="America/New_York"

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
echo -e "${BLUE}Validation Runner Deployment${NC}"
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
echo "  Scheduler Timezone:   $SCHEDULER_TIMEZONE"
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
ENV_VARS="GCP_PROJECT=$PROJECT_ID"

# Check for Slack webhooks
if [ -n "$SLACK_WEBHOOK_URL_ORCHESTRATION_HEALTH" ]; then
    ENV_VARS="$ENV_VARS,SLACK_WEBHOOK_URL_ORCHESTRATION_HEALTH=$SLACK_WEBHOOK_URL_ORCHESTRATION_HEALTH"
    echo -e "${GREEN}✓ SLACK_WEBHOOK_URL_ORCHESTRATION_HEALTH configured${NC}"
else
    echo -e "${YELLOW}Warning: SLACK_WEBHOOK_URL_ORCHESTRATION_HEALTH not set${NC}"
fi

if [ -n "$SLACK_WEBHOOK_URL_ERROR" ]; then
    ENV_VARS="$ENV_VARS,SLACK_WEBHOOK_URL_ERROR=$SLACK_WEBHOOK_URL_ERROR"
    echo -e "${GREEN}✓ SLACK_WEBHOOK_URL_ERROR configured${NC}"
fi

if [ -n "$SLACK_WEBHOOK_URL" ]; then
    ENV_VARS="$ENV_VARS,SLACK_WEBHOOK_URL=$SLACK_WEBHOOK_URL"
    echo -e "${GREEN}✓ SLACK_WEBHOOK_URL configured (fallback)${NC}"
fi

# Create temp directory for deployment (to resolve symlinks)
TEMP_DIR=$(mktemp -d)
trap "rm -rf ${TEMP_DIR}" EXIT

echo -e "${YELLOW}Preparing deployment package...${NC}"

# Copy main function files
cp "$SOURCE_DIR/main.py" "${TEMP_DIR}/"
cp "$SOURCE_DIR/requirements.txt" "${TEMP_DIR}/"

# Copy the ENTIRE shared module from project root
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cp -r "$REPO_ROOT/shared" "${TEMP_DIR}/"

# Remove pycache and other unnecessary files
find "${TEMP_DIR}/shared" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "${TEMP_DIR}/shared" -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
find "${TEMP_DIR}/shared" -type f -name "*.pyc" -delete 2>/dev/null || true

# Verify critical imports will work
if [ ! -f "${TEMP_DIR}/shared/validation/continuous_validator.py" ]; then
    echo -e "${RED}Error: continuous_validator.py not found in deployment package${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Deployment package prepared ($(find ${TEMP_DIR} -type f | wc -l) files)${NC}"

gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime $RUNTIME \
    --region $REGION \
    --source "${TEMP_DIR}" \
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

# Deploy Cloud Scheduler jobs
if [ "$SKIP_SCHEDULER" = false ]; then
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Deploying Cloud Scheduler Jobs...${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""

    for job_name in "${!SCHEDULERS[@]}"; do
        IFS=':' read -r schedule param <<< "${SCHEDULERS[$job_name]}"
        job_uri="${FUNCTION_URL}?schedule=${param}"

        echo -e "${YELLOW}Deploying scheduler: $job_name${NC}"
        echo "  Schedule: $schedule"
        echo "  Parameter: schedule=$param"

        # Check if scheduler job exists
        if gcloud scheduler jobs describe $job_name --location=$REGION --project=$PROJECT_ID &>/dev/null; then
            echo "  Updating existing job..."
            gcloud scheduler jobs update http $job_name \
                --location=$REGION \
                --schedule="$schedule" \
                --time-zone="$SCHEDULER_TIMEZONE" \
                --uri="$job_uri" \
                --http-method=GET \
                --project=$PROJECT_ID
        else
            echo "  Creating new job..."
            gcloud scheduler jobs create http $job_name \
                --location=$REGION \
                --schedule="$schedule" \
                --time-zone="$SCHEDULER_TIMEZONE" \
                --uri="$job_uri" \
                --http-method=GET \
                --project=$PROJECT_ID
        fi
        echo -e "${GREEN}  ✓ $job_name deployed${NC}"
        echo ""
    done
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
    echo -e "${YELLOW}Scheduler Jobs:${NC}"
    for job_name in "${!SCHEDULERS[@]}"; do
        gcloud scheduler jobs describe $job_name \
            --location=$REGION \
            --project=$PROJECT_ID \
            --format="table(name,schedule,state)" 2>/dev/null || true
    done
fi

echo ""
echo -e "${YELLOW}Validation Schedules:${NC}"
echo "  6 AM ET  - Post-overnight: Phase 3/4 completion, historical completeness"
echo "  8 AM ET  - Pre-game prep: Predictions ready, feature store quality"
echo "  6 PM ET  - Pre-game final: Final validation before games start"
echo ""

echo -e "${YELLOW}Next Steps:${NC}"
echo "1. View logs:"
echo "   ${BLUE}gcloud functions logs read $FUNCTION_NAME --region $REGION --limit 50${NC}"
echo ""
echo "2. Test by calling directly:"
echo "   ${BLUE}curl \"$FUNCTION_URL?schedule=post_overnight\"${NC}"
echo ""
echo "3. Run a scheduler job immediately:"
echo "   ${BLUE}gcloud scheduler jobs run validation-post-overnight --location $REGION${NC}"
echo ""
echo -e "${GREEN}✓ Validation runner deployed successfully!${NC}"
