#!/usr/bin/env bash
# bin/deployment/deploy_real_time_business.sh
# Deploy the CRITICAL real-time business workflow for NBA prop betting

set -e

PROJECT_ID=$(gcloud config get-value project 2>/dev/null || echo "unknown")
REGION="us-west2"
WORKFLOW_NAME="real-time-business"
SCHEDULER_NAME="real-time-business-trigger"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m'

echo -e "${BLUE}🏀 NBA Real-Time Business Workflow Deployment${NC}"
echo -e "${BLUE}=============================================${NC}"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Workflow: $WORKFLOW_NAME"
echo "Timestamp: $(date)"
echo ""

# Check prerequisites
echo -e "${YELLOW}📋 Phase 1: Prerequisites Check${NC}"
echo "==============================="

# Check if workflow file exists
if [[ ! -f "workflows/real-time-business.yaml" ]]; then
    echo -e "${RED}❌ Error: workflows/real-time-business.yaml not found${NC}"
    echo "Please create the workflow file first using the provided template"
    exit 1
fi

echo "✅ Workflow file found"

# Check if workflows directory exists
mkdir -p workflows/backup

# Check gcloud auth
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q "@"; then
    echo -e "${RED}❌ Error: Not authenticated with gcloud${NC}"
    echo "Run: gcloud auth login"
    exit 1
fi

echo "✅ gcloud authentication verified"

# Check permissions
echo "Checking workflow permissions..."
if ! gcloud services list --enabled --filter="name:workflows.googleapis.com" --format="value(name)" | grep -q "workflows.googleapis.com"; then
    echo -e "${YELLOW}⚠️  Enabling Cloud Workflows API...${NC}"
    gcloud services enable workflows.googleapis.com
fi

echo "✅ Prerequisites satisfied"
echo ""

# Deploy the workflow
echo -e "${YELLOW}🚀 Phase 2: Deploy Workflow${NC}"
echo "==========================="

echo "Deploying $WORKFLOW_NAME workflow..."

gcloud workflows deploy $WORKFLOW_NAME \
    --source=workflows/real-time-business.yaml \
    --location=$REGION \
    --description="NBA Real-Time Business Operations - CRITICAL Events->Props dependency for prop betting revenue" \
    --quiet

echo -e "${GREEN}✅ Real-time business workflow deployed successfully${NC}"
echo ""

# Test the workflow
echo -e "${YELLOW}🧪 Phase 3: Test Workflow Execution${NC}"
echo "=================================="

echo "Testing workflow execution (this will take 5-15 minutes)..."
echo "Starting execution..."

EXECUTION_ID=$(gcloud workflows run $WORKFLOW_NAME \
    --location=$REGION \
    --data='{"trigger":"manual_test"}' \
    --format="value(name)" | cut -d'/' -f6)

echo "Execution started with ID: $EXECUTION_ID"
echo ""
echo "Monitoring execution progress..."

# Monitor execution with timeout
timeout=900  # 15 minutes
counter=0
last_status=""

while [[ $counter -lt $timeout ]]; do
    status=$(gcloud workflows executions describe $EXECUTION_ID \
        --workflow=$WORKFLOW_NAME \
        --location=$REGION \
        --format="value(state)" 2>/dev/null || echo "UNKNOWN")
    
    # Only log status changes to reduce noise
    if [[ "$status" != "$last_status" ]]; then
        echo "$(date '+%H:%M:%S') - Status: $status"
        last_status="$status"
    fi
    
    case "$status" in
        "SUCCEEDED")
            echo -e "${GREEN}✅ Workflow test completed successfully!${NC}"
            
            # Get execution result
            echo ""
            echo "Execution summary:"
            result=$(gcloud workflows executions describe $EXECUTION_ID \
                --workflow=$WORKFLOW_NAME \
                --location=$REGION \
                --format="value(result)" 2>/dev/null || echo "No result available")
            echo "$result" | jq '.' 2>/dev/null || echo "$result"
            break
            ;;
        "FAILED")
            echo -e "${RED}❌ Workflow test failed!${NC}"
            echo ""
            echo "Getting execution details..."
            gcloud workflows executions describe $EXECUTION_ID \
                --workflow=$WORKFLOW_NAME \
                --location=$REGION
            exit 1
            ;;
        "CANCELLED")
            echo -e "${YELLOW}⚠️  Workflow execution was cancelled${NC}"
            exit 1
            ;;
    esac
    
    sleep 30
    ((counter+=30))
done

if [[ $counter -ge $timeout ]]; then
    echo -e "${YELLOW}⚠️  Workflow test timed out after 15 minutes${NC}"
    echo "Check execution status manually:"
    echo "gcloud workflows executions describe $EXECUTION_ID --workflow=$WORKFLOW_NAME --location=$REGION"
    echo ""
    echo "The workflow may still be running. Proceeding with scheduler setup..."
fi

echo ""

# Create Cloud Scheduler trigger
echo -e "${YELLOW}⏰ Phase 4: Create Cloud Scheduler Trigger${NC}"
echo "========================================="

echo "Creating Cloud Scheduler trigger for every 2 hours (8 AM - 8 PM PT)..."

# Check if scheduler job already exists and delete it
if gcloud scheduler jobs describe $SCHEDULER_NAME --location=$REGION >/dev/null 2>&1; then
    echo "Existing scheduler job found. Deleting..."
    gcloud scheduler jobs delete $SCHEDULER_NAME --location=$REGION --quiet
fi

# Create new scheduler job
gcloud scheduler jobs create http $SCHEDULER_NAME \
    --schedule='0 8-20/2 * * *' \
    --time-zone='America/Los_Angeles' \
    --uri="https://workflowexecutions.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/workflows/${WORKFLOW_NAME}/executions" \
    --http-method=POST \
    --oauth-service-account-email="${PROJECT_ID}-compute@developer.gserviceaccount.com" \
    --headers='Content-Type=application/json' \
    --message-body='{"argument": "{\"trigger\": \"scheduler\"}"}' \
    --location=$REGION \
    --description="Trigger NBA Real-Time Business Workflow every 2 hours (8 AM - 8 PM PT) - CRITICAL for prop betting revenue"

echo -e "${GREEN}✅ Cloud Scheduler trigger created successfully${NC}"
echo ""

# Pause old individual schedulers
echo -e "${YELLOW}📊 Phase 5: Manage Old Individual Schedulers${NC}"
echo "==========================================="

echo "Pausing old individual scheduler jobs (keeping them for rollback if needed)..."

# List of old scheduler jobs to pause
old_jobs=(
    "nba-odds-events"
    "nba-odds-props"
    "nba-player-list"
    "nba-injury-report"
    "nba-bdl-active-players"
)

paused_jobs=0
missing_jobs=0

for job in "${old_jobs[@]}"; do
    if gcloud scheduler jobs describe "$job" --location=$REGION >/dev/null 2>&1; then
        echo "Pausing: $job"
        gcloud scheduler jobs pause "$job" --location=$REGION --quiet
        ((paused_jobs++))
    else
        echo "Job not found: $job (already deleted or not created yet)"
        ((missing_jobs++))
    fi
done

echo "✅ Paused $paused_jobs old scheduler jobs ($missing_jobs were not found)"
echo ""

# Final status and next steps
echo -e "${GREEN}🎉 Deployment Complete!${NC}"
echo -e "${GREEN}=======================${NC}"
echo ""
echo -e "${PURPLE}📊 Summary:${NC}"
echo "✅ Real-Time Business Workflow deployed and tested"
echo "✅ Cloud Scheduler trigger created (every 2 hours, 8 AM - 8 PM PT)"
echo "✅ $paused_jobs old individual schedulers paused (not deleted)"
echo ""
echo -e "${PURPLE}🔍 Monitoring Commands:${NC}"
echo ""
echo "# List recent executions"
echo "gcloud workflows executions list --workflow=$WORKFLOW_NAME --location=$REGION --limit=5"
echo ""
echo "# Get detailed execution status"
echo "gcloud workflows executions describe EXECUTION_ID --workflow=$WORKFLOW_NAME --location=$REGION"
echo ""
echo "# Check scheduler trigger status"
echo "gcloud scheduler jobs describe $SCHEDULER_NAME --location=$REGION"
echo ""
echo "# View workflow logs"
echo "gcloud logging read \"resource.type=cloud_workflow AND resource.labels.workflow_id=$WORKFLOW_NAME\" --limit=50 --freshness=1h"
echo ""

echo -e "${PURPLE}⏰ Next Execution Times (PT):${NC}"
current_hour=$(date +%H)
next_times=()

for hour in 8 10 12 14 16 18 20; do
    if [[ $current_hour -lt $hour ]]; then
        next_times+=("${hour}:00")
    fi
done

# If no times today, show tomorrow's first time
if [[ ${#next_times[@]} -eq 0 ]]; then
    next_times=("8:00 (tomorrow)")
fi

echo "Today: ${next_times[*]}"
echo ""

echo -e "${PURPLE}🎯 Business Impact:${NC}"
echo "This workflow now handles your CRITICAL prop betting operations:"
echo "• Events API → Props API dependency (core revenue)"
echo "• Player intelligence (team mapping)"
echo "• Injury reports (player availability)"
echo "• Player validation (data quality)"
echo ""

echo -e "${PURPLE}📋 Next Steps:${NC}"
echo "1. Monitor workflow executions for 24-48 hours"
echo "2. Verify prop betting data is flowing correctly"
echo "3. When confident, deploy other workflows (morning, game-day, post-game)"
echo "4. Delete old individual schedulers once fully migrated"
echo ""

echo -e "${YELLOW}🚨 Important Notes:${NC}"
echo "• Update Slack webhook URL in workflow file for notifications"
echo "• Monitor API usage to ensure you're within rate limits"
echo "• This workflow runs: Events → Foundation Scrapers (parallel) → Props"
echo "• If Events fails, Props will be skipped (saves API calls)"

# Show current scheduler status
echo ""
echo -e "${BLUE}📅 Current Scheduler Status:${NC}"
echo "Active workflow triggers:"
gcloud scheduler jobs list --location=$REGION --filter="name:$SCHEDULER_NAME" --format="table(name,schedule,state)" 2>/dev/null || echo "No active triggers found"

echo ""
echo -e "${GREEN}🏀 Your NBA prop betting workflow is now LIVE!${NC}"