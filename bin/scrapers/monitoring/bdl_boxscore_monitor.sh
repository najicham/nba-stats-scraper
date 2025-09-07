#!/bin/bash
# File: bin/backfill/bdl_boxscore_monitor.sh
# Purpose: OPTIMIZED monitoring for Ball Don't Lie Boxscore backfill process  
# Usage: ./bin/backfill/bdl_boxscore_monitor.sh [command] [options]

set -e

PROJECT="nba-props-platform"
REGION="us-west2"
JOB_NAME="bdl-boxscore-backfill"

# Performance settings
TIMEOUT_SHORT=15  # For quick operations
TIMEOUT_LONG=30   # For heavy operations
CACHE_DIR="/tmp/bdl_monitor_cache"
CACHE_TTL=300     # 5 minutes cache

# Expected totals (estimated from 4 seasons)
ESTIMATED_TOTAL_DATES=850  # Rough estimate of unique game dates

# GCS bucket paths
GCS_DATA_PATH="gs://nba-scraped-data/ball-dont-lie/box-scores"

# Seasons to include in backfill monitoring
SEASONS_TO_MONITOR=("2021-22" "2022-23" "2023-24" "2024-25")

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

# Initialize cache directory
mkdir -p "$CACHE_DIR"

print_header() {
    echo -e "${CYAN}================================================${NC}"
    echo -e "${CYAN}🏀 BALL DON'T LIE BOXSCORE BACKFILL MONITOR${NC}"
    echo -e "${CYAN}================================================${NC}"
    echo -e "Time: $(date)"
    echo ""
}

# OPTIMIZED: Fast GCS operation with timeout and caching
gcs_operation_safe() {
    local operation="$1"
    local cache_key="$2"
    local cache_file="$CACHE_DIR/${cache_key}.cache"
    local cache_time_file="$CACHE_DIR/${cache_key}.time"
    
    # Check cache validity
    if [[ -f "$cache_file" && -f "$cache_time_file" ]]; then
        local cache_time=$(cat "$cache_time_file" 2>/dev/null || echo "0")
        local current_time=$(date +%s)
        local age=$((current_time - cache_time))
        
        if [[ $age -lt $CACHE_TTL ]]; then
            # Use cached result
            cat "$cache_file"
            return 0
        fi
    fi
    
    # Execute operation with timeout
    local result=""
    if result=$(timeout $TIMEOUT_LONG bash -c "$operation" 2>/dev/null); then
        # Cache successful result
        echo "$result" > "$cache_file"
        date +%s > "$cache_time_file"
        echo "$result"
        return 0
    else
        # Operation failed, try to use stale cache
        if [[ -f "$cache_file" ]]; then
            echo -e "  ${YELLOW}⚠️  Using cached data (operation timed out)${NC}" >&2
            cat "$cache_file"
            return 0
        else
            return 1
        fi
    fi
}

# OPTIMIZED: Fast date counting using directory sampling
count_gcs_dates_fast() {
    local cache_key="bdl_date_count"
    
    echo -e "  ${BLUE}🔍 Counting processed dates...${NC}" >&2
    
    # Try cached count first
    local cached_count=$(gcs_operation_safe "echo 'cached'" "$cache_key" 2>/dev/null)
    if [[ -n "$cached_count" && "$cached_count" != "cached" ]]; then
        echo "$cached_count"
        return 0
    fi
    
    # Count date directories
    local date_dirs=""
    if date_dirs=$(timeout $TIMEOUT_SHORT gcloud storage ls "$GCS_DATA_PATH/" 2>/dev/null); then
        local total_dates=$(echo "$date_dirs" | wc -l | tr -d ' ')
        
        echo -e "  ${GREEN}📊 Found $total_dates processed dates${NC}" >&2
        echo "$total_dates" > "$CACHE_DIR/${cache_key}.cache"
        date +%s > "$CACHE_DIR/${cache_key}.time"
        echo "$total_dates"
        return 0
    fi
    
    echo -e "  ${YELLOW}⚠️  Could not count dates, using estimate${NC}" >&2
    echo "0"
}

# OPTIMIZED: Fast progress calculation for BDL boxscores
calculate_gcs_progress_fast() {
    echo -e "${BLUE}📊 Progress Analysis (BDL Boxscores):${NC}"
    echo ""
    
    # Get date count (cached/estimated)
    local processed_dates=$(count_gcs_dates_fast)
    
    if [[ "$processed_dates" -gt 0 ]]; then
        # Calculate progress percentage against estimated total
        local progress_pct=$((processed_dates * 100 / ESTIMATED_TOTAL_DATES))
        local remaining=$((ESTIMATED_TOTAL_DATES - processed_dates))
        
        echo -e "${PURPLE}🎯 BDL BOXSCORE BACKFILL PROGRESS:${NC}"
        if [[ $progress_pct -gt 100 ]]; then
            echo -e "  📅 Processed dates: ${GREEN}$processed_dates${NC} / $ESTIMATED_TOTAL_DATES (${GREEN}COMPLETE + ${progress_pct}%${NC}) ✅"
            echo -e "  ${GREEN}✨ Backfill COMPLETE!${NC}"
        else
            echo -e "  📅 Processed dates: ${GREEN}$processed_dates${NC} / $ESTIMATED_TOTAL_DATES (${YELLOW}$progress_pct%${NC}) - $remaining remaining"
        fi
        
        # Calculate ETA if running
        local running_exec=$(find_running_execution)
        if [[ -n "$running_exec" && $remaining -gt 0 ]]; then
            local start_time=$(timeout $TIMEOUT_SHORT gcloud run jobs executions describe "$running_exec" \
                --region=$REGION \
                --format="value(metadata.creationTimestamp)" 2>/dev/null)
            
            if [[ -n "$start_time" ]]; then
                local start_epoch=$(parse_iso_timestamp "$start_time")
                local current_epoch=$(date +%s)
                local elapsed_seconds=$((current_epoch - start_epoch))
                
                if [[ $elapsed_seconds -gt 0 && $processed_dates -gt 0 ]]; then
                    local rate=$(echo "scale=1; $processed_dates * 60 / $elapsed_seconds" | bc -l 2>/dev/null || echo "0")
                    local eta_minutes=$(echo "scale=1; $remaining / $rate" | bc -l 2>/dev/null || echo "0")
                    echo -e "  ⏱️  Rate: ${CYAN}$rate dates/min${NC}, ETA: ${PURPLE}$eta_minutes minutes${NC}"
                fi
            fi
        fi
    else
        echo -e "  ${YELLOW}No dates processed yet${NC}"
    fi
}

# OPTIMIZED: Super fast quick command for BDL
cmd_quick_optimized() {
    # Check running status (fast)
    local running_exec=""
    if running_exec=$(timeout $TIMEOUT_SHORT gcloud run jobs executions list \
        --job=$JOB_NAME \
        --region=$REGION \
        --format="value(metadata.name)" \
        --limit=1 2>/dev/null); then
        
        if [[ -n "$running_exec" ]]; then
            # Check if job is actually running or stuck
            local execution_check=$(find_running_execution)
            
            if [[ "$execution_check" =~ ^STUCK: ]]; then
                local stuck_name=$(echo "$execution_check" | cut -d: -f2)
                local stuck_hours=$(echo "$execution_check" | cut -d: -f3)
                echo "Status: STUCK ($stuck_name) - ${stuck_hours}h elapsed"
                echo "⚠️  Job appears stuck - consider stopping it manually:"
                echo "   gcloud run jobs executions cancel $stuck_name --region=$REGION"
                return 0
            elif [[ -n "$execution_check" ]]; then
                # Get runtime info
                local start_time=""
                if start_time=$(timeout $TIMEOUT_SHORT gcloud run jobs executions describe "$execution_check" \
                    --region=$REGION \
                    --format="value(metadata.creationTimestamp)" 2>/dev/null); then
                    
                    local elapsed=$(calculate_elapsed_time "$start_time")
                    echo "Status: RUNNING ($execution_check)${elapsed:+ ($elapsed elapsed)}"
                else
                    echo "Status: RUNNING ($execution_check)"
                fi
            else
                echo "Status: NO ACTIVE JOBS"
            fi
        else
            echo "Status: NO ACTIVE JOBS"
        fi
    else
        echo "Status: UNKNOWN (timeout)"
    fi
    
    # Fast progress check using cached data
    local cache_file="$CACHE_DIR/quick_progress.cache"
    local cache_time_file="$CACHE_DIR/quick_progress.time"
    
    # Use cached progress if recent
    if [[ -f "$cache_file" && -f "$cache_time_file" ]]; then
        local cache_time=$(cat "$cache_time_file" 2>/dev/null || echo "0")
        local current_time=$(date +%s)
        local age=$((current_time - cache_time))
        
        if [[ $age -lt 60 ]]; then  # 1 minute cache for quick command
            cat "$cache_file"
            echo "Note: Using cached progress (${age}s old)"
            return 0
        fi
    fi
    
    # Get fresh progress and cache it
    local processed_dates=$(count_gcs_dates_fast)
    if [[ "$processed_dates" -gt 0 ]]; then
        local progress_pct=$((processed_dates * 100 / ESTIMATED_TOTAL_DATES))
        
        local progress_info="Progress: $processed_dates / $ESTIMATED_TOTAL_DATES dates ($progress_pct% complete)"
        
        echo "$progress_info"
        echo "$progress_info" > "$cache_file"
        date +%s > "$cache_time_file"
    else
        echo "Progress: Data not available yet"
    fi
    
    # Show latest activity (quick check)
    local latest=""
    if latest=$(timeout $TIMEOUT_SHORT gcloud logging read \
        "resource.type=cloud_run_job AND textPayload:\"Downloaded\"" \
        --limit=1 \
        --format="value(textPayload)" \
        --project=$PROJECT \
        --freshness=10m 2>/dev/null); then
        echo "$latest"
    fi
}

# Job management commands (same pattern as gamebook monitor)
cmd_cancel_stuck() {
    echo -e "${BLUE}🔍 Checking for stuck jobs...${NC}"
    
    local execution_check=$(find_running_execution)
    
    if [[ "$execution_check" =~ ^STUCK: ]]; then
        local stuck_name=$(echo "$execution_check" | cut -d: -f2)
        local stuck_hours=$(echo "$execution_check" | cut -d: -f3)
        
        echo -e "${RED}🚨 Found stuck job: $stuck_name (${stuck_hours}h elapsed)${NC}"
        echo -e "${YELLOW}Cancelling stuck job...${NC}"
        
        if gcloud run jobs executions cancel "$stuck_name" --region=$REGION --quiet; then
            echo -e "${GREEN}✅ Successfully cancelled stuck job${NC}"
            echo -e "${BLUE}💡 You can now restart with:${NC}"
            echo -e "   ${CYAN}gcloud run jobs execute $JOB_NAME --region=$REGION${NC}"
        else
            echo -e "${RED}❌ Failed to cancel job${NC}"
        fi
    elif [[ -n "$execution_check" ]]; then
        echo -e "${GREEN}✅ Current job appears to be running normally${NC}"
        echo -e "   Job: $execution_check"
    else
        echo -e "${YELLOW}ℹ️  No active jobs found${NC}"
    fi
}

cmd_restart_job() {
    echo -e "${BLUE}🔄 Restarting BDL boxscore backfill job...${NC}"
    
    # Check if there's a running job first
    local execution_check=$(find_running_execution)
    
    if [[ -n "$execution_check" ]]; then
        if [[ "$execution_check" =~ ^STUCK: ]]; then
            echo -e "${YELLOW}⚠️  Stuck job detected, cancelling first...${NC}"
            cmd_cancel_stuck
            echo ""
        else
            echo -e "${YELLOW}⚠️  Job is currently running. Cancel it first? (y/N)${NC}"
            read -r response
            if [[ "$response" =~ ^[Yy] ]]; then
                local job_name=$(echo "$execution_check" | cut -d: -f1)
                gcloud run jobs executions cancel "$job_name" --region=$REGION --quiet
                echo -e "${GREEN}✅ Cancelled running job${NC}"
            else
                echo -e "${YELLOW}Aborted - job still running${NC}"
                return 1
            fi
        fi
    fi
    
    echo -e "${BLUE}🚀 Starting new execution...${NC}"
    if gcloud run jobs execute $JOB_NAME --region=$REGION; then
        echo -e "${GREEN}✅ Job started successfully${NC}"
        echo -e "${BLUE}💡 Monitor with: ./bin/backfill/bdl_boxscore_monitor.sh watch${NC}"
    else
        echo -e "${RED}❌ Failed to start job${NC}"
    fi
}

# Clear cache function
cmd_clear_cache() {
    echo -e "${BLUE}🧹 Clearing monitor cache...${NC}"
    rm -rf "$CACHE_DIR"
    mkdir -p "$CACHE_DIR"
    echo -e "${GREEN}✅ Cache cleared${NC}"
}

# Helper functions (same as gamebook monitor)
parse_iso_timestamp() {
    local iso_time="$1"
    
    if [[ -n "$iso_time" ]]; then
        local clean_time=$(echo "$iso_time" | sed 's/\.[0-9]*Z$/Z/')
        local epoch=""
        
        # Try different parsing methods
        epoch=$(TZ=UTC date -j -f "%Y-%m-%dT%H:%M:%SZ" "$clean_time" "+%s" 2>/dev/null || echo "")
        
        if [[ -z "$epoch" ]]; then
            epoch=$(date -d "$clean_time" +%s 2>/dev/null || echo "")
        fi
        
        if [[ -z "$epoch" ]]; then
            local alt_time=$(echo "$clean_time" | sed 's/Z$/+0000/')
            epoch=$(date -j -f "%Y-%m-%dT%H:%M:%S%z" "$alt_time" "+%s" 2>/dev/null || echo "")
        fi
        
        if [[ -n "$epoch" && "$epoch" -gt 1700000000 ]]; then
            echo "$epoch"
        fi
    fi
}

calculate_elapsed_time() {
    local start_time="$1"
    local start_epoch=$(parse_iso_timestamp "$start_time")
    local current_epoch=$(date +%s)
    
    if [[ -n "$start_epoch" && "$start_epoch" -gt 0 ]]; then
        local duration_seconds=$((current_epoch - start_epoch))
        local duration_hours=$((duration_seconds / 3600))
        local duration_minutes=$(((duration_seconds % 3600) / 60))
        echo "${duration_hours}h ${duration_minutes}m"
    fi
}

find_running_execution() {
    local executions=""
    if executions=$(timeout $TIMEOUT_SHORT gcloud run jobs executions list \
        --job=$JOB_NAME \
        --region=$REGION \
        --format="value(metadata.name)" \
        --limit=3 2>/dev/null); then
        
        while IFS= read -r exec_name; do
            if [[ -n "$exec_name" ]]; then
                # Get detailed status info
                local status_info=""
                if status_info=$(timeout $TIMEOUT_SHORT gcloud run jobs executions describe "$exec_name" \
                    --region=$REGION \
                    --format="value(status.conditions[0].type,metadata.creationTimestamp)" 2>/dev/null); then
                    
                    local status=$(echo "$status_info" | cut -f1)
                    local creation_time=$(echo "$status_info" | cut -f2)
                    
                    # Check if genuinely running
                    if [[ "$status" != "Succeeded" && "$status" != "Completed" && "$status" != "Failed" ]]; then
                        # BDL jobs should complete in ~30 minutes, so >2 hours = stuck
                        if [[ -n "$creation_time" ]]; then
                            local start_epoch=$(parse_iso_timestamp "$creation_time")
                            local current_epoch=$(date +%s)
                            local elapsed_hours=$(( (current_epoch - start_epoch) / 3600 ))
                            
                            if [[ $elapsed_hours -gt 2 ]]; then
                                echo "STUCK:$exec_name:$elapsed_hours"
                                return 0
                            fi
                        fi
                        
                        echo "$exec_name"
                        return 0
                    fi
                fi
            fi
        done <<< "$executions"
    fi
    
    return 1
}

get_recent_logs() {
    local limit=${1:-20}
    timeout $TIMEOUT_LONG gcloud logging read \
        "resource.type=cloud_run_job AND (textPayload:\"Downloaded\" OR textPayload:\"Progress\" OR textPayload:\"❌\")" \
        --limit=$limit \
        --format="value(timestamp,textPayload)" \
        --project=$PROJECT \
        --freshness=30m 2>/dev/null | head -$limit
}

show_execution_status() {
    echo -e "${BLUE}🏃 Recent Executions:${NC}"
    
    # Get execution data for custom table with elapsed time
    local executions_data=""
    if executions_data=$(timeout $TIMEOUT_LONG gcloud run jobs executions list \
        --job=$JOB_NAME \
        --region=$REGION \
        --limit=5 \
        --format="value(metadata.name,status.conditions[0].type,metadata.creationTimestamp,status.completionTime)" 2>/dev/null); then
        
        # Custom table header
        local timezone=$(date +%Z)
        printf "%-32s %-12s %-20s %s\n" "EXECUTION" "STATUS" "CREATED ($timezone)" "ELAPSED"
        printf "%-32s %-12s %-20s %s\n" "$(printf '%*s' 32 '' | tr ' ' '-')" "$(printf '%*s' 12 '' | tr ' ' '-')" "$(printf '%*s' 20 '' | tr ' ' '-')" "$(printf '%*s' 10 '' | tr ' ' '-')"
        
        # Process each execution
        while IFS=$'\t' read -r exec_name status created completed; do
            if [[ -n "$exec_name" ]]; then
                # Calculate elapsed time
                local elapsed_display="--"
                if [[ -n "$created" ]]; then
                    local start_epoch=$(parse_iso_timestamp "$created")
                    if [[ -n "$start_epoch" ]]; then
                        local end_epoch=""
                        if [[ -n "$completed" && "$completed" != "null" ]]; then
                            # Completed job - use completion time
                            end_epoch=$(parse_iso_timestamp "$completed")
                        else
                            # Running job - use current time
                            end_epoch=$(date +%s)
                        fi
                        
                        if [[ -n "$end_epoch" ]]; then
                            local duration_seconds=$((end_epoch - start_epoch))
                            local duration_hours=$((duration_seconds / 3600))
                            local duration_minutes=$(((duration_seconds % 3600) / 60))
                            elapsed_display="${duration_hours}h ${duration_minutes}m"
                        fi
                    fi
                fi
                
                # Format created timestamp for display
                local created_display="--"
                if [[ -n "$created" ]]; then
                    local start_epoch=$(parse_iso_timestamp "$created")
                    if [[ -n "$start_epoch" ]]; then
                        created_display=$(date -r "$start_epoch" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "$created")
                    else
                        created_display=$(echo "$created" | sed 's/T/ /' | sed 's/\.[0-9]*Z$//')
                    fi
                fi
                
                # Print table row
                printf "%-32s %-12s %-20s %s\n" "$exec_name" "$status" "$created_display" "$elapsed_display"
            fi
        done <<< "$executions_data"
        
        echo ""
        local execution_check=$(find_running_execution)
        
        if [[ "$execution_check" =~ ^STUCK: ]]; then
            local stuck_name=$(echo "$execution_check" | cut -d: -f2)
            local stuck_hours=$(echo "$execution_check" | cut -d: -f3)
            echo -e "${RED}🚨 STUCK JOB DETECTED: $stuck_name (${stuck_hours}h elapsed)${NC}"
            echo -e "${YELLOW}⚠️  Recommendation: Cancel the stuck job and restart:${NC}"
            echo -e "   ${CYAN}gcloud run jobs executions cancel $stuck_name --region=$REGION${NC}"
        elif [[ -n "$execution_check" ]]; then
            echo -e "${GREEN}🔥 Currently Running: $execution_check${NC}"
        else
            # Check if latest job completed successfully
            if echo "$executions_data" | head -1 | grep -q -E "(Completed|Succeeded)"; then
                echo -e "${GREEN}✅ Latest execution completed successfully${NC}"
            else
                echo -e "${YELLOW}No currently running executions detected${NC}"
            fi
        fi
    else
        echo -e "${RED}❌ Failed to get execution status (timeout)${NC}"
    fi
}

check_activity_health() {
    echo -e "${BLUE}🏥 Activity Health:${NC}"
    
    local recent_logs=""
    if recent_logs=$(get_recent_logs 10 | cut -f2 2>/dev/null); then
        if [[ -n "$recent_logs" ]]; then
            local recent_downloads=$(echo "$recent_logs" | grep "✅ Downloaded" | wc -l | tr -d ' ')
            local recent_errors=$(echo "$recent_logs" | grep -E "(❌|ERROR)" | wc -l | tr -d ' ')
            
            echo -e "  Recent activity (last 10 logs):"
            echo -e "    Downloads: ${GREEN}$recent_downloads${NC}"
            echo -e "    Errors: ${RED}$recent_errors${NC}"
            
            if [[ $recent_downloads -gt 0 ]]; then
                echo -e "  ${GREEN}✅ Active - Downloads in progress${NC}"
            elif [[ $recent_errors -gt 0 ]]; then
                echo -e "  ${YELLOW}⚠️  Issues detected${NC}"
            else
                echo -e "  ${YELLOW}⚠️  No recent download activity${NC}"
            fi
        else
            echo -e "  ${YELLOW}⚠️  No recent logs found${NC}"
        fi
    else
        echo -e "  ${RED}❌ Failed to get recent logs (timeout)${NC}"
    fi
}

# Command implementations
cmd_status() {
    print_header
    show_execution_status
    echo ""
    check_activity_health
    echo ""
    
    echo -e "${BLUE}📄 Latest Activity:${NC}"
    local recent=""
    if recent=$(get_recent_logs 3 | cut -f2 2>/dev/null); then
        if [[ -n "$recent" ]]; then
            echo "$recent" | sed 's/^/  /'
        else
            echo -e "  ${YELLOW}No recent activity${NC}"
        fi
    else
        echo -e "  ${RED}Failed to get recent logs${NC}"
    fi
}

cmd_progress() {
    print_header
    calculate_gcs_progress_fast
}

cmd_watch() {
    echo -e "${GREEN}Starting continuous monitoring (Ctrl+C to stop)...${NC}"
    
    while true; do
        clear
        cmd_quick_optimized
        echo ""
        echo -e "${YELLOW}Next update in 30 seconds... (Ctrl+C to stop)${NC}"
        sleep 30  # Faster updates since BDL job is quicker
    done
}

cmd_logs() {
    local count=${1:-20}
    print_header
    echo -e "${BLUE}📄 Recent Logs (last $count):${NC}"
    local logs=""
    if logs=$(get_recent_logs $count); then
        echo "$logs" | sed 's/^/  /'
    else
        echo -e "  ${RED}Failed to get logs${NC}"
    fi
}

show_usage_optimized() {
    echo "Usage: $0 [command]"
    echo ""
    echo "OPTIMIZED Commands (fast, cached):"
    echo "  quick          - Super fast status with cached progress"
    echo "  status         - Status overview with timeouts"
    echo "  progress       - Progress analysis with smart caching"
    echo "  clear-cache    - Clear all cached data"
    echo ""
    echo "Job Management:"
    echo "  cancel-stuck   - Find and cancel stuck jobs (>2h runtime)"
    echo "  restart        - Restart the backfill job (cancels current if needed)"
    echo ""
    echo "Standard Commands:"
    echo "  watch          - Continuous monitoring (30s updates)"
    echo "  logs [N]       - Show last N log lines"
    echo ""
    echo "BDL-Specific Notes:"
    echo "  - Expected duration: 15-20 minutes for all 4 seasons"
    echo "  - Rate limit: 600 req/min (much faster than gamebook)"
    echo "  - Data structure: One call per date (not per game)"
    echo "  - Estimated ~850 unique game dates across 4 seasons"
}

# Main command handling
case "${1:-quick}" in
    "status")
        cmd_status
        ;;
    "progress")
        cmd_progress
        ;;
    "watch")
        cmd_watch
        ;;
    "quick"|"")
        cmd_quick_optimized
        ;;
    "clear-cache")
        cmd_clear_cache
        ;;
    "cancel-stuck")
        cmd_cancel_stuck
        ;;
    "restart")
        cmd_restart_job
        ;;
    "logs")
        cmd_logs "$2"
        ;;
    "help"|"-h"|"--help")
        show_usage_optimized
        ;;
    *)
        echo "Unknown command: $1"
        show_usage_optimized
        exit 1
        ;;
esac