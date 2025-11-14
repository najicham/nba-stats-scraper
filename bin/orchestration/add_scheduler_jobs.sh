#!/bin/bash
# bin/orchestration/add_scheduler_jobs.sh
#
# Add Cloud Scheduler jobs for orchestration to existing nba-scrapers service
# This is a ONE-TIME setup - run after fixes are deployed to nba-scrapers
#
# Version 2.0 - Added Phase 1 Workflow Executor job
#
# Usage: ./bin/orchestration/add_scheduler_jobs.sh

set -e

PROJECT_ID="nba-props-platform"
REGION="us-west2"
SERVICE_NAME="nba-scrapers"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🕐 Adding Cloud Scheduler Jobs for Orchestration"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Service: ${SERVICE_NAME}"
echo "Version: 2.0 (Phase 1 - Workflow Executor)"
echo ""

# Get service URL
echo "Getting service URL..."
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
  --region=${REGION} \
  --format="value(status.url)" \
  --project=${PROJECT_ID})

if [[ -z "$SERVICE_URL" ]]; then
    echo "❌ Error: Cloud Run service '${SERVICE_NAME}' not found."
    echo "   Deploy scrapers first: ./bin/scrapers/deploy/deploy_scrapers_simple.sh"
    exit 1
fi

echo "✅ Service found: ${SERVICE_URL}"
echo ""

# Create service account for Cloud Scheduler if needed
echo "Setting up service account..."
if gcloud iam service-accounts describe scheduler-orchestration@${PROJECT_ID}.iam.gserviceaccount.com \
    --project=${PROJECT_ID} &>/dev/null; then
    echo "✅ Service account already exists"
else
    echo "Creating service account..."
    gcloud iam service-accounts create scheduler-orchestration \
        --display-name="Cloud Scheduler - Orchestration Jobs" \
        --project=${PROJECT_ID}
    
    echo "✅ Service account created"
fi

# Grant invoker permission
echo "Granting Cloud Run invoker permission..."
gcloud run services add-iam-policy-binding ${SERVICE_NAME} \
    --member="serviceAccount:scheduler-orchestration@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/run.invoker" \
    --region=${REGION} \
    --project=${PROJECT_ID} \
    --quiet

echo "✅ Permissions granted"
echo ""

# Function to create or update job
create_or_update_job() {
    local job_name=$1
    local schedule=$2
    local uri=$3
    local description=$4
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Setting up: ${job_name}"
    echo "Schedule: ${schedule}"
    echo "Endpoint: ${uri}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    if gcloud scheduler jobs describe ${job_name} \
        --location=${REGION} \
        --project=${PROJECT_ID} &>/dev/null; then
        
        echo "Job exists, updating..."
        gcloud scheduler jobs update http ${job_name} \
            --location=${REGION} \
            --schedule="${schedule}" \
            --time-zone="America/New_York" \
            --uri="${uri}" \
            --http-method=POST \
            --oidc-service-account-email="scheduler-orchestration@${PROJECT_ID}.iam.gserviceaccount.com" \
            --headers="Content-Type=application/json" \
            --message-body='{}' \
            --attempt-deadline=180s \
            --project=${PROJECT_ID} \
            --quiet
        
        echo "✅ Updated: ${job_name}"
    else
        echo "Creating new job..."
        gcloud scheduler jobs create http ${job_name} \
            --location=${REGION} \
            --schedule="${schedule}" \
            --time-zone="America/New_York" \
            --uri="${uri}" \
            --http-method=POST \
            --oidc-service-account-email="scheduler-orchestration@${PROJECT_ID}.iam.gserviceaccount.com" \
            --headers="Content-Type=application/json" \
            --message-body='{}' \
            --attempt-deadline=180s \
            --description="${description}" \
            --project=${PROJECT_ID} \
            --quiet
        
        echo "✅ Created: ${job_name}"
    fi
    echo ""
}

# Create/update the 4 scheduler jobs
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Creating Scheduler Jobs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Job 1: Daily Schedule Locker - 5 AM ET (10 AM UTC)
create_or_update_job \
    "daily-schedule-locker" \
    "0 10 * * *" \
    "${SERVICE_URL}/generate-daily-schedule" \
    "Generate daily expected workflow schedule at 5 AM ET"

# Job 2: Master Controller - Hourly at :00, 6 AM - 11 PM ET (11 AM - 4 AM UTC)
create_or_update_job \
    "master-controller-hourly" \
    "0 6-23 * * *" \
    "${SERVICE_URL}/evaluate" \
    "Evaluate workflow execution decisions hourly at :00, 6 AM-11 PM ET"

# Job 3: 🆕 PHASE 1 - Workflow Executor - Hourly at :05, 6 AM - 11 PM ET (11:05 AM - 4:05 AM UTC)
create_or_update_job \
    "workflow-executor-hourly" \
    "5 6-23 * * *" \
    "${SERVICE_URL}/execute-workflows" \
    "Execute pending workflows hourly at :05 (5 min after evaluation), 6 AM-11 PM ET"

# Job 4: Cleanup Processor - Every 15 minutes
create_or_update_job \
    "cleanup-processor" \
    "*/15 * * * *" \
    "${SERVICE_URL}/cleanup" \
    "Check for orphaned files and republish every 15 minutes"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Setup Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Scheduler Jobs Created:"
echo ""
echo "  1. daily-schedule-locker"
echo "     Schedule: 5:00 AM ET daily (10:00 UTC)"
echo "     Purpose: Generate daily workflow schedule"
echo ""
echo "  2. master-controller-hourly"
echo "     Schedule: Every hour at :00, 6 AM-11 PM ET (11:00-04:00 UTC)"
echo "     Purpose: Evaluate which workflows should run"
echo ""
echo "  3. workflow-executor-hourly 🆕"
echo "     Schedule: Every hour at :05, 6 AM-11 PM ET (11:05-04:05 UTC)"
echo "     Purpose: Execute workflows decided by master controller"
echo ""
echo "  4. cleanup-processor"
echo "     Schedule: Every 15 minutes"
echo "     Purpose: Self-healing - detect and recover orphaned files"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Execution Flow (Phase 1):"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  6:00 AM → /evaluate (master controller)"
echo "             ↓ Logs RUN/SKIP decisions to BigQuery"
echo "             ↓"
echo "  6:05 AM → /execute-workflows (NEW!)"
echo "             ↓ Reads RUN decisions"
echo "             ↓ Calls scrapers via HTTP"
echo "             ↓ Logs to workflow_executions table"
echo "             ↓"
echo "  7:00 AM → /evaluate (master controller)"
echo "  7:05 AM → /execute-workflows"
echo "  ..."
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "View Scheduler Jobs:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
gcloud scheduler jobs list --location=${REGION} --project=${PROJECT_ID}
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Next Steps:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "1. Verify Phase 1 tables exist:"
echo "   bq show nba-props-platform:nba_orchestration.workflow_executions"
echo ""
echo "2. Test Phase 1 flow manually:"
echo "   # Step 1: Evaluate workflows"
echo "   gcloud scheduler jobs run master-controller-hourly --location=${REGION}"
echo ""
echo "   # Step 2: Wait 30 seconds, then execute workflows"
echo "   gcloud scheduler jobs run workflow-executor-hourly --location=${REGION}"
echo ""
echo "3. Check Phase 1 results in BigQuery:"
echo "   # Decisions made"
echo "   bq query 'SELECT * FROM nba_orchestration.workflow_decisions WHERE DATE(decision_time) = CURRENT_DATE() ORDER BY decision_time DESC LIMIT 10'"
echo ""
echo "   # Workflows executed"
echo "   bq query 'SELECT * FROM nba_orchestration.workflow_executions WHERE DATE(execution_time) = CURRENT_DATE() ORDER BY execution_time DESC LIMIT 10'"
echo ""
echo "   # Scrapers called by controller"
echo "   bq query 'SELECT * FROM nba_orchestration.scraper_execution_log WHERE source = \"CONTROLLER\" AND DATE(triggered_at) = CURRENT_DATE() ORDER BY triggered_at DESC LIMIT 20'"
echo ""
echo "4. Monitor logs:"
echo "   # Scheduler logs"
echo "   gcloud logging read 'resource.type=cloud_scheduler_job' --limit=20"
echo ""
echo "   # Service logs (filter for workflow executor)"
echo "   gcloud logging read 'resource.type=cloud_run_revision AND resource.labels.service_name=nba-scrapers AND \"Workflow Executor\"' --limit=50"
echo ""
echo "5. Verify end-to-end flow:"
echo "   # Link decision → execution → scraper results"
echo "   bq query --use_legacy_sql=false '"
echo "   SELECT "
echo "     d.workflow_name,"
echo "     d.action,"
echo "     d.decision_time,"
echo "     e.execution_time,"
echo "     e.status,"
echo "     e.scrapers_triggered,"
echo "     e.scrapers_succeeded"
echo "   FROM \`nba-props-platform.nba_orchestration.workflow_decisions\` d"
echo "   LEFT JOIN \`nba-props-platform.nba_orchestration.workflow_executions\` e"
echo "     ON d.decision_id = e.decision_id"
echo "   WHERE DATE(d.decision_time) = CURRENT_DATE()"
echo "   ORDER BY d.decision_time DESC"
echo "   '"
echo ""
echo "6. Tomorrow morning (after automatic runs):"
echo "   # Check if workflows ran automatically"
echo "   bq query 'SELECT workflow_name, COUNT(*) as runs FROM nba_orchestration.workflow_executions WHERE DATE(execution_time) = CURRENT_DATE() GROUP BY workflow_name'"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Phase 1 is now deployed! 🚀"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"