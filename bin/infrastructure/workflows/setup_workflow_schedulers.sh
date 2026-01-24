#!/bin/bash
set -euo pipefail
# SAVE TO: ~/code/nba-stats-scraper/bin/scheduling/setup_workflow_schedulers.sh
# Updated for NEW 5-workflow system with 12 total daily executions

PROJECT_ID="nba-props-platform"
REGION="us-west2"

echo "⏰ NBA Workflow Schedulers Setup (NEW 5-Workflow System)"
echo "========================================================"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Timestamp: $(date)"
echo ""
echo "📊 Target: 12 total workflow executions per day"
echo "🎯 5 workflows with strategic scheduling for complete data coverage"
echo ""

# Step 1: Ensure service account exists and has permissions
setup_service_account() {
    echo "👤 Step 1: Setting up service account..."
    
    # Create service account if it doesn't exist
    if ! gcloud iam service-accounts describe workflow-scheduler@$PROJECT_ID.iam.gserviceaccount.com >/dev/null 2>&1; then
        echo "Creating workflow-scheduler service account..."
        gcloud iam service-accounts create workflow-scheduler \
            --description="Service account for Cloud Scheduler to trigger workflows" \
            --display-name="Workflow Scheduler" \
            --project=$PROJECT_ID
    else
        echo "✅ Service account already exists"
    fi
    
    # Grant necessary permissions
    echo "Ensuring proper permissions..."
    local permissions=(
        "roles/workflows.invoker"
        "roles/logging.logWriter"
        "roles/cloudscheduler.jobRunner"
    )
    
    for permission in "${permissions[@]}"; do
        gcloud projects add-iam-policy-binding $PROJECT_ID \
            --member="serviceAccount:workflow-scheduler@$PROJECT_ID.iam.gserviceaccount.com" \
            --role="$permission" \
            --quiet >/dev/null 2>&1
    done
    
    echo "✅ Service account configured"
}

# Step 2: Clean up OLD workflow schedulers  
cleanup_old_schedulers() {
    echo ""
    echo "🗑️ Step 2: Cleaning up OLD workflow schedulers..."
    
    local old_schedulers=(
        "game-day-evening-trigger"
        "post-game-analysis-trigger"
    )
    
    local cleaned_count=0
    for scheduler in "${old_schedulers[@]}"; do
        if gcloud scheduler jobs describe $scheduler --location=$REGION >/dev/null 2>&1; then
            echo "Deleting old scheduler: $scheduler"
            if gcloud scheduler jobs delete $scheduler --location=$REGION --quiet; then
                echo "✅ $scheduler deleted"
                cleaned_count=$((cleaned_count + 1))
            else
                echo "❌ Failed to delete $scheduler"
            fi
        else
            echo "ℹ️ $scheduler not found (already deleted)"
        fi
    done
    
    echo "📊 Cleaned up $cleaned_count old schedulers"
}

# Step 3: Create NEW workflow schedulers for 12-execution system
create_workflow_schedulers() {
    echo ""
    echo "⏰ Step 3: Creating NEW 5-workflow schedulers (12 total executions)..."
    
    # Function to create a single scheduler
    create_scheduler() {
        local job_name=$1
        local workflow_name=$2
        local schedule=$3
        local description=$4
        local executions_per_day=$5
        
        echo ""
        echo "📅 Creating $job_name..."
        echo "   Schedule: $schedule"
        echo "   Workflow: $workflow_name"
        echo "   Executions/day: $executions_per_day"
        echo "   Description: $description"
        
        # Delete existing job if it exists (for updates)
        gcloud scheduler jobs delete $job_name --location=$REGION --quiet 2>/dev/null || true
        
        if gcloud scheduler jobs create http $job_name \
            --location=$REGION \
            --schedule="$schedule" \
            --time-zone="America/Los_Angeles" \
            --uri="https://workflowexecutions.googleapis.com/v1/projects/$PROJECT_ID/locations/$REGION/workflows/$workflow_name/executions" \
            --http-method=POST \
            --headers="Content-Type=application/json" \
            --oauth-service-account-email="workflow-scheduler@$PROJECT_ID.iam.gserviceaccount.com" \
            --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform" \
            --message-body='{}' \
            --description="$description" >/dev/null 2>&1; then
            echo "✅ $job_name created successfully"
            return 0
        else
            echo "❌ Failed to create $job_name"
            return 1
        fi
    }
    
    # Create all NEW workflow schedulers
    local created_count=0
    local total_daily_executions=0
    
    # 1. Early Morning Final Check (6AM PT) - 1 execution
    if create_scheduler "early-morning-final-check-trigger" "early-morning-final-check" "0 6 * * *" "Final recovery attempt + Enhanced PBP (6AM PT)" "1"; then
        created_count=$((created_count + 1))
        total_daily_executions=$((total_daily_executions + 1))
    fi
    
    # 2. Morning Operations (8AM PT) - 1 execution  
    if create_scheduler "morning-operations-trigger" "morning-operations" "0 8 * * *" "Daily setup + Enhanced PBP recovery (8AM PT)" "1"; then
        created_count=$((created_count + 1))
        total_daily_executions=$((total_daily_executions + 1))
    fi
    
    # 3. Real-Time Business (Every 2h, 8AM-8PM PT) - 7 executions
    if create_scheduler "real-time-business-trigger" "real-time-business" "0 8-20/2 * * *" "CRITICAL Events→Props revenue chain (Every 2h: 8AM-8PM PT)" "7"; then
        created_count=$((created_count + 1))
        total_daily_executions=$((total_daily_executions + 7))
    fi
    
    # 4. Post-Game Collection (8PM & 11PM PT) - 2 executions
    if create_scheduler "post-game-collection-trigger" "post-game-collection" "0 20,23 * * *" "Core game data collection (8PM & 11PM PT)" "2"; then
        created_count=$((created_count + 1))
        total_daily_executions=$((total_daily_executions + 2))
    fi
    
    # 5. Late Night Recovery (2AM PT) - 1 execution
    if create_scheduler "late-night-recovery-trigger" "late-night-recovery" "0 2 * * *" "Enhanced PBP + comprehensive retry (2AM PT)" "1"; then
        created_count=$((created_count + 1))
        total_daily_executions=$((total_daily_executions + 1))
    fi
    
    echo ""
    echo "📊 Scheduler Creation Summary:"
    echo "• Created: $created_count/5 workflow schedulers"  
    echo "• Total daily executions: $total_daily_executions"
    echo "• Target daily executions: 12"
    
    if [[ $total_daily_executions -eq 12 ]]; then
        echo "✅ Perfect! Achieved target of 12 daily executions"
    else
        echo "⚠️ Expected 12 daily executions, got $total_daily_executions"
    fi
}

# Step 4: Verify setup and show execution timeline
verify_setup() {
    echo ""
    echo "🔍 Step 4: Verifying NEW scheduler setup..."
    
    echo ""
    echo "🚀 Available Workflows:"
    if ! gcloud workflows list --location=$REGION --format="table(name.basename(),state)" 2>/dev/null; then
        echo "❌ No workflows found or permission issue"
        return 1
    fi
    
    echo ""
    echo "⏰ NEW Workflow Schedulers:"
    if ! gcloud scheduler jobs list --location=$REGION --filter="name ~ .*trigger" --format="table(name,schedule,state)" 2>/dev/null; then
        echo "❌ No workflow schedulers found"
        return 1
    fi
    
    echo ""
    echo "📅 Daily Execution Timeline (Pacific Time):"
    echo "┌─────────┬────────────────────────────┬─────────────────────────────────┐"
    echo "│  Time   │         Workflow           │           Purpose               │"
    echo "├─────────┼────────────────────────────┼─────────────────────────────────┤"
    echo "│  2:00   │ late-night-recovery        │ Enhanced PBP + comprehensive    │"
    echo "│  6:00   │ early-morning-final-check  │ Final recovery attempt          │"
    echo "│  8:00   │ morning-operations         │ Daily setup + Enhanced PBP      │"
    echo "│  8:00   │ real-time-business #1      │ Events→Props (CRITICAL)        │"
    echo "│ 10:00   │ real-time-business #2      │ Events→Props                    │"
    echo "│ 12:00   │ real-time-business #3      │ Events→Props                    │"
    echo "│ 14:00   │ real-time-business #4      │ Events→Props                    │"
    echo "│ 16:00   │ real-time-business #5      │ Events→Props                    │"
    echo "│ 18:00   │ real-time-business #6      │ Events→Props                    │"
    echo "│ 20:00   │ real-time-business #7      │ Events→Props                    │"
    echo "│ 20:00   │ post-game-collection #1    │ Core game data                  │"
    echo "│ 23:00   │ post-game-collection #2    │ Core game data                  │"
    echo "└─────────┴────────────────────────────┴─────────────────────────────────┘"
    echo ""
    echo "📊 Total: 12 executions per day"
    echo ""
    echo "✅ Setup verification complete"
}

# Step 5: Show monitoring and next steps
show_next_steps() {
    echo ""
    echo "📝 Step 5: Monitoring & Next Steps"
    echo "=================================="
    
    echo ""
    echo "🎯 Key Success Metrics:"
    echo "• 💼 Real-Time Business: Events→Props dependency must succeed (REVENUE CRITICAL)"
    echo "• 🏀 Post-Game Collection: Core game data for analysis"
    echo "• 🌙 Late Night Recovery: Enhanced PBP collection (available 2+ hours after games)"
    echo "• 📁 Status Tracking: All workflows write to gs://nba-props-status/workflow-status/"
    echo ""
    
    echo "🔍 Essential Monitoring Commands:"
    echo ""
    echo "# Complete system overview"
    echo "bin/monitoring/monitor_workflows.sh detailed"
    echo ""
    echo "# Check critical revenue workflow"
    echo "gcloud workflows executions list real-time-business --location=$REGION --limit=5"
    echo ""
    echo "# Monitor scheduler health"
    echo "gcloud scheduler jobs list --location=$REGION --filter='name ~ .*trigger'"
    echo ""
    echo "# Check status files (foundation for future smart recovery)"
    echo "gsutil ls gs://nba-props-status/workflow-status/\$(date +%Y-%m-%d)/"
    echo ""
    
    echo "⚠️ Critical Monitoring Points:"
    echo "1. 💼 Real-Time Business success rate must stay > 95% (revenue protection)"
    echo "2. 🔄 Full recovery chain: 8PM → 11PM → 2AM → 6AM → 8AM" 
    echo "3. 📊 Enhanced PBP collection success by 8AM (available 2+ hours post-game)"
    echo "4. 📁 Status tracking files being written correctly"
    echo ""
    
    echo "🚀 Ready for Production:"
    echo "• ✅ 5-workflow system deployed with comprehensive recovery"
    echo "• ✅ 12-execution schedule provides continuous data collection"  
    echo "• ✅ Revenue-critical Events→Props dependency protected"
    echo "• ✅ Foundation built for future smart recovery & backfill workflows"
}

# Main execution
echo "Starting NEW 5-workflow scheduler setup..."

setup_service_account
cleanup_old_schedulers  
create_workflow_schedulers
verify_setup
show_next_steps

echo ""
echo "🎉 NEW 5-workflow scheduler setup complete!"
echo ""
echo "📈 Your system now runs 12 executions per day with:"
echo "• 🌅 Comprehensive recovery strategy (2AM → 6AM → 8AM)"
echo "• 💼 Revenue-critical Events→Props protection (7 times daily)" 
echo "• 🏀 Reliable game data collection (8PM & 11PM)"
echo "• 📁 Status tracking foundation for future enhancements"
echo ""
echo "Next: Monitor the system and consider backfill workflow development!"
