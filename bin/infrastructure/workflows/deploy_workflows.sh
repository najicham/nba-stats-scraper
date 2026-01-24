#!/bin/bash
set -euo pipefail
# SAVE TO: ~/code/nba-stats-scraper/bin/deployment/deploy_workflows.sh
# Enhanced for organized directory structure with category support (macOS compatible)

PROJECT_ID="nba-props-platform"
REGION="us-west2"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Default values
CATEGORY="all"
DRY_RUN=false
VERBOSE=false

# Help function
show_help() {
    cat << EOF
🚀 NBA Workflows Deployment Script (Enhanced)

USAGE:
    $0 [OPTIONS]

OPTIONS:
    --category CATEGORY    Deploy specific category: operational, backfill, admin, all (default: all)
    --dry-run             Show what would be deployed without actually deploying
    --verbose             Show detailed output
    --help                Show this help message

CATEGORIES:
    operational    Production workflows (5 workflows, 12 daily executions)
    backfill       Historical data collection workflows
    admin          System maintenance and utility workflows  
    all            Deploy all categories

EXAMPLES:
    $0                                    # Deploy all workflows
    $0 --category operational             # Deploy only production workflows
    $0 --category backfill                # Deploy only backfill workflows
    $0 --category backfill --dry-run      # Preview backfill deployment
    $0 --category all --verbose           # Deploy all with detailed output

DIRECTORY STRUCTURE:
    workflows/
    ├── operational/    # Daily production workflows
    ├── backfill/       # Historical data collection
    ├── admin/          # System utilities
    └── backup/         # Archived workflows (ignored)
EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --category)
            CATEGORY="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --help)
            show_help
            exit 0
            ;;
        *)
            echo "❌ Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Validate category
if [[ ! "$CATEGORY" =~ ^(operational|backfill|admin|all)$ ]]; then
    echo "❌ Invalid category: $CATEGORY"
    echo "Valid categories: operational, backfill, admin, all"
    exit 1
fi

echo "🚀 NBA Workflows Deployment (Enhanced Directory Structure)"
echo "=========================================================="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Category: $CATEGORY"
echo "Dry Run: $DRY_RUN"
echo "Project Root: $PROJECT_ROOT"
echo "Timestamp: $(date)"
echo ""

# Function to get workflow configurations for a category
get_workflows_for_category() {
    local category="$1"
    
    case "$category" in
        "operational")
            cat << EOF
early-morning-final-check:NBA Early Morning Final Check - Final recovery attempt (6AM PT)
morning-operations:NBA Morning Operations - Daily setup + Enhanced PBP recovery (8AM PT)
real-time-business:NBA Real-Time Business - CRITICAL Events->Props revenue chain (Every 2h)
post-game-collection:NBA Post-Game Collection - Core game data collection (8PM & 11PM PT)
late-night-recovery:NBA Late Night Recovery - Enhanced PBP + comprehensive retry (2AM PT)
EOF
            ;;
        "backfill")
            cat << EOF
collect-nba-historical-schedules:NBA Historical Schedule Collection - Foundation for backfill (2021-2025)
EOF
            ;;
        "admin")
            # Currently empty, will be populated as admin workflows are added
            echo ""
            ;;
        *)
            echo ""
            ;;
    esac
}

# Validation function
validate_workflows() {
    echo "📋 Step 1: Validating workflow files for category: $CATEGORY"
    
    local workflows_dir="$PROJECT_ROOT/workflows"
    local categories_to_check=()
    
    # Determine which categories to validate
    if [[ "$CATEGORY" == "all" ]]; then
        categories_to_check=("operational" "backfill" "admin")
    else
        categories_to_check=("$CATEGORY")
    fi
    
    local total_expected=0
    local total_found=0
    local missing_files=()
    
    for cat in "${categories_to_check[@]}"; do
        local cat_dir="$workflows_dir/$cat"
        
        if [[ ! -d "$cat_dir" ]]; then
            echo "❌ Category directory not found: $cat_dir"
            exit 1
        fi
        
        echo ""
        echo "🔍 Checking $cat category..."
        
        # Get workflows for this category
        local workflows_config
        workflows_config=$(get_workflows_for_category "$cat")
        
        if [[ -z "$workflows_config" ]]; then
            echo "⚠️  No workflows defined for $cat category"
            continue
        fi
        
        # Parse workflow configurations
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            
            local workflow_name="${line%%:*}"
            local workflow_file="$cat_dir/$workflow_name.yaml"
            
            total_expected=$((total_expected + 1))
            
            if [[ -f "$workflow_file" ]]; then
                echo "✅ Found: $cat/$workflow_name.yaml"
                total_found=$((total_found + 1))
            else
                echo "❌ Missing: $cat/$workflow_name.yaml"
                missing_files+=("$cat/$workflow_name.yaml")
            fi
        done <<< "$workflows_config"
    done
    
    echo ""
    echo "📊 Validation Summary: $total_found/$total_expected workflow files found"
    
    if [[ ${#missing_files[@]} -gt 0 ]]; then
        echo ""
        echo "❌ Missing workflow files:"
        for file in "${missing_files[@]}"; do
            echo "   • workflows/$file"
        done
        exit 1
    fi
    
    echo "✅ All required workflow files found"
}

# Deployment function
deploy_workflows() {
    echo ""
    echo "🚀 Step 2: Deploying workflows for category: $CATEGORY"
    
    local workflows_dir="$PROJECT_ROOT/workflows"
    local categories_to_deploy=()
    
    # Determine which categories to deploy
    if [[ "$CATEGORY" == "all" ]]; then
        categories_to_deploy=("operational" "backfill" "admin")
    else
        categories_to_deploy=("$CATEGORY")
    fi
    
    local total_deployed=0
    local total_failed=0
    local failed_workflows=()
    
    for cat in "${categories_to_deploy[@]}"; do
        echo ""
        echo "📂 Deploying $cat workflows..."
        
        # Get workflows for this category
        local workflows_config
        workflows_config=$(get_workflows_for_category "$cat")
        
        if [[ -z "$workflows_config" ]]; then
            echo "⚠️  No workflows to deploy for $cat category"
            continue
        fi
        
        # Deploy each workflow in the category
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            
            IFS=':' read -r workflow_name description <<< "$line"
            local workflow_file="$workflows_dir/$cat/$workflow_name.yaml"
            
            echo ""
            echo "📦 Deploying $workflow_name ($cat)..."
            [[ "$VERBOSE" == true ]] && echo "   File: $workflow_file"
            echo "   Description: $description"
            
            if [[ "$DRY_RUN" == true ]]; then
                echo "🔍 DRY RUN: Would deploy with command:"
                echo "   gcloud workflows deploy $workflow_name --source='$workflow_file' --location=$REGION"
                total_deployed=$((total_deployed + 1))
            else
                if gcloud workflows deploy "$workflow_name" \
                    --source="$workflow_file" \
                    --location="$REGION" \
                    --description="$description" \
                    --service-account="756957797294-compute@developer.gserviceaccount.com"; then
                    echo "✅ $workflow_name deployed successfully"
                    total_deployed=$((total_deployed + 1))
                else
                    echo "❌ Failed to deploy $workflow_name"
                    echo "🔍 Check YAML syntax in $workflow_file"
                    failed_workflows+=("$workflow_name ($cat)")
                    total_failed=$((total_failed + 1))
                fi
            fi
        done <<< "$workflows_config"
    done
    
    echo ""
    echo "📊 Deployment Summary:"
    echo "✅ Successfully deployed: $total_deployed workflows"
    [[ $total_failed -gt 0 ]] && echo "❌ Failed to deploy: $total_failed workflows"
    
    if [[ ${#failed_workflows[@]} -gt 0 ]]; then
        echo ""
        echo "❌ Failed workflows:"
        for workflow in "${failed_workflows[@]}"; do
            echo "   • $workflow"
        done
    fi
}

# Test critical workflow (only for operational category)
test_critical_workflow() {
    # Only test critical workflow if operational category is being deployed
    if [[ "$CATEGORY" != "operational" && "$CATEGORY" != "all" ]]; then
        return
    fi
    
    if [[ "$DRY_RUN" == true ]]; then
        echo ""
        echo "🧪 DRY RUN: Would test real-time-business workflow"
        return
    fi
    
    echo ""
    echo "🧪 Step 3: Testing CRITICAL workflow (real-time-business)..."
    
    echo "Testing real-time-business workflow (revenue critical Events→Props)..."
    
    local execution_id
    execution_id=$(gcloud workflows run real-time-business --location=$REGION --format="value(name)" 2>/dev/null)
    
    if [[ -n "$execution_id" ]]; then
        echo "✅ Test execution started: $execution_id"
        echo "⏳ Waiting 45 seconds for completion..."
        sleep 45
        
        local status
        status=$(gcloud workflows executions describe "$execution_id" --location=$REGION --workflow=real-time-business --format="value(state)" 2>/dev/null)
        
        echo "📊 Execution status: $status"
        
        case "$status" in
            "SUCCEEDED")
                echo "🎉 CRITICAL workflow test PASSED!"
                echo "✅ Events→Props revenue chain working"
                ;;
            "FAILED")
                echo "🔴 CRITICAL workflow test FAILED!"
                echo "❌ Events→Props revenue chain BROKEN"
                
                # Get error details
                local error_msg
                error_msg=$(gcloud workflows executions describe "$execution_id" --location=$REGION --workflow=real-time-business --format="value(error.context)" 2>/dev/null)
                if [[ -n "$error_msg" ]]; then
                    echo "🔍 Error: $error_msg"
                fi
                ;;
            "ACTIVE")
                echo "⏳ Test still running. Check manually:"
                echo "gcloud workflows executions describe $execution_id --location=$REGION --workflow=real-time-business"
                ;;
            *)
                echo "❓ Unknown status: $status"
                ;;
        esac
    else
        echo "❌ Failed to start test execution"
    fi
}

# Show deployment status
show_deployment_status() {
    if [[ "$DRY_RUN" == true ]]; then
        echo ""
        echo "🔍 DRY RUN Complete - No actual deployments performed"
        return
    fi
    
    echo ""
    echo "📊 Step 4: Deployment Status & Next Steps"
    echo "========================================"
    
    echo ""
    echo "🚀 Currently Deployed Workflows:"
    gcloud workflows list --location=$REGION --format="table(name.basename(),state,revisionCreateTime)" 2>/dev/null
    
    # Category-specific next steps
    case "$CATEGORY" in
        "operational")
            echo ""
            echo "⏰ Current Workflow Schedulers:"
            gcloud scheduler jobs list --location=$REGION --filter="name ~ .*trigger" --format="table(name,schedule,state)" 2>/dev/null
            
            echo ""
            echo "🎯 CRITICAL Next Steps for operational workflows:"
            echo "1. 🔄 Update schedulers for 5-workflow system:"
            echo "   $SCRIPT_DIR/../scheduling/setup_workflow_schedulers.sh"
            echo ""
            echo "2. 📊 Monitor production system:"
            echo "   $SCRIPT_DIR/../monitoring/monitor_workflows.sh detailed"
            ;;
        "backfill")
            echo ""
            echo "🎯 Next Steps for backfill workflows:"
            echo "1. 🏃 Execute schedule collection:"
            echo "   gcloud workflows run collect-nba-historical-schedules --location=$REGION"
            echo ""
            echo "2. 📊 Monitor backfill execution:"
            echo "   gcloud workflows executions list collect-nba-historical-schedules --location=$REGION --limit=3"
            echo ""
            echo "3. ✅ Verify schedule collection results:"
            echo "   gcloud storage ls gs://nba-scraped-data/schedules/"
            ;;
        "admin")
            echo ""
            echo "🎯 Next Steps for admin workflows:"
            echo "1. 📊 Schedule system health checks"
            echo "2. 🔍 Configure data quality monitoring"
            ;;
        "all")
            echo ""
            echo "🎯 Next Steps for complete system:"
            echo "1. 🔄 Update operational schedulers if needed"
            echo "2. 🏃 Execute backfill foundation:"
            echo "   gcloud workflows run collect-nba-historical-schedules --location=$REGION"
            echo "3. 📊 Monitor all systems:"
            echo "   $SCRIPT_DIR/../monitoring/monitor_workflows.sh detailed"
            ;;
    esac
}

# Main execution
echo "Starting deployment for category: $CATEGORY..."

validate_workflows
deploy_workflows
test_critical_workflow  
show_deployment_status

echo ""
if [[ "$DRY_RUN" == true ]]; then
    echo "🔍 DRY RUN Complete - Review the output above"
    echo "Run without --dry-run to perform actual deployment"
else
    echo "🎉 Deployment complete for category: $CATEGORY!"
    
    # Category-specific success messages
    case "$CATEGORY" in
        "operational")
            echo ""
            echo "📈 Your operational system provides:"
            echo "• 🌅 Early Morning Final Check (6AM) - Last chance recovery"
            echo "• 🌄 Morning Operations (8AM) - Daily setup + Enhanced PBP recovery"  
            echo "• 💼 Real-Time Business (Every 2h) - CRITICAL Events→Props revenue"
            echo "• 🏀 Post-Game Collection (8PM & 11PM) - Core game data"
            echo "• 🌙 Late Night Recovery (2AM) - Enhanced PBP + comprehensive retry"
            ;;
        "backfill")
            echo ""
            echo "📈 Your backfill foundation is ready:"
            echo "• 🗓️  Historical schedule collection workflow deployed"
            echo "• 🎯 Ready to build complete 4-season historical dataset"
            echo "• 🚀 Next: Execute schedule collection to begin backfill"
            ;;
        "all")
            echo ""
            echo "📈 Complete workflow system deployed:"
            echo "• ✅ Operational workflows (production ready)"
            echo "• ✅ Backfill workflows (historical data foundation)"
            echo "• ✅ Admin workflows (system utilities)"
            ;;
    esac
fi

echo ""