#!/bin/bash
# SAVE TO: ~/code/nba-stats-scraper/bin/monitoring/monitor_workflows.sh

PROJECT_ID="nba-props-platform"
REGION="us-west2"

echo "📊 NBA Workflow Monitoring Dashboard"
echo "==================================="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Timestamp: $(date)"
echo ""

# Function to show workflow health
show_workflow_health() {
    local workflows=("real-time-business" "morning-operations" "game-day-evening" "post-game-analysis")
    
    echo "🏥 Workflow Health Summary"
    echo "========================="
    
    for workflow in "${workflows[@]}"; do
        echo ""
        echo "📊 $workflow:"
        
        # Get recent executions (last 5)
        local executions
        executions=$(gcloud workflows executions list $workflow --location=$REGION --limit=5 --format="value(state)" 2>/dev/null)
        
        if [[ -z "$executions" ]]; then
            echo "  ⚠️ No recent executions found"
            continue
        fi
        
        # Count execution states
        local success_count=0
        local failed_count=0
        local active_count=0
        local total_count=0
        
        while IFS= read -r state; do
            ((total_count++))
            case "$state" in
                "SUCCEEDED") ((success_count++)) ;;
                "FAILED") ((failed_count++)) ;;
                "ACTIVE") ((active_count++)) ;;
            esac
        done <<< "$executions"
        
        # Show health metrics
        echo "  📈 Recent executions (last 5): $total_count"
        echo "  ✅ Succeeded: $success_count"
        echo "  ❌ Failed: $failed_count"
        echo "  🔄 Active: $active_count"
        
        # Calculate success rate
        if [[ $total_count -gt 0 ]]; then
            local success_rate=$((success_count * 100 / total_count))
            echo "  📊 Success rate: $success_rate%"
            
            if [[ $success_rate -ge 80 ]]; then
                echo "  🟢 Health: Good"
            elif [[ $success_rate -ge 60 ]]; then
                echo "  🟡 Health: Warning"
            else
                echo "  🔴 Health: Critical"
            fi
        fi
        
        # Show latest execution details
        local latest_execution
        latest_execution=$(gcloud workflows executions list $workflow --location=$REGION --limit=1 --format="value(name)" 2>/dev/null)
        
        if [[ -n "$latest_execution" ]]; then
            local latest_state latest_start latest_end
            latest_state=$(gcloud workflows executions describe "$latest_execution" --location=$REGION --workflow=$workflow --format="value(state)" 2>/dev/null)
            latest_start=$(gcloud workflows executions describe "$latest_execution" --location=$REGION --workflow=$workflow --format="value(startTime)" 2>/dev/null)
            latest_end=$(gcloud workflows executions describe "$latest_execution" --location=$REGION --workflow=$workflow --format="value(endTime)" 2>/dev/null)
            
            echo "  🕐 Latest: $latest_state"
            echo "  📅 Started: $latest_start"
            if [[ -n "$latest_end" ]]; then
                echo "  🏁 Ended: $latest_end"
            fi
            
            # Show error details for failed executions
            if [[ "$latest_state" == "FAILED" ]]; then
                echo "  🔍 Error details:"
                local error_msg
                error_msg=$(gcloud workflows executions describe "$latest_execution" --location=$REGION --workflow=$workflow --format="value(error.context)" 2>/dev/null)
                if [[ -n "$error_msg" ]]; then
                    echo "    $error_msg"
                fi
            fi
        fi
    done
}

# Function to show scheduler status
show_scheduler_status() {
    echo ""
    echo "⏰ Workflow Scheduler Status"
    echo "==========================="
    
    local schedulers
    schedulers=$(gcloud scheduler jobs list --location=$REGION --filter="name ~ .*trigger" --format="table(name,schedule,state,lastAttemptTime,nextRunTime)" 2>/dev/null)
    
    if [[ -n "$schedulers" ]]; then
        echo "$schedulers"
    else
        echo "❌ No workflow schedulers found"
    fi
}

# Function to show recent activity
show_recent_activity() {
    echo ""
    echo "📈 Recent Activity (Last 24 Hours)"
    echo "=================================="
    
    # Get recent workflow logs
    echo "🔍 Recent workflow executions:"
    gcloud workflows executions list real-time-business --location=$REGION --limit=10 --format="table(name,state,startTime,endTime)" 2>/dev/null || echo "No recent executions found"
    
    echo ""
    echo "📋 Recent logs (errors and warnings):"
    gcloud logging read 'resource.type="cloud_workflow" AND (severity="ERROR" OR severity="WARNING")' \
        --limit=5 \
        --format="table(timestamp,severity,textPayload)" \
        --freshness=1d 2>/dev/null || echo "No recent errors/warnings found"
}

# Function to check business metrics
check_business_metrics() {
    echo ""
    echo "💼 Business Metrics Check"
    echo "========================"
    
    # Check Events -> Props dependency
    echo "🎯 Critical Business Flow (Events → Props):"
    
    # Get latest real-time-business execution
    local latest_execution
    latest_execution=$(gcloud workflows executions list real-time-business --location=$REGION --limit=1 --format="value(name)" 2>/dev/null)
    
    if [[ -n "$latest_execution" ]]; then
        local result
        result=$(gcloud workflows executions describe "$latest_execution" --location=$REGION --workflow=real-time-business --format="value(result)" 2>/dev/null)
        
        if [[ -n "$result" ]]; then
            echo "  📊 Latest execution result:"
            echo "$result" | sed 's/^/    /'
            
            # Check for revenue-critical indicators
            if echo "$result" | grep -q "CRITICAL_FAILURE"; then
                echo "  🔴 ALERT: Critical business failure detected!"
            elif echo "$result" | grep -q "PARTIAL_FAILURE"; then
                echo "  🟡 WARNING: Partial business failure (may impact revenue)"
            elif echo "$result" | grep -q "SUCCESS"; then
                echo "  🟢 GOOD: Business flow completed successfully"
            fi
        fi
    else
        echo "  ⚠️ No recent executions found for business flow check"
    fi
}

# Main execution functions
show_summary() {
    show_workflow_health
    show_scheduler_status
    check_business_metrics
}

show_detailed() {
    show_workflow_health
    show_scheduler_status
    show_recent_activity
    check_business_metrics
}

# Command line argument handling
case "${1:-summary}" in
    "summary"|"")
        show_summary
        ;;
    "detailed"|"detail")
        show_detailed
        ;;
    "health")
        show_workflow_health
        ;;
    "schedulers")
        show_scheduler_status
        ;;
    "business")
        check_business_metrics
        ;;
    "activity")
        show_recent_activity
        ;;
    *)
        echo "Usage: $0 [summary|detailed|health|schedulers|business|activity]"
        echo ""
        echo "Options:"
        echo "  summary    - Quick health overview (default)"
        echo "  detailed   - Full monitoring dashboard"
        echo "  health     - Workflow execution health only"
        echo "  schedulers - Scheduler status only"
        echo "  business   - Business metrics only"
        echo "  activity   - Recent activity only"
        exit 1
        ;;
esac

echo ""
echo "🔍 Quick Commands:"
echo "# Monitor specific workflow"
echo "gcloud workflows executions list WORKFLOW_NAME --location=$REGION"
echo ""
echo "# View workflow logs"
echo "gcloud logging read 'resource.type=\"cloud_workflow\"' --limit=10"
