#!/bin/bash
# FILE: bin/scrapers/monitoring/nbac_referee_assignments_monitor.sh
# Purpose: Monitoring for NBA Referee Assignments backfill process with concurrent job support
# Usage: ./bin/scrapers/monitoring/nbac_referee_assignments_monitor.sh [command] [options]

set -euo pipefail

PROJECT="nba-props-platform"
REGION="us-west2"
JOB_NAME="nba-referee-assignments-backfill"

# Performance settings
TIMEOUT_SHORT=15  # For quick operations
TIMEOUT_LONG=30   # For heavy operations
CACHE_DIR="/tmp/nba_referee_monitor_cache"
CACHE_TTL=300     # 5 minutes cache

# Expected totals based on 4 seasons (approximate dates)
EXPECTED_TOTAL_DATES=1400  # ~350 dates per season across 4 seasons
FALLBACK_TOTAL_DATES=1400  

# GCS bucket paths
GCS_DATA_PATH="gs://nba-scraped-data/nba-com/referee-assignments"

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
    echo -e "${CYAN}🏀 NBA REFEREE ASSIGNMENTS MONITOR v1.0${NC}"
    echo -e "${CYAN}================================================${NC}"
    echo -e "Time: $(date)"
    echo ""
}

# Fast GCS operation with timeout and caching
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

# Count JSON files directly with better performance
count_json_files_fast() {
    local cache_key="json_count"
    local cache_file="$CACHE_DIR/${cache_key}.cache"
    local cache_time_file="$CACHE_DIR/${cache_key}.time"
    
    # Use 60-second cache for JSON count
    if [[ -f "$cache_file" && -f "$cache_time_file" ]]; then
        local cache_time=$(cat "$cache_time_file" 2>/dev/null || echo "0")
        local current_time=$(date +%s)
        local age=$((current_time - cache_time))
        
        if [[ $age -lt 60 ]]; then
            cat "$cache_file"
            return 0
        fi
    fi
    
    # Count JSON files with timeout
    local count=0
    if count=$(timeout $TIMEOUT_LONG gsutil ls -r "$GCS_DATA_PATH/" 2>/dev/null | grep -c "\.json$" 2>/dev/null); then
        echo "$count" > "$cache_file"
        date +%s > "$cache_time_file"
        echo "$count"
    elif [[ -f "$cache_file" ]]; then
        # Use stale cache if command times out
        cat "$cache_file"
    else
        echo "0"
    fi
}

# Parse ISO timestamp for elapsed time calculations
parse_iso_timestamp() {
    local iso_time="$1"
    
    if [[ -n "$iso_time" ]]; then
        # Clean up the timestamp
        local clean_time=$(echo "$iso_time" | sed 's/\.[0-9]*Z$/Z/')
        
        # Try to parse with date command
        local epoch=""
        
        # Try GNU date (Linux)
        epoch=$(date -d "$clean_time" +%s 2>/dev/null || echo "")
        
        # If that failed, try BSD date (macOS)
        if [[ -z "$epoch" ]]; then
            epoch=$(TZ=UTC date -j -f "%Y-%m-%dT%H:%M:%SZ" "$clean_time" "+%s" 2>/dev/null || echo "")
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

# Find ALL running executions (not just one)
find_all_running_executions() {
    local running_execs=()
    
    # Get recent executions with their status
    local executions=""
    if executions=$(timeout $TIMEOUT_SHORT gcloud run jobs executions list \
        --job=$JOB_NAME \
        --region=$REGION \
        --format="value(metadata.name,status.conditions[0].type,status.conditions[0].status,status.startTime)" \
        --limit=10 2>/dev/null); then
        
        while IFS=$'\t' read -r exec_name type status start_time; do
            if [[ -n "$exec_name" ]]; then
                # Check for running jobs
                if [[ "$type" == "Running" ]] || \
                   [[ "$type" == "Unknown" ]] || \
                   [[ "$type" == "Started" ]] || \
                   [[ "$type" == "Pending" ]] || \
                   [[ ("$type" == "Completed" && "$status" == "Unknown") ]]; then
                    
                    # Check if stuck (>8 hours for referee assignments)
                    if [[ -n "$start_time" ]]; then
                        local start_epoch=$(parse_iso_timestamp "$start_time")
                        local current_epoch=$(date +%s)
                        if [[ -n "$start_epoch" ]]; then
                            local elapsed_hours=$(( (current_epoch - start_epoch) / 3600 ))
                            
                            if [[ $elapsed_hours -gt 8 ]]; then
                                running_execs+=("STUCK:$exec_name:$elapsed_hours")
                            else
                                running_execs+=("$exec_name")
                            fi
                        else
                            running_execs+=("$exec_name")
                        fi
                    else
                        running_execs+=("$exec_name")
                    fi
                fi
            fi
        done <<< "$executions"
    fi
    
    # Return array as newline-separated string
    printf '%s\n' "${running_execs[@]}"
}

# Show concurrent job status
show_concurrent_status() {
    echo -e "${PURPLE}🎯 CONCURRENT JOBS STATUS:${NC}"
    echo ""
    
    # Get all running executions
    local running_execs=$(find_all_running_executions)
    
    if [[ -z "$running_execs" ]] || [[ "$running_execs" == "" ]]; then
        echo -e "${YELLOW}  No running jobs detected${NC}"
        echo -e "${BLUE}  Hint: Jobs might have completed or not started yet${NC}"
        return
    fi
    
    local total_downloads=0
    local job_count=0
    
    # Process each running job
    while IFS= read -r exec; do
        [[ -z "$exec" ]] && continue
        
        job_count=$((job_count + 1))
        
        # Check if stuck
        if [[ "$exec" =~ ^STUCK: ]]; then
            local exec_name=$(echo "$exec" | cut -d: -f2)
            local stuck_hours=$(echo "$exec" | cut -d: -f3)
            echo -e "${RED}📦 $exec_name [STUCK - ${stuck_hours}h]${NC}"
            echo -e "  ${YELLOW}Recommendation: Cancel with:${NC}"
            echo -e "  ${CYAN}gcloud run jobs executions cancel $exec_name --region=$REGION${NC}"
        else
            echo -e "${GREEN}📦 $exec:${NC}"
            
            # Get execution details
            local exec_info=$(gcloud run jobs executions describe "$exec" \
                --region=$REGION \
                --format="value(status.startTime)" 2>/dev/null)
            
            if [[ -n "$exec_info" ]]; then
                local elapsed=$(calculate_elapsed_time "$exec_info")
                echo -e "  Runtime: ${CYAN}$elapsed${NC}"
            fi
            
            # Get last download
            local last_log=$(gcloud logging read \
                "resource.type=\"cloud_run_job\" AND \
                labels.\"run.googleapis.com/execution_name\"=\"$exec\" AND \
                textPayload:\"Downloaded\"" \
                --format="value(textPayload)" \
                --limit=1 \
                --order="desc" \
                --freshness=10m 2>/dev/null | head -1)
            
            if [[ -n "$last_log" ]]; then
                # Extract date info
                local date_info=$(echo "$last_log" | grep -o "Downloaded [^:]*" | head -1)
                echo -e "  Last: ${GREEN}$date_info${NC}"
            else
                echo -e "  Last: ${YELLOW}No recent downloads${NC}"
            fi
            
            # Count downloads for this execution (quick estimate)
            local download_count=$(gcloud logging read \
                "resource.type=\"cloud_run_job\" AND \
                labels.\"run.googleapis.com/execution_name\"=\"$exec\" AND \
                textPayload:\"Downloaded\"" \
                --format="value(textPayload)" \
                --limit=1000 2>/dev/null | wc -l)
            
            total_downloads=$((total_downloads + download_count))
            echo -e "  Downloads: ${GREEN}$download_count${NC} dates"
        fi
        echo ""
    done <<< "$running_execs"
    
    # Summary
    if [[ $job_count -gt 0 ]]; then
        echo -e "${BLUE}📊 SUMMARY:${NC}"
        echo -e "  Active jobs: ${GREEN}$job_count${NC}"
        echo -e "  Total downloads (sampled): ${GREEN}$total_downloads${NC}"
    fi
}

# Quick command for multiple concurrent jobs
cmd_quick_optimized() {
    # Get ALL running executions
    local running_execs=$(find_all_running_executions)
    local running_count=0
    local stuck_count=0
    
    # Count running and stuck jobs
    while IFS= read -r exec; do
        [[ -z "$exec" ]] && continue
        if [[ "$exec" =~ ^STUCK: ]]; then
            stuck_count=$((stuck_count + 1))
        else
            running_count=$((running_count + 1))
        fi
    done <<< "$running_execs"
    
    # Status line
    if [[ $stuck_count -gt 0 ]]; then
        echo "Status: ${RED}$stuck_count STUCK${NC}, $running_count running"
    elif [[ $running_count -gt 0 ]]; then
        echo "Status: RUNNING ($running_count concurrent jobs)"
        # Show job names
        echo "$running_execs" | grep -v "^STUCK:" | sed 's/^/  ✓ /' | head -5
    else
        echo "Status: NO ACTIVE JOBS"
    fi
    
    # JSON count and progress
    local json_count=$(count_json_files_fast)
    if [[ "$json_count" -gt 0 ]]; then
        local pct=$((json_count * 100 / EXPECTED_TOTAL_DATES))
        echo "Progress: $json_count / $EXPECTED_TOTAL_DATES dates ($pct%)"
        
        # Estimate rate if jobs are running
        if [[ $running_count -gt 0 ]]; then
            # Get earliest start time
            local earliest_start=$(gcloud run jobs executions list \
                --job=$JOB_NAME \
                --region=$REGION \
                --filter="status.conditions[0].type=Unknown" \
                --format="value(status.startTime)" \
                --limit=10 2>/dev/null | tail -1)
            
            if [[ -n "$earliest_start" ]]; then
                local start_epoch=$(parse_iso_timestamp "$earliest_start")
                local current_epoch=$(date +%s)
                if [[ -n "$start_epoch" ]]; then
                    local elapsed_seconds=$((current_epoch - start_epoch))
                    if [[ $elapsed_seconds -gt 60 ]]; then
                        local rate=$((json_count * 60 / elapsed_seconds))
                        local remaining=$((EXPECTED_TOTAL_DATES - json_count))
                        local eta_minutes=$((remaining / rate))
                        local eta_hours=$((eta_minutes / 60))
                        echo "Rate: ~$rate dates/min | ETA: ${eta_hours}h"
                    fi
                fi
            fi
        fi
    else
        echo "Progress: Calculating..."
    fi
    
    # Show latest activity
    local latest=$(gcloud logging read \
        "resource.type=cloud_run_job AND textPayload:\"Downloaded\"" \
        --limit=1 \
        --format="value(textPayload)" \
        --project=$PROJECT \
        --freshness=10m 2>/dev/null | head -1)
    
    if [[ -n "$latest" ]]; then
        local date_info=$(echo "$latest" | grep -o "Downloaded [^:]*" | head -1)
        echo "Latest: $date_info"
    fi
}

# Updated status command
cmd_status() {
    print_header
    show_execution_status
    echo ""
    show_concurrent_status
    echo ""
    check_activity_health
}

# Show execution status table
show_execution_status() {
    echo -e "${BLUE}🏃 Recent Executions:${NC}"
    
    # Get execution data
    local executions_data=""
    if executions_data=$(timeout $TIMEOUT_LONG gcloud run jobs executions list \
        --job=$JOB_NAME \
        --region=$REGION \
        --limit=8 \
        --format="value(metadata.name,status.conditions[0].type,status.startTime,status.completionTime)" 2>/dev/null); then
        
        # Custom table header
        printf "%-36s %-12s %-20s %s\n" "EXECUTION" "STATUS" "STARTED" "ELAPSED/DURATION"
        printf "%-36s %-12s %-20s %s\n" "$(printf '%*s' 36 '' | tr ' ' '-')" "$(printf '%*s' 12 '' | tr ' ' '-')" "$(printf '%*s' 20 '' | tr ' ' '-')" "$(printf '%*s' 15 '' | tr ' ' '-')"
        
        # Process each execution
        while IFS=$'\t' read -r exec_name status start_time completed; do
            if [[ -n "$exec_name" ]]; then
                # Calculate elapsed/duration
                local time_display="--"
                if [[ -n "$start_time" ]]; then
                    if [[ -n "$completed" && "$completed" != "null" && "$status" == "Completed" ]]; then
                        # Completed - show duration
                        local start_epoch=$(parse_iso_timestamp "$start_time")
                        local end_epoch=$(parse_iso_timestamp "$completed")
                        if [[ -n "$start_epoch" && -n "$end_epoch" ]]; then
                            local duration_seconds=$((end_epoch - start_epoch))
                            local hours=$((duration_seconds / 3600))
                            local minutes=$(((duration_seconds % 3600) / 60))
                            time_display="${hours}h ${minutes}m"
                        fi
                    else
                        # Running - show elapsed
                        time_display=$(calculate_elapsed_time "$start_time")
                        [[ -n "$time_display" ]] && time_display="$time_display (running)"
                    fi
                fi
                
                # Format start time for display
                local start_display="--"
                if [[ -n "$start_time" ]]; then
                    start_display=$(echo "$start_time" | sed 's/T/ /' | sed 's/\.[0-9]*Z$//' | cut -d' ' -f2)
                fi
                
                # Color code status
                local status_colored="$status"
                case "$status" in
                    "Unknown"|"Running") status_colored="${GREEN}$status${NC}" ;;
                    "Completed") status_colored="${CYAN}$status${NC}" ;;
                    "Failed") status_colored="${RED}$status${NC}" ;;
                    *) status_colored="${YELLOW}$status${NC}" ;;
                esac
                
                printf "%-36s %-12b %-20s %s\n" "$exec_name" "$status_colored" "$start_display" "$time_display"
            fi
        done <<< "$executions_data"
    else
        echo -e "${RED}❌ Failed to get execution status${NC}"
    fi
}

# Check activity health
check_activity_health() {
    echo -e "${BLUE}🏥 Activity Health:${NC}"
    
    # Get recent logs
    local recent_logs=""
    if recent_logs=$(gcloud logging read \
        "resource.type=cloud_run_job AND resource.labels.job_name=\"$JOB_NAME\"" \
        --limit=50 \
        --format="value(textPayload)" \
        --project=$PROJECT \
        --freshness=30m 2>/dev/null); then
        
        if [[ -n "$recent_logs" ]]; then
            local recent_downloads=$(echo "$recent_logs" | grep -c "✅ Downloaded" || echo "0")
            local no_games=$(echo "$recent_logs" | grep -c "📅 No games" || echo "0")
            local recent_errors=$(echo "$recent_logs" | grep -c "❌" || echo "0")
            local recent_timeouts=$(echo "$recent_logs" | grep -c "Timeout" || echo "0")
            
            echo -e "  Last 30 minutes:"
            echo -e "    Downloads: ${GREEN}$recent_downloads${NC}"
            echo -e "    No games: ${CYAN}$no_games${NC}"
            echo -e "    Errors: ${RED}$recent_errors${NC}"
            echo -e "    Timeouts: ${YELLOW}$recent_timeouts${NC}"
            
            local total_activity=$((recent_downloads + no_games))
            if [[ $total_activity -gt 0 ]]; then
                echo -e "  Status: ${GREEN}✅ Healthy - Active processing${NC}"
            elif [[ $recent_errors -gt 5 ]]; then
                echo -e "  Status: ${RED}⚠️  High error rate${NC}"
            else
                echo -e "  Status: ${YELLOW}⚠️  Low activity${NC}"
            fi
        else
            echo -e "  ${YELLOW}No recent activity${NC}"
        fi
    else
        echo -e "  ${RED}Failed to check health${NC}"
    fi
}

# Progress command
cmd_progress() {
    print_header
    
    echo -e "${BLUE}📊 BACKFILL PROGRESS:${NC}"
    echo ""
    
    # Get JSON count
    local json_count=$(count_json_files_fast)
    
    # Progress bar
    local json_pct=$((json_count * 100 / EXPECTED_TOTAL_DATES))
    
    # JSON Progress
    echo -e "${PURPLE}📄 Referee Assignments:${NC}"
    printf "  Progress: ["
    local bar_width=30
    local filled=$((json_pct * bar_width / 100))
    for ((i=0; i<filled; i++)); do printf "="; done
    for ((i=filled; i<bar_width; i++)); do printf " "; done
    printf "] ${GREEN}%d%%${NC}\n" "$json_pct"
    echo -e "  Count: ${GREEN}$json_count${NC} / $EXPECTED_TOTAL_DATES dates"
    
    # Year breakdown
    echo ""
    echo -e "${BLUE}📅 BY YEAR:${NC}"
    for year in 2021 2022 2023 2024; do
        local year_count=$(gsutil ls "$GCS_DATA_PATH/$year/**/*.json" 2>/dev/null | wc -l || echo "0")
        echo -e "  Year $year: ${GREEN}$year_count${NC} files"
    done
}

# Watch command
cmd_watch() {
    echo -e "${GREEN}Starting continuous monitoring (Ctrl+C to stop)...${NC}"
    
    while true; do
        clear
        cmd_quick_optimized
        echo ""
        echo "========================"
        show_concurrent_status
        echo ""
        echo -e "${YELLOW}Refreshing in 30 seconds... (Ctrl+C to stop)${NC}"
        sleep 30
    done
}

# Logs command
cmd_logs() {
    local count=${1:-20}
    print_header
    echo -e "${BLUE}📄 Recent Logs (last $count):${NC}"
    
    gcloud logging read \
        "resource.type=cloud_run_job AND resource.labels.job_name=\"$JOB_NAME\"" \
        --limit=$count \
        --format="value(timestamp,textPayload)" \
        --project=$PROJECT \
        --freshness=1h 2>/dev/null | \
        while IFS=$'\t' read -r timestamp text; do
            echo "  $(echo "$timestamp" | cut -d'T' -f2 | cut -d'.' -f1) $text"
        done
}

# Cancel stuck jobs
cmd_cancel_stuck() {
    print_header
    echo -e "${BLUE}🔍 Checking for stuck jobs...${NC}"
    
    local running_execs=$(find_all_running_executions)
    local found_stuck=false
    
    while IFS= read -r exec; do
        [[ -z "$exec" ]] && continue
        
        if [[ "$exec" =~ ^STUCK: ]]; then
            found_stuck=true
            local exec_name=$(echo "$exec" | cut -d: -f2)
            local stuck_hours=$(echo "$exec" | cut -d: -f3)
            
            echo -e "${RED}Found stuck job: $exec_name (${stuck_hours}h elapsed)${NC}"
            echo -e "${YELLOW}Cancelling...${NC}"
            
            if gcloud run jobs executions cancel "$exec_name" --region=$REGION --quiet; then
                echo -e "${GREEN}✅ Successfully cancelled${NC}"
            else
                echo -e "${RED}❌ Failed to cancel${NC}"
            fi
        fi
    done <<< "$running_execs"
    
    if [[ "$found_stuck" == "false" ]]; then
        echo -e "${GREEN}✅ No stuck jobs found${NC}"
    fi
}

# Restart job
cmd_restart() {
    print_header
    echo -e "${BLUE}🔄 Restarting backfill job...${NC}"
    
    # Check for running jobs
    local running_execs=$(find_all_running_executions | grep -v "^STUCK:")
    if [[ -n "$running_execs" ]]; then
        echo -e "${YELLOW}⚠️  Active jobs detected. Cancel them first? (y/N)${NC}"
        read -r response
        if [[ "$response" =~ ^[Yy] ]]; then
            while IFS= read -r exec; do
                [[ -z "$exec" ]] && continue
                echo "Cancelling $exec..."
                gcloud run jobs executions cancel "$exec" --region=$REGION --quiet
            done <<< "$running_execs"
        else
            echo "Aborted"
            return 1
        fi
    fi
    
    echo -e "${BLUE}Starting new execution...${NC}"
    if gcloud run jobs execute $JOB_NAME --region=$REGION; then
        echo -e "${GREEN}✅ Job started${NC}"
    else
        echo -e "${RED}❌ Failed to start${NC}"
    fi
}

# Clear cache
cmd_clear_cache() {
    echo -e "${BLUE}🧹 Clearing cache...${NC}"
    rm -rf "$CACHE_DIR"
    mkdir -p "$CACHE_DIR"
    echo -e "${GREEN}✅ Cache cleared${NC}"
}

# Usage help
show_usage() {
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  quick          - Quick status check (default)"
    echo "  status         - Detailed status with execution history"
    echo "  progress       - Progress analysis with year breakdown"
    echo "  watch          - Continuous monitoring (30s refresh)"
    echo "  logs [N]       - Show last N log entries (default: 20)"
    echo "  cancel-stuck   - Find and cancel stuck jobs (>8h)"
    echo "  restart        - Restart the backfill job"
    echo "  clear-cache    - Clear cached data"
    echo ""
    echo "Features:"
    echo "  - Supports multiple concurrent job executions"
    echo "  - Automatic stuck job detection (>8 hours)"
    echo "  - Smart caching for performance (${CACHE_TTL}s TTL)"
    echo "  - JSON file count tracking with progress estimation"
    echo ""
    echo "Examples:"
    echo "  $0 quick                    # Quick status"
    echo "  $0 watch                    # Continuous monitoring"
    echo "  $0 logs 50                  # Last 50 log entries"
}

# Main command router
case "${1:-quick}" in
    "quick"|"")
        cmd_quick_optimized
        ;;
    "status")
        cmd_status
        ;;
    "progress")
        cmd_progress
        ;;
    "watch")
        cmd_watch
        ;;
    "logs")
        cmd_logs "$2"
        ;;
    "cancel-stuck")
        cmd_cancel_stuck
        ;;
    "restart")
        cmd_restart
        ;;
    "clear-cache")
        cmd_clear_cache
        ;;
    "help"|"-h"|"--help")
        show_usage
        ;;
    *)
        echo "Unknown command: $1"
        show_usage
        exit 1
        ;;
esac