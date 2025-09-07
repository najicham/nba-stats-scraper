#!/bin/bash
# SAVE TO: ~/code/nba-stats-scraper/bin/monitoring/monitor_workflows.sh
# Updated for NEW 5-workflow system with 12 daily executions

PROJECT_ID="nba-props-platform"
REGION="us-west2"

echo "📊 NBA Workflow Monitoring Dashboard (5-Workflow System)"
echo "========================================================"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Timestamp: $(date)"
echo "Target: 12 daily executions across 5 workflows"
echo ""

# Function to show workflow health for NEW 5-workflow system
show_workflow_health() {
    local workflows=(
        "early-morning-final-check"
        "morning-operations" 
        "real-time-business"
        "post-game-collection"
        "late-night-recovery"
    )
    
    echo "🏥 Workflow Health Summary (5-Workflow System)"
    echo "=============================================="
    
    local total_workflows=0
    local healthy_workflows=0
    local critical_issues=0
    
    for workflow in "${workflows[@]}"; do
        echo ""
        echo "📊 $workflow:"
        total_workflows=$((total_workflows + 1))
        
        # Get recent executions (last 10 for better analysis)
        local executions
        executions=$(gcloud workflows executions list $workflow --location=$REGION --limit=10 --format="value(state)" 2>/dev/null)
        
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
        echo "  📈 Recent executions (last 10): $total_count"
        echo "  ✅ Succeeded: $success_count"
        echo "  ❌ Failed: $failed_count"
        echo "  🔄 Active: $active_count"
        
        # Calculate success rate and health status
        local health_status="Unknown"
        local success_rate=0
        
        if [[ $total_count -gt 0 ]]; then
            success_rate=$((success_count * 100 / total_count))
            echo "  📊 Success rate: $success_rate%"
            
            # Determine health status with workflow-specific thresholds
            case "$workflow" in
                "real-time-business")
                    # CRITICAL workflow - higher threshold
                    if [[ $success_rate -ge 95 ]]; then
                        health_status="🟢 Excellent"
                        healthy_workflows=$((healthy_workflows + 1))
                    elif [[ $success_rate -ge 85 ]]; then
                        health_status="🟡 Warning"
                    else
                        health_status="🔴 CRITICAL"
                        critical_issues=$((critical_issues + 1))
                    fi
                    ;;
                *)
                    # Regular workflows - standard thresholds
                    if [[ $success_rate -ge 80 ]]; then
                        health_status="🟢 Good"
                        healthy_workflows=$((healthy_workflows + 1))
                    elif [[ $success_rate -ge 60 ]]; then
                        health_status="🟡 Warning"
                    else
                        health_status="🔴 Critical"
                        critical_issues=$((critical_issues + 1))
                    fi
                    ;;
            esac
        fi
        
        echo "  🏥 Health: $health_status"
        
        # Show latest execution details
        local latest_execution
        latest_execution=$(gcloud workflows executions list $workflow --location=$REGION --limit=1 --format="value(name)" 2>/dev/null)
        
        if [[ -n "$latest_execution" ]]; then
            local latest_state latest_start latest_end
            latest_state=$(gcloud workflows executions describe "$latest_execution" --location=$REGION --workflow=$workflow --format="value(state)" 2>/dev/null)
            latest_start=$(gcloud workflows executions describe "$latest_execution" --location=$REGION --workflow=$workflow --format="value(startTime)" 2>/dev/null)
            latest_end=$(gcloud workflows executions describe "$latest_execution" --location=$REGION --workflow=$workflow --format="value(endTime)" 2>/dev/null)
            
            echo "  🕐 Latest: $latest_state"
            if [[ -n "$latest_start" ]]; then
                echo "  📅 Started: $(echo "$latest_start" | cut -d'T' -f1) $(echo "$latest_start" | cut -d'T' -f2 | cut -d'.' -f1)"
            fi
            if [[ -n "$latest_end" ]]; then
                echo "  🏁 Ended: $(echo "$latest_end" | cut -d'T' -f1) $(echo "$latest_end" | cut -d'T' -f2 | cut -d'.' -f1)"
            fi
            
            # Show error details for failed executions
            if [[ "$latest_state" == "FAILED" ]]; then
                echo "  🔍 Error details:"
                local error_msg
                error_msg=$(gcloud workflows executions describe "$latest_execution" --location=$REGION --workflow=$workflow --format="value(error.context)" 2>/dev/null)
                if [[ -n "$error_msg" ]]; then
                    echo "    $(echo "$error_msg" | head -c 100)..."
                fi
            fi
        fi
        
        # Special alerts for critical workflows
        if [[ "$workflow" == "real-time-business" && $success_rate -lt 95 ]]; then
            echo "  🚨 REVENUE ALERT: Real-Time Business below 95% success rate!"
        fi
    done
    
    # Overall system health summary
    echo ""
    echo "🎯 Overall System Health:"
    echo "• Total workflows: $total_workflows"
    echo "• Healthy workflows: $healthy_workflows"
    echo "• Critical issues: $critical_issues"
    
    if [[ $critical_issues -eq 0 ]]; then
        echo "• 🟢 System Status: Healthy"
    elif [[ $critical_issues -eq 1 ]]; then
        echo "• 🟡 System Status: Warning (1 critical issue)"
    else
        echo "• 🔴 System Status: Critical ($critical_issues critical issues)"
    fi
}

# Function to show scheduler status for 12-execution system
show_scheduler_status() {
    echo ""
    echo "⏰ Workflow Scheduler Status (12 Daily Executions)"
    echo "=================================================="
    
    # Show current schedulers
    echo "📅 Active Schedulers:"
    local schedulers
    schedulers=$(gcloud scheduler jobs list --location=$REGION --filter="name ~ .*trigger" --format="csv[no-heading](name,schedule,state,lastAttemptTime,nextRunTime)" 2>/dev/null)
    
    if [[ -n "$schedulers" ]]; then
        echo "┌─────────────────────────────────┬─────────────────────┬─────────┬─────────────────────┬─────────────────────┐"
        echo "│            Scheduler            │      Schedule       │  State  │    Last Attempt     │     Next Run        │"
        echo "├─────────────────────────────────┼─────────────────────┼─────────┼─────────────────────┼─────────────────────┤"
        
        while IFS=',' read -r name schedule state last_attempt next_run; do
            # Clean up the values and format
            name=$(echo "$name" | sed 's/-trigger$//')
            schedule=$(echo "$schedule" | tr -d '"')
            state=$(echo "$state" | tr -d '"')
            last_attempt=$(echo "$last_attempt" | tr -d '"' | cut -d'T' -f2 | cut -d'.' -f1)
            next_run=$(echo "$next_run" | tr -d '"' | cut -d'T' -f2 | cut -d'.' -f1)
            
            printf "│ %-31s │ %-19s │ %-7s │ %-19s │ %-19s │\n" \
                   "$name" "$schedule" "$state" "$last_attempt" "$next_run"
        done <<< "$schedulers"
        
        echo "└─────────────────────────────────┴─────────────────────┴─────────┴─────────────────────┴─────────────────────┘"
    else
        echo "❌ No workflow schedulers found"
    fi
    
    # Show daily execution count
    echo ""
    echo "📊 Expected Daily Executions:"
    echo "• early-morning-final-check: 1 execution (6AM)"
    echo "• morning-operations: 1 execution (8AM)" 
    echo "• real-time-business: 7 executions (8AM, 10AM, 12PM, 2PM, 4PM, 6PM, 8PM)"
    echo "• post-game-collection: 2 executions (8PM, 11PM)"
    echo "• late-night-recovery: 1 execution (2AM)"
    echo "• 📈 Total: 12 executions per day"
}

# Function to show recent activity across all workflows
show_recent_activity() {
    echo ""
    echo "📈 Recent Activity (Last 24 Hours)"
    echo "=================================="
    
    # Count recent executions by workflow
    echo "🔍 Recent executions by workflow:"
    local workflows=(
        "early-morning-final-check"
        "morning-operations" 
        "real-time-business"
        "post-game-collection"
        "late-night-recovery"
    )
    
    local total_executions=0
    
    for workflow in "${workflows[@]}"; do
        local count
        count=$(gcloud workflows executions list $workflow --location=$REGION --filter="startTime>=$(date -d '24 hours ago' -Iseconds)" --format="value(name)" 2>/dev/null | wc -l)
        echo "  • $workflow: $count executions"
        total_executions=$((total_executions + count))
    done
    
    echo "  📊 Total recent executions: $total_executions"
    
    if [[ $total_executions -ge 12 ]]; then
        echo "  ✅ Good: Meeting daily execution target"
    elif [[ $total_executions -ge 8 ]]; then
        echo "  🟡 Warning: Below daily target but acceptable"
    else
        echo "  🔴 Critical: Significantly below daily target"
    fi
    
    # Show recent errors and warnings
    echo ""
    echo "📋 Recent logs (errors and warnings):"
    local recent_logs
    recent_logs=$(gcloud logging read 'resource.type="cloud_workflow" AND (severity="ERROR" OR severity="WARNING")' \
        --limit=5 \
        --format="csv[no-heading](timestamp,severity,textPayload)" \
        --freshness=1d 2>/dev/null)
    
    if [[ -n "$recent_logs" ]]; then
        echo "┌─────────────────────┬──────────┬────────────────────────────────────────────────┐"
        echo "│      Timestamp      │ Severity │                   Message                      │"
        echo "├─────────────────────┼──────────┼────────────────────────────────────────────────┤"
        
        while IFS=',' read -r timestamp severity message; do
            # Clean and format
            timestamp=$(echo "$timestamp" | tr -d '"' | cut -d'T' -f2 | cut -d'.' -f1)
            severity=$(echo "$severity" | tr -d '"')
            message=$(echo "$message" | tr -d '"' | head -c 46)
            
            printf "│ %-19s │ %-8s │ %-46s │\n" "$timestamp" "$severity" "$message"
        done <<< "$recent_logs"
        
        echo "└─────────────────────┴──────────┴────────────────────────────────────────────────┘"
    else
        echo "✅ No recent errors or warnings found"
    fi
}

# Function to check business metrics and revenue protection
check_business_metrics() {
    echo ""
    echo "💼 Business Metrics & Revenue Protection"
    echo "======================================="
    
    # Check Events → Props dependency (CRITICAL for revenue)
    echo "🎯 CRITICAL Business Flow Analysis (Events → Props):"
    
    # Get recent real-time-business executions
    local recent_executions
    recent_executions=$(gcloud workflows executions list real-time-business --location=$REGION --limit=7 --format="value(name)" 2>/dev/null)
    
    if [[ -n "$recent_executions" ]]; then
        local success_count=0
        local total_count=0
        
        echo "  📊 Analyzing last 7 Real-Time Business executions..."
        
        while IFS= read -r execution; do
            if [[ -n "$execution" ]]; then
                total_count=$((total_count + 1))
                local state
                state=$(gcloud workflows executions describe "$execution" --location=$REGION --workflow=real-time-business --format="value(state)" 2>/dev/null)
                
                if [[ "$state" == "SUCCEEDED" ]]; then
                    success_count=$((success_count + 1))
                fi
            fi
        done <<< "$recent_executions"
        
        local success_rate=0
        if [[ $total_count -gt 0 ]]; then
            success_rate=$((success_count * 100 / total_count))
        fi
        
        echo "  📈 Success rate: $success_rate% ($success_count/$total_count)"
        
        # Revenue protection assessment
        if [[ $success_rate -ge 95 ]]; then
            echo "  🟢 REVENUE STATUS: Protected (excellent Events→Props success rate)"
        elif [[ $success_rate -ge 85 ]]; then
            echo "  🟡 REVENUE STATUS: At Risk (Events→Props success rate below optimal)"
        else
            echo "  🔴 REVENUE STATUS: CRITICAL (Events→Props dependency failing)"
            echo "  🚨 IMMEDIATE ACTION REQUIRED: Revenue generation may be blocked"
        fi
        
        # Check latest execution for detailed status
        local latest_execution
        latest_execution=$(echo "$recent_executions" | head -n1)
        
        if [[ -n "$latest_execution" ]]; then
            local result
            result=$(gcloud workflows executions describe "$latest_execution" --location=$REGION --workflow=real-time-business --format="value(result)" 2>/dev/null)
            
            if [[ -n "$result" ]]; then
                echo "  🔍 Latest execution analysis:"
                
                # Parse result for business indicators
                if echo "$result" | grep -q "CRITICAL_FAILURE"; then
                    echo "    🔴 ALERT: Critical business failure detected!"
                elif echo "$result" | grep -q "PARTIAL_FAILURE"; then
                    echo "    🟡 WARNING: Partial business failure (may impact revenue)"
                elif echo "$result" | grep -q "SUCCESS"; then
                    echo "    🟢 GOOD: Business flow completed successfully"
                fi
                
                # Check Events→Props dependency status
                if echo "$result" | grep -q "events_status.*success"; then
                    echo "    ✅ Events API: Working"
                else
                    echo "    ❌ Events API: Failed (blocks Props)"
                fi
                
                if echo "$result" | grep -q "props_status.*success"; then
                    echo "    ✅ Props API: Working"
                elif echo "$result" | grep -q "props_status.*skipped"; then
                    echo "    ⏭️ Props API: Skipped (due to Events failure)"
                else
                    echo "    ❌ Props API: Failed"
                fi
            fi
        fi
    else
        echo "  ⚠️ No recent Real-Time Business executions found"
        echo "  🔴 REVENUE STATUS: UNKNOWN (no execution data)"
    fi
    
    # Check status file tracking (foundation for smart recovery)
    echo ""
    echo "📁 Status Tracking Analysis:"
    local today=$(date +%Y-%m-%d)
    local status_files
    status_files=$(gsutil ls "gs://nba-props-status/workflow-status/$today/" 2>/dev/null | wc -l)
    
    echo "  📊 Status files today: $status_files"
    
    if [[ $status_files -gt 5 ]]; then
        echo "  ✅ Status tracking: Active (foundation for smart recovery ready)"
    elif [[ $status_files -gt 0 ]]; then
        echo "  🟡 Status tracking: Partial (some workflows writing status)"
    else
        echo "  ❌ Status tracking: Not working (may need investigation)"
    fi
}

# Main execution functions with different detail levels
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

show_quick_status() {
    echo "🚀 Quick System Status:"
    
    # Count healthy workflows
    local workflows=("early-morning-final-check" "morning-operations" "real-time-business" "post-game-collection" "late-night-recovery")
    local healthy=0
    
    for workflow in "${workflows[@]}"; do
        local latest_state
        latest_state=$(gcloud workflows executions list $workflow --location=$REGION --limit=1 --format="value(state)" 2>/dev/null)
        if [[ "$latest_state" == "SUCCEEDED" ]]; then
            healthy=$((healthy + 1))
        fi
    done
    
    echo "  📊 Healthy workflows: $healthy/5"
    
    # Check critical workflow
    local rtb_state
    rtb_state=$(gcloud workflows executions list real-time-business --location=$REGION --limit=1 --format="value(state)" 2>/dev/null)
    echo "  💼 Real-Time Business (critical): $rtb_state"
    
    # Check schedulers
    local active_schedulers
    active_schedulers=$(gcloud scheduler jobs list --location=$REGION --filter="name ~ .*trigger AND state=ENABLED" --format="value(name)" 2>/dev/null | wc -l)
    echo "  ⏰ Active schedulers: $active_schedulers/5"
    
    if [[ $healthy -eq 5 && "$rtb_state" == "SUCCEEDED" && $active_schedulers -eq 5 ]]; then
        echo "  🟢 Overall: System Healthy"
    else
        echo "  🟡 Overall: Issues Detected - run detailed monitoring"
    fi
}

# Command line argument handling
case "${1:-summary}" in
    "quick"|"q")
        show_quick_status
        ;;
    "summary"|"")
        show_summary
        ;;
    "detailed"|"detail"|"d")
        show_detailed
        ;;
    "health"|"h")
        show_workflow_health
        ;;
    "schedulers"|"s")
        show_scheduler_status
        ;;
    "business"|"b")
        check_business_metrics
        ;;
    "activity"|"a")
        show_recent_activity
        ;;
    *)
        echo "Usage: $0 [quick|summary|detailed|health|schedulers|business|activity]"
        echo ""
        echo "Options:"
        echo "  quick      - Fast system overview (q)"
        echo "  summary    - Standard health overview (default)"
        echo "  detailed   - Full monitoring dashboard (d)"
        echo "  health     - Workflow execution health only (h)"
        echo "  schedulers - Scheduler status only (s)"
        echo "  business   - Business metrics & revenue protection (b)"
        echo "  activity   - Recent activity analysis (a)"
        exit 1
        ;;
esac

echo ""
echo "🔍 Quick Commands for Deeper Analysis:"
echo "# Monitor specific workflow"
echo "gcloud workflows executions list WORKFLOW_NAME --location=$REGION --limit=10"
echo ""
echo "# Check recent logs"
echo "gcloud logging read 'resource.type=\"cloud_workflow\"' --limit=10"
echo ""
echo "# Status file analysis"
echo "gsutil ls gs://nba-props-status/workflow-status/\$(date +%Y-%m-%d)/"
echo ""
echo "# Business-critical workflow focus"
echo "gcloud workflows executions describe \$(gcloud workflows executions list real-time-business --location=$REGION --limit=1 --format='value(name)') --location=$REGION --workflow=real-time-business"
