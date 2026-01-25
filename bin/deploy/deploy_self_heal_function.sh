#!/bin/bash
# Deploy Self-Heal Predictions Cloud Function
#
# This function runs daily to check for missing predictions and trigger
# healing pipelines if necessary. It checks BOTH today AND tomorrow.
#
# Schedule: 12:45 PM ET daily (45 12 * * * America/New_York)
# Note: Runs 15 minutes BEFORE Phase 6 tonight-picks (1 PM ET) to allow
#       time for self-healing before the export runs.
#
# Usage:
#   ./bin/deploy/deploy_self_heal_function.sh
#   ./bin/deploy/deploy_self_heal_function.sh --skip-scheduler  # Deploy function only
#   ./bin/deploy/deploy_self_heal_function.sh --dry-run         # Show what would be deployed

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
FUNCTION_NAME="self-heal-predictions"
REGION="us-west2"
RUNTIME="python311"
ENTRY_POINT="self_heal_check"
SERVICE_ACCOUNT="756957797294-compute@developer.gserviceaccount.com"
MEMORY="512MB"
TIMEOUT="540s"  # 9 minutes for self-healing pipeline

# Scheduler configuration
SCHEDULER_NAME="self-heal-predictions"
SCHEDULER_SCHEDULE="45 12 * * *"  # 12:45 PM ET (runs 15 min before Phase 6 export)
SCHEDULER_TIMEZONE="America/New_York"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SOURCE_DIR="orchestration/cloud_functions/self_heal"

# Parse arguments
SKIP_SCHEDULER=false
DRY_RUN=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-scheduler)
            SKIP_SCHEDULER=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            shift
            ;;
    esac
done

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Self-Heal Predictions Deployment${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check source directory
if [ ! -d "$PROJECT_ROOT/$SOURCE_DIR" ]; then
    echo -e "${RED}Error: Source directory not found: $SOURCE_DIR${NC}"
    exit 1
fi

if [ ! -f "$PROJECT_ROOT/$SOURCE_DIR/main.py" ]; then
    echo -e "${RED}Error: main.py not found in $SOURCE_DIR${NC}"
    exit 1
fi

echo -e "${YELLOW}Configuration:${NC}"
echo "  Project ID:      $PROJECT_ID"
echo "  Function Name:   $FUNCTION_NAME"
echo "  Region:          $REGION"
echo "  Entry Point:     $ENTRY_POINT"
echo "  Schedule:        $SCHEDULER_SCHEDULE ($SCHEDULER_TIMEZONE)"
echo "  Memory:          $MEMORY"
echo "  Timeout:         $TIMEOUT"
echo "  Dry Run:         $DRY_RUN"
echo ""

# Check authentication
echo -e "${YELLOW}Checking authentication...${NC}"
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
    echo -e "${RED}Error: Not authenticated with gcloud${NC}"
    echo "Run: gcloud auth login"
    exit 1
fi
echo -e "${GREEN}+ Authenticated${NC}"
echo ""

# Set project
CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null)
if [ "$CURRENT_PROJECT" != "$PROJECT_ID" ]; then
    echo -e "${YELLOW}Switching to project $PROJECT_ID${NC}"
    gcloud config set project $PROJECT_ID
fi
echo -e "${GREEN}+ Project set to $PROJECT_ID${NC}"
echo ""

if $DRY_RUN; then
    echo -e "${YELLOW}[DRY RUN] Would deploy function: $FUNCTION_NAME${NC}"
    echo ""
    echo -e "${YELLOW}Command that would be run:${NC}"
    echo "gcloud functions deploy $FUNCTION_NAME \\"
    echo "  --gen2 \\"
    echo "  --runtime $RUNTIME \\"
    echo "  --region $REGION \\"
    echo "  --source $SOURCE_DIR \\"
    echo "  --entry-point $ENTRY_POINT \\"
    echo "  --trigger-http \\"
    echo "  --no-allow-unauthenticated \\"
    echo "  --service-account=$SERVICE_ACCOUNT \\"
    echo "  --timeout $TIMEOUT \\"
    echo "  --memory $MEMORY"
    exit 0
fi

# Deploy function
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Phase 1: Deploying Cloud Function...${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

START_TIME=$(date +%s)

cd "$PROJECT_ROOT"

# Create temporary build directory with dereferenced symlinks
echo -e "${YELLOW}Creating deployment package (dereferencing symlinks)...${NC}"
BUILD_DIR=$(mktemp -d)
trap "rm -rf $BUILD_DIR" EXIT

# Copy source with dereferenced symlinks using rsync
rsync -aL --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
    "$SOURCE_DIR/" "$BUILD_DIR/"

echo -e "${GREEN}✓ Build directory created: $BUILD_DIR${NC}"
echo -e "${YELLOW}Deploying from build directory...${NC}"
echo ""

gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime $RUNTIME \
    --region $REGION \
    --source "$BUILD_DIR" \
    --entry-point $ENTRY_POINT \
    --trigger-http \
    --no-allow-unauthenticated \
    --service-account=$SERVICE_ACCOUNT \
    --timeout $TIMEOUT \
    --memory $MEMORY \
    --project $PROJECT_ID

DEPLOY_TIME=$(($(date +%s) - START_TIME))
echo ""
echo -e "${GREEN}+ Cloud Function deployed successfully (${DEPLOY_TIME}s)${NC}"
echo ""

# Deploy/Update Cloud Scheduler job
if [ "$SKIP_SCHEDULER" = false ]; then
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Phase 2: Configuring Cloud Scheduler...${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""

    # Get the function URL
    FUNCTION_URL=$(gcloud functions describe $FUNCTION_NAME --region $REGION --gen2 --format="value(serviceConfig.uri)")
    echo -e "${CYAN}Function URL: $FUNCTION_URL${NC}"

    # Check if scheduler job exists
    if gcloud scheduler jobs describe $SCHEDULER_NAME --location=$REGION --project=$PROJECT_ID &>/dev/null; then
        echo -e "${YELLOW}Scheduler job exists, updating...${NC}"
        gcloud scheduler jobs update http $SCHEDULER_NAME \
            --location=$REGION \
            --schedule="$SCHEDULER_SCHEDULE" \
            --time-zone="$SCHEDULER_TIMEZONE" \
            --uri="$FUNCTION_URL" \
            --http-method=POST \
            --oidc-service-account-email=$SERVICE_ACCOUNT \
            --project=$PROJECT_ID
    else
        echo -e "${YELLOW}Creating new scheduler job...${NC}"
        gcloud scheduler jobs create http $SCHEDULER_NAME \
            --location=$REGION \
            --schedule="$SCHEDULER_SCHEDULE" \
            --time-zone="$SCHEDULER_TIMEZONE" \
            --uri="$FUNCTION_URL" \
            --http-method=POST \
            --oidc-service-account-email=$SERVICE_ACCOUNT \
            --project=$PROJECT_ID
    fi
    echo ""
    echo -e "${GREEN}+ Cloud Scheduler job configured${NC}"
    echo ""
fi

# Phase 3: Verification
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Phase 3: Verification${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

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
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

echo -e "${YELLOW}What This Function Does:${NC}"
echo "  1. Checks if TODAY has games scheduled and predictions"
echo "  2. Checks if TOMORROW has games scheduled and predictions"
echo "  3. If either is missing predictions, triggers self-healing:"
echo "     - Clears stuck run_history entries"
echo "     - Triggers Phase 3 analytics"
echo "     - Triggers Phase 4 feature store"
echo "     - Triggers prediction coordinator"
echo ""

echo -e "${YELLOW}Self-Heal Flow:${NC}"
echo "  Cloud Scheduler (12:45 PM ET daily)"
echo "       |"
echo "       v"
echo "  self-heal-predictions (Cloud Function)"
echo "       |"
echo "       +---> Check TODAY's predictions"
echo "       |        |"
echo "       |        +---> If missing: Trigger healing pipeline"
echo "       |"
echo "       +---> Check TOMORROW's predictions"
echo "                |"
echo "                +---> If missing: Trigger healing pipeline"
echo ""
echo "  Note: Runs 15 min BEFORE Phase 6 tonight-picks export (1 PM ET)"
echo "        to allow time for self-healing before exports run."
echo ""

echo -e "${YELLOW}Quick Commands:${NC}"
echo ""
echo "1. View logs:"
echo "   ${BLUE}gcloud logging read 'resource.labels.service_name=\"self-heal-predictions\"' --limit 20 --freshness=1h${NC}"
echo ""
echo "2. Trigger manually:"
echo "   ${BLUE}gcloud scheduler jobs run $SCHEDULER_NAME --location $REGION${NC}"
echo ""
echo "3. Check current predictions:"
echo "   ${BLUE}bq query --use_legacy_sql=false \"SELECT game_date, COUNT(*) as predictions FROM nba_predictions.player_prop_predictions WHERE game_date >= CURRENT_DATE('America/New_York') AND is_active = TRUE GROUP BY 1\"${NC}"
echo ""
echo "4. Run daily health check:"
echo "   ${BLUE}./bin/monitoring/daily_health_check.sh${NC}"
echo ""

TOTAL_TIME=$(($(date +%s) - START_TIME))
echo -e "${GREEN}+ Total deployment time: ${TOTAL_TIME}s${NC}"
