#!/bin/bash
# SAVE TO: ~/code/nba-stats-scraper/bin/deploy/deploy_workflows.sh

PROJECT_ID="nba-props-platform"
REGION="us-west2"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "🚀 NBA Workflows Deployment"
echo "==========================="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Project Root: $PROJECT_ROOT"
echo "Timestamp: $(date)"
echo ""

# Step 1: Validate workflow files exist
validate_workflows() {
    echo "📋 Step 1: Validating workflow files..."
    
    local workflows_dir="$PROJECT_ROOT/workflows"
    local required_workflows=(
        "real-time-business.yaml"
        "game-day-evening.yaml"
        "post-game-analysis.yaml"
        "morning-operations.yaml"
    )
    
    if [[ ! -d "$workflows_dir" ]]; then
        echo "❌ Workflows directory not found: $workflows_dir"
        echo "Please create the workflows directory and add YAML files"
        exit 1
    fi
    
    local missing_files=()
    for workflow in "${required_workflows[@]}"; do
        if [[ -f "$workflows_dir/$workflow" ]]; then
            echo "✅ Found: $workflow"
        else
            echo "❌ Missing: $workflow"
            missing_files+=("$workflow")
        fi
    done
    
    if [[ ${#missing_files[@]} -gt 0 ]]; then
        echo ""
        echo "❌ Missing workflow files. Please add:"
        for file in "${missing_files[@]}"; do
            echo "   • $workflows_dir/$file"
        done
        exit 1
    fi
    
    echo "✅ All workflow files found"
}

# Step 2: Deploy workflows
deploy_workflows() {
    echo ""
    echo "🚀 Step 2: Deploying workflows..."
    
    local workflows_dir="$PROJECT_ROOT/workflows"
    local workflows=(
        "real-time-business:NBA Real-Time Business Operations - CRITICAL Events->Props dependency"
        "game-day-evening:NBA Game Day Evening - Live game monitoring"
        "post-game-analysis:NBA Post-Game Analysis - Detailed stats and analytics"
        "morning-operations:NBA Morning Operations - Daily setup and roster updates"
    )
    
    local deployed_count=0
    for workflow_info in "${workflows[@]}"; do
        IFS=':' read -r workflow_name description <<< "$workflow_info"
        
        echo ""
        echo "📦 Deploying $workflow_name..."
        
        if gcloud workflows deploy $workflow_name \
            --source="$workflows_dir/$workflow_name.yaml" \
            --location=$REGION \
            --description="$description" \
            --service-account="756957797294-compute@developer.gserviceaccount.com"; then
            echo "✅ $workflow_name deployed successfully"
            deployed_count=$((deployed_count + 1))
        else
            echo "❌ Failed to deploy $workflow_name"
            echo "🔍 Check YAML syntax in $workflows_dir/$workflow_name.yaml"
        fi
    done
    
    echo ""
    echo "📊 Deployment Summary: $deployed_count/4 workflows deployed"
}

# Step 3: Test critical workflow
test_critical_workflow() {
    echo ""
    echo "🧪 Step 3: Testing critical workflow..."
    
    echo "Testing real-time-business workflow (most critical for revenue)..."
    
    local execution_id
    execution_id=$(gcloud workflows run real-time-business --location=$REGION --format="value(name)")
    
    if [[ -n "$execution_id" ]]; then
        echo "✅ Test execution started: $execution_id"
        echo "⏳ Waiting 30 seconds for completion..."
        sleep 30
        
        local status
        status=$(gcloud workflows executions describe "$execution_id" --location=$REGION --workflow=real-time-business --format="value(state)" 2>/dev/null)
        
        echo "📊 Execution status: $status"
        
        if [[ "$status" == "SUCCEEDED" ]]; then
            echo "🎉 Critical workflow test passed!"
        else
            echo "⚠️ Test still running or failed. Check manually:"
            echo "gcloud workflows executions describe $execution_id --location=$REGION --workflow=real-time-business"
        fi
    else
        echo "❌ Failed to start test execution"
    fi
}

# Step 4: Show deployment status
show_deployment_status() {
    echo ""
    echo "📊 Step 4: Deployment Status"
    echo "============================"
    
    echo ""
    echo "🚀 Deployed Workflows:"
    gcloud workflows list --location=$REGION --format="table(name,state,revisionCreateTime)"
    
    echo ""
    echo "📋 Recent Executions (real-time-business):"
    gcloud workflows executions list real-time-business --location=$REGION --limit=3 --format="table(name,state,startTime,endTime)" 2>/dev/null || echo "No executions found"
    
    echo ""
    echo "🎯 Next Steps:"
    echo "1. Set up workflow schedulers: $SCRIPT_DIR/../scheduling/setup_workflow_schedulers.sh"
    echo "2. Monitor workflow executions for a few cycles"
    echo "3. Transition from individual schedulers: $SCRIPT_DIR/../scheduling/pause_all_schedulers.sh"
}

# Main execution
echo "Starting workflow deployment..."

validate_workflows
deploy_workflows
test_critical_workflow
show_deployment_status

echo ""
echo "✅ Workflow deployment complete!"
echo ""
echo "🔍 Monitor workflows:"
echo "gcloud workflows executions list WORKFLOW_NAME --location=$REGION"
