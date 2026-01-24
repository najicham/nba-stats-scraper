#!/bin/bash
# Deploy Phase 5B Grading Cloud Function and Scheduler Job
#
# This function grades predictions against actual game results.
# Runs daily at 7:30 AM ET (after Phase 3 analytics complete - Phase 3 starts at 6:30 AM and takes 45+ min).
#
# Usage:
#   ./bin/deploy/deploy_grading_function.sh
#   ./bin/deploy/deploy_grading_function.sh --skip-scheduler  # Deploy function only
#   ./bin/deploy/deploy_grading_function.sh --dry-run         # Show what would be deployed

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
FUNCTION_NAME="phase5b-grading"
REGION="us-west2"
RUNTIME="python311"
ENTRY_POINT="main"
TRIGGER_TOPIC="nba-grading-trigger"
SERVICE_ACCOUNT="756957797294-compute@developer.gserviceaccount.com"
MEMORY="1Gi"
TIMEOUT="300s"  # 5 minutes for grading
MAX_INSTANCES="3"
MIN_INSTANCES="0"

# Scheduler configuration
SCHEDULER_NAME="grading-daily"
SCHEDULER_SCHEDULE="30 12 * * *"  # 7:30 AM ET = 12:30 PM UTC (after Phase 3 completes)
SCHEDULER_TIMEZONE="America/New_York"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SOURCE_DIR="orchestration/cloud_functions/grading"

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
echo -e "${BLUE}Phase 5B Grading Deployment${NC}"
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
echo "  Trigger Topic:   $TRIGGER_TOPIC"
echo "  Schedule:        $SCHEDULER_SCHEDULE ($SCHEDULER_TIMEZONE)"
echo "  Dry Run:         $DRY_RUN"
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

# Check/Create Pub/Sub topics
echo -e "${YELLOW}Checking Pub/Sub topics...${NC}"

if gcloud pubsub topics describe $TRIGGER_TOPIC --project=$PROJECT_ID &>/dev/null; then
    echo -e "${GREEN}✓ Input topic exists: $TRIGGER_TOPIC${NC}"
else
    echo -e "${RED}✗ Input topic not found: $TRIGGER_TOPIC${NC}"
    if ! $DRY_RUN; then
        echo -e "${YELLOW}Creating topic...${NC}"
        gcloud pubsub topics create $TRIGGER_TOPIC --project=$PROJECT_ID
        echo -e "${GREEN}✓ Created topic: $TRIGGER_TOPIC${NC}"
    fi
fi

COMPLETE_TOPIC="nba-grading-complete"
if gcloud pubsub topics describe $COMPLETE_TOPIC --project=$PROJECT_ID &>/dev/null; then
    echo -e "${GREEN}✓ Complete topic exists: $COMPLETE_TOPIC${NC}"
else
    echo -e "${RED}✗ Complete topic not found: $COMPLETE_TOPIC${NC}"
    if ! $DRY_RUN; then
        echo -e "${YELLOW}Creating topic...${NC}"
        gcloud pubsub topics create $COMPLETE_TOPIC --project=$PROJECT_ID
        echo -e "${GREEN}✓ Created topic: $COMPLETE_TOPIC${NC}"
    fi
fi
echo ""

# Navigate to project root
cd "$PROJECT_ROOT"

# Create deployment package with all required dependencies
DEPLOY_DIR=$(mktemp -d)
echo -e "${YELLOW}Preparing deployment package in $DEPLOY_DIR...${NC}"

# Copy cloud function entry point
cp "$SOURCE_DIR/main.py" "$DEPLOY_DIR/"
cp "$SOURCE_DIR/requirements.txt" "$DEPLOY_DIR/"

# Copy required source directories
cp -r data_processors "$DEPLOY_DIR/"
cp -r shared "$DEPLOY_DIR/"
cp -r predictions "$DEPLOY_DIR/"

# Create __init__.py files if missing
touch "$DEPLOY_DIR/data_processors/__init__.py"
touch "$DEPLOY_DIR/data_processors/grading/__init__.py"
touch "$DEPLOY_DIR/data_processors/grading/prediction_accuracy/__init__.py"
touch "$DEPLOY_DIR/data_processors/grading/system_daily_performance/__init__.py"
touch "$DEPLOY_DIR/shared/__init__.py"
touch "$DEPLOY_DIR/predictions/__init__.py"
touch "$DEPLOY_DIR/predictions/worker/__init__.py"

# Add additional dependencies to requirements.txt
cat >> "$DEPLOY_DIR/requirements.txt" << 'EOF'
# Additional dependencies for grading processors
pytz>=2023.0
EOF

echo "Deployment package contents:"
ls -la "$DEPLOY_DIR/"
echo ""

if $DRY_RUN; then
    echo -e "${YELLOW}[DRY RUN] Would deploy function: $FUNCTION_NAME${NC}"
    rm -rf "$DEPLOY_DIR"
    exit 0
fi

# Deploy function
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Deploying Cloud Function...${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime $RUNTIME \
    --region $REGION \
    --source "$DEPLOY_DIR" \
    --entry-point $ENTRY_POINT \
    --trigger-topic $TRIGGER_TOPIC \
    --service-account=$SERVICE_ACCOUNT \
    --set-env-vars GCP_PROJECT=$PROJECT_ID \
    --memory $MEMORY \
    --timeout $TIMEOUT \
    --max-instances $MAX_INSTANCES \
    --min-instances $MIN_INSTANCES \
    --project $PROJECT_ID

# Cleanup temp directory
rm -rf "$DEPLOY_DIR"

echo ""
echo -e "${GREEN}✓ Cloud Function deployed successfully${NC}"
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
        gcloud scheduler jobs update pubsub $SCHEDULER_NAME \
            --location=$REGION \
            --schedule="$SCHEDULER_SCHEDULE" \
            --time-zone="$SCHEDULER_TIMEZONE" \
            --topic="projects/$PROJECT_ID/topics/$TRIGGER_TOPIC" \
            --message-body='{"target_date": "yesterday", "trigger_source": "scheduler", "run_aggregation": true}' \
            --project=$PROJECT_ID
    else
        echo -e "${YELLOW}Creating new scheduler job...${NC}"
        gcloud scheduler jobs create pubsub $SCHEDULER_NAME \
            --location=$REGION \
            --schedule="$SCHEDULER_SCHEDULE" \
            --time-zone="$SCHEDULER_TIMEZONE" \
            --topic="projects/$PROJECT_ID/topics/$TRIGGER_TOPIC" \
            --message-body='{"target_date": "yesterday", "trigger_source": "scheduler", "run_aggregation": true}' \
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
echo "  Cloud Scheduler (7:30 AM ET daily)"
echo "       ↓"
echo "  nba-grading-trigger (Pub/Sub)"
echo "       ↓"
echo "  phase5b-grading (this function)"
echo "       ↓"
echo "  Writes to: prediction_accuracy, system_daily_performance"
echo "       ↓"
echo "  nba-grading-complete (Pub/Sub)"
echo ""

echo -e "${YELLOW}Next Steps:${NC}"
echo "1. View logs:"
echo "   ${BLUE}gcloud functions logs read $FUNCTION_NAME --region $REGION --limit 50${NC}"
echo ""
echo "2. Test by triggering manually:"
echo "   ${BLUE}gcloud pubsub topics publish nba-grading-trigger --message='{\"target_date\":\"2025-12-13\",\"trigger_source\":\"manual\"}'${NC}"
echo ""
echo "3. Run scheduler job immediately:"
echo "   ${BLUE}gcloud scheduler jobs run $SCHEDULER_NAME --location $REGION${NC}"
echo ""
echo "4. Check graded data:"
echo "   ${BLUE}bq query --use_legacy_sql=false 'SELECT MAX(game_date) FROM nba_predictions.prediction_accuracy'${NC}"
echo ""
echo -e "${GREEN}✓ Grading infrastructure deployed successfully!${NC}"
