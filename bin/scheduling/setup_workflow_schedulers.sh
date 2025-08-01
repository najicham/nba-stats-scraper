#!/bin/bash
# SAVE TO: ~/code/nba-stats-scraper/bin/scheduling/setup_workflow_schedulers.sh

PROJECT_ID="nba-props-platform"
REGION="us-west2"

echo "⏰ NBA Workflow Schedulers Setup"
echo "================================"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Timestamp: $(date)"
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

# Step 2: Create workflow schedulers
create_workflow_schedulers() {
    echo ""
    echo "⏰ Step 2: Creating workflow schedulers..."
    
    # Function to create a single scheduler
    create_scheduler() {
        local job_name=$1
        local workflow_name=$2
        local schedule=$3
        local description=$4
        
        echo ""
        echo "📅 Creating $job_name..."
        echo "   Schedule: $schedule"
        echo "   Workflow: $workflow_name"
        
        # Delete existing job if it exists
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
    
    # Create all workflow schedulers
    local created_count=0
    
    if create_scheduler "real-time-business-trigger" "real-time-business" "0 8-20/2 * * *" "Triggers Real-Time Business every 2 hours (8 AM - 8 PM PT)"; then
        created_count=$((created_count + 1))
    fi
    
    if create_scheduler "morning-operations-trigger" "morning-operations" "0 8 * * *" "Triggers Morning Operations daily at 8 AM PT"; then
        created_count=$((created_count + 1))
    fi
    
    if create_scheduler "game-day-evening-trigger" "game-day-evening" "0 18,21,23 * * *" "Triggers Game Day Evening at 6 PM, 9 PM, 11 PM PT"; then
        created_count=$((created_count + 1))
    fi
    
    if create_scheduler "post-game-analysis-trigger" "post-game-analysis" "0 21 * * *" "Triggers Post-Game Analysis daily at 9 PM PT"; then
        created_count=$((created_count + 1))
    fi
    
    echo ""
    echo "📊 Created $created_count/4 workflow schedulers"
}

# Step 3: Verify setup
verify_setup() {
    echo ""
    echo "🔍 Step 3: Verifying setup..."
    
    echo ""
    echo "🚀 Available Workflows:"
    if ! gcloud workflows list --location=$REGION --format="table(name,state)" 2>/dev/null; then
        echo "❌ No workflows found or permission issue"
        return 1
    fi
    
    echo ""
    echo "⏰ Workflow Schedulers:"
    if ! gcloud scheduler jobs list --location=$REGION --filter="name ~ .*trigger" --format="table(name,schedule,state)" 2>/dev/null; then
        echo "❌ No workflow schedulers found"
        return 1
    fi
    
    echo ""
    echo "✅ Setup verification complete"
}

# Step 4: Show next steps
show_next_steps() {
    echo ""
    echo "📝 Step 4: Next Steps"
    echo "===================="
    
    echo ""
    echo "📅 Your Automated Schedule:"
    echo "• real-time-business-trigger: Every 2 hours (8 AM - 8 PM PT)"
    echo "• morning-operations-trigger: Daily at 8 AM PT"  
    echo "• game-day-evening-trigger: 6 PM, 9 PM, 11 PM PT"
    echo "• post-game-analysis-trigger: Daily at 9 PM PT"
    echo ""
    
    echo "🎯 Recommended Actions:"
    echo "1. Monitor workflow executions for 24-48 hours"
    echo "2. Verify business logic works correctly"
    echo "3. Use bin/scheduling/pause_all_schedulers.sh to transition from old system"
    echo ""
    
    echo "🔍 Monitoring Commands:"
    echo "# Check recent workflow executions"
    echo "gcloud workflows executions list real-time-business --location=$REGION --limit=5"
    echo ""
    echo "# Monitor all workflow schedulers"
    echo "gcloud scheduler jobs list --location=$REGION --filter='name ~ .*trigger'"
    echo ""
    echo "# View workflow logs"
    echo "gcloud logging read 'resource.type=\"cloud_workflow\"' --limit=20"
}

# Main execution
echo "Starting workflow scheduler setup..."

setup_service_account
create_workflow_schedulers
verify_setup
show_next_steps

echo ""
echo "🎉 Workflow scheduler setup complete!"
echo "Your NBA workflows are now running automatically on schedule."
