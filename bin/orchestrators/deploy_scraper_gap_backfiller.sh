#!/bin/bash
# Deploy Scraper Gap Backfiller to Google Cloud Functions
#
# This function automatically detects and backfills gaps when scrapers
# recover from failures. Also alerts when gaps accumulate beyond threshold.
#
# Schedule: Every 4 hours via Cloud Scheduler
# Logic:
#   1. Check for accumulated gaps (>= threshold) and send alerts
#   2. For each scraper with unbackfilled failures (last 7 days):
#      - Test if scraper is healthy (try current date)
#      - If healthy, backfill oldest unbackfilled date
#      - Mark as backfilled on success
#
# Usage:
#   ./bin/orchestrators/deploy_scraper_gap_backfiller.sh
#
# Updated: 2026-01-24 (Jan 24 Session - added gap alerting)

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ID="nba-props-platform"
FUNCTION_NAME="scraper-gap-backfiller"
REGION="us-west2"
RUNTIME="python311"
ENTRY_POINT="backfill_gaps"
MEMORY="512MB"
TIMEOUT="540s"  # 9 minutes - backfills can take time
MAX_INSTANCES="1"  # Only one instance to prevent duplicate backfills
MIN_INSTANCES="0"

# Source directory (relative to project root)
SOURCE_DIR="orchestration/cloud_functions/scraper_gap_backfiller"

# Scheduler configuration
SCHEDULER_JOB_NAME="scraper-gap-backfiller-trigger"
SCHEDULER_SCHEDULE="0 */4 * * *"  # Every 4 hours
SCHEDULER_TIMEZONE="America/New_York"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Scraper Gap Backfiller Deployment${NC}"
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
echo "  Schedule:        $SCHEDULER_SCHEDULE ($SCHEDULER_TIMEZONE)"
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
google-cloud-secret-manager>=2.0.0
flask>=2.0.0
requests>=2.28.0
boto3>=1.26.0
EOF
    echo -e "${GREEN}OK Created requirements.txt${NC}"
fi

# Deploy function (HTTP trigger for scheduler)
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
    --no-allow-unauthenticated \
    --set-env-vars GCP_PROJECT=$PROJECT_ID \
    --memory $MEMORY \
    --timeout $TIMEOUT \
    --max-instances $MAX_INSTANCES \
    --min-instances $MIN_INSTANCES \
    --project $PROJECT_ID

echo ""
echo -e "${GREEN}OK Function deployed${NC}"
echo ""

# Get function URL for scheduler
FUNCTION_URL=$(gcloud functions describe $FUNCTION_NAME \
    --region $REGION \
    --gen2 \
    --project $PROJECT_ID \
    --format="value(serviceConfig.uri)")

echo -e "${YELLOW}Function URL: $FUNCTION_URL${NC}"
echo ""

# Create or update Cloud Scheduler job
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Configuring Cloud Scheduler...${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Delete existing scheduler job if it exists
if gcloud scheduler jobs describe $SCHEDULER_JOB_NAME --location=$REGION --project=$PROJECT_ID &>/dev/null; then
    echo -e "${YELLOW}Deleting existing scheduler job...${NC}"
    gcloud scheduler jobs delete $SCHEDULER_JOB_NAME \
        --location=$REGION \
        --project=$PROJECT_ID \
        --quiet
fi

# Create new scheduler job
echo -e "${YELLOW}Creating scheduler job...${NC}"
gcloud scheduler jobs create http $SCHEDULER_JOB_NAME \
    --location=$REGION \
    --schedule="$SCHEDULER_SCHEDULE" \
    --time-zone="$SCHEDULER_TIMEZONE" \
    --uri="$FUNCTION_URL" \
    --http-method=POST \
    --oidc-service-account-email="${PROJECT_ID}@appspot.gserviceaccount.com" \
    --project=$PROJECT_ID

echo -e "${GREEN}OK Scheduler job created${NC}"
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
echo -e "${YELLOW}Scheduler Details:${NC}"
gcloud scheduler jobs describe $SCHEDULER_JOB_NAME \
    --location=$REGION \
    --project=$PROJECT_ID \
    --format="table(name,schedule,timeZone,state)"

echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "1. Test manually:"
echo "   ${BLUE}gcloud scheduler jobs run $SCHEDULER_JOB_NAME --location=$REGION${NC}"
echo ""
echo "2. View logs:"
echo "   ${BLUE}gcloud functions logs read $FUNCTION_NAME --region $REGION --limit 50${NC}"
echo ""
echo "3. Check scraper_failures table:"
echo "   ${BLUE}SELECT * FROM nba_orchestration.scraper_failures WHERE backfilled = FALSE${NC}"
echo ""
echo -e "${GREEN}OK Scraper Gap Backfiller deployed successfully!${NC}"
