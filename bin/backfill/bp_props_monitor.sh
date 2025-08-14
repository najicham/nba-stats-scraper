#!/bin/bash
# File: bin/backfill/bp_props_monitor.sh
# Clean BettingPros Historical Backfill Monitor
# Usage: ./bin/backfill/bp_props_monitor.sh [command] [options]

set -e

# Configuration
PROJECT="nba-props-platform"
REGION="us-west2"
JOB_NAME="nba-bp-backfill"
GCS_EVENTS_PATH="gs://nba-scraped-data/bettingpros/events"
GCS_PROPS_PATH="gs://nba-scraped-data/bettingpros/player-props/points"
BASELINE_DIRS=0
TARGET_DIRS_PER_SEASON=85
TOTAL_SEASONS=3
TARGET_DIRS_TOTAL=$((TARGET_DIRS_PER_SEASON * TOTAL_SEASONS))

# Colors using tput (macOS compatible)
if command -v tput >/dev/null 2>&1 && [[ $(tput colors 2>/dev/null || echo 0) -ge 8 ]]; then
    RED=$(tput setaf 1)
    GREEN=$(tput setaf 2)
    YELLOW=$(tput setaf 3)
    BLUE=$(tput setaf 4)
    PURPLE=$(tput setaf 5)
    CYAN=$(tput setaf 6)
    BOLD=$(tput bold)
    NC=$(tput sgr0)
else
    RED="" GREEN="" YELLOW="" BLUE="" PURPLE="" CYAN="" BOLD="" NC=""
fi

# Parse arguments
COMMAND="${1:-quick}"
NO_COLOR=false
CUSTOM_BASELINE=""

for arg in "$@"; do
    case $arg in
        --no-color) NO_COLOR=true ;;
        --baseline=*) CUSTOM_BASELINE="${arg#*=}" ;;
    esac
done

if [[ "$NO_COLOR" == true ]]; then
    RED="" GREEN="" YELLOW="" BLUE="" PURPLE="" CYAN="" BOLD="" NC=""
fi

if [[ -n "$CUSTOM_BASELINE" ]]; then
    BASELINE_DIRS="$CUSTOM_BASELINE"
fi

# Helper functions
print_header() {
    printf "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
    printf "${CYAN}${BOLD}📊 BETTINGPROS HISTORICAL BACKFILL MONITOR${NC}\n"
    printf "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
    printf "${BLUE}Time: $(date)${NC}\n"
    printf "${BLUE}Job: $JOB_NAME${NC}\n\n"
}

get_execution_status() {
    # Check for recent activity (simple approach)
    local recent_activity
    recent_activity=$(gcloud logging read \
        "resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME" \
        --limit=1 \
        --format="value(timestamp)" \
        --project="$PROJECT" \
        --freshness=5m 2>/dev/null | head -1)
    
    # Get most recent execution name
    local exec_name
    exec_name=$(gcloud run jobs executions list \
        --job="$JOB_NAME" \
        --region="$REGION" \
        --limit=1 \
        --format="value(metadata.name)" \
        2>/dev/null | head -1)
    
    if [[ -n "$recent_activity" && -n "$exec_name" ]]; then
        printf "${GREEN}RUNNING${NC} ($exec_name)"
    elif [[ -n "$exec_name" ]]; then
        printf "${BLUE}COMPLETED${NC} ($exec_name)"
    else
        printf "${RED}NO EXECUTIONS${NC}"
    fi
}

get_directory_count() {
    local count
    count=$(gcloud storage ls "$GCS_PROPS_PATH/" 2>/dev/null | wc -l | tr -d ' ' || echo "0")
    echo "$count"
}

get_current_season() {
    # Extract year from most recent directory
    local recent_dir
    recent_dir=$(gcloud storage ls "$GCS_PROPS_PATH/" 2>/dev/null | sort | tail -1)
    if [[ -n "$recent_dir" ]]; then
        local date_name=$(basename "$recent_dir" | sed 's|/$||')
        local year=$(echo "$date_name" | cut -d- -f1 2>/dev/null || echo "")
        if [[ "$year" =~ ^20[0-9][0-9]$ ]]; then
            echo "$year"
            return
        fi
    fi
    echo "unknown"
}

get_progress_info() {
    local current_count="$1"
    local current_season="$2"
    local new_dirs=$((current_count - BASELINE_DIRS))
    local progress_percent=0
    local season_progress_percent=0
    
    if [[ $new_dirs -gt 0 ]]; then
        progress_percent=$((new_dirs * 100 / TARGET_DIRS_TOTAL))
        
        # Calculate season-specific progress
        if [[ "$current_season" != "unknown" ]]; then
            season_progress_percent=$((new_dirs * 100 / TARGET_DIRS_PER_SEASON))
        fi
    fi
    
    echo "$new_dirs:$progress_percent:$season_progress_percent"
}

get_latest_activity() {
    gcloud logging read \
        "resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME" \
        --limit=1 \
        --format="value(textPayload)" \
        --project="$PROJECT" \
        --freshness=1h 2>/dev/null | head -1
}

validate_data_consistency() {
    local events_count props_count
    events_count=$(gcloud storage ls "$GCS_EVENTS_PATH/" 2>/dev/null | wc -l | tr -d ' ' || echo "0")
    props_count=$(gcloud storage ls "$GCS_PROPS_PATH/" 2>/dev/null | wc -l | tr -d ' ' || echo "0")
    
    if [[ "$events_count" -eq "$props_count" ]]; then
        printf "${GREEN}✅ Data Consistent${NC} (events: $events_count, props: $props_count)"
    elif [[ "$events_count" -gt "$props_count" ]]; then
        local diff=$((events_count - props_count))
        printf "${YELLOW}⚠️  Missing Props${NC} ($diff dates have events but no props)"
    elif [[ "$props_count" -gt "$events_count" ]]; then
        local diff=$((props_count - events_count))
        printf "${YELLOW}⚠️  Missing Events${NC} ($diff dates have props but no events)"
    else
        printf "${RED}❌ Data Issue${NC} (events: $events_count, props: $props_count)"
    fi
}

# Commands
cmd_quick() {
    printf "Status: "
    get_execution_status
    printf "\n"
    
    local dir_count
    dir_count=$(get_directory_count)
    printf "Directory Count: ${GREEN}$dir_count${NC} (baseline: $BASELINE_DIRS)\n"
    
    local current_season
    current_season=$(get_current_season)
    if [[ "$current_season" != "unknown" ]]; then
        printf "Current Season: ${PURPLE}$current_season${NC}\n"
    fi
    
    local progress_info
    progress_info=$(get_progress_info "$dir_count" "$current_season")
    local new_dirs=$(echo "$progress_info" | cut -d: -f1)
    local progress_percent=$(echo "$progress_info" | cut -d: -f2)
    local season_progress=$(echo "$progress_info" | cut -d: -f3)
    
    if [[ $new_dirs -gt 0 ]]; then
        printf "✅ Progress: ${GREEN}+$new_dirs${NC} new dates"
        if [[ "$current_season" != "unknown" && $season_progress -gt 0 ]]; then
            printf " (${PURPLE}$season_progress%%${NC} of $current_season season, ${PURPLE}$progress_percent%%${NC} total)\n"
        else
            printf " (${PURPLE}$progress_percent%%${NC} of total target)\n"
        fi
        
        # Add quick timing info
        local elapsed_seconds
        elapsed_seconds=$(get_execution_timing)
        if [[ $elapsed_seconds -gt 0 ]]; then
            local elapsed_formatted
            elapsed_formatted=$(format_duration "$elapsed_seconds")
            printf "⏰ Elapsed: ${CYAN}$elapsed_formatted${NC}"
            
            # Quick ETA calculation
            local remaining_total=$((TARGET_DIRS_TOTAL - new_dirs))
            if [[ $remaining_total -gt 0 ]]; then
                local eta_seconds
                if command -v bc >/dev/null 2>&1; then
                    eta_seconds=$(echo "scale=0; $remaining_total * $elapsed_seconds / $new_dirs" | bc 2>/dev/null || echo "0")
                else
                    eta_seconds=$((remaining_total * elapsed_seconds / new_dirs))
                fi
                
                if [[ $eta_seconds -gt 0 ]]; then
                    local eta_formatted
                    eta_formatted=$(format_duration "$eta_seconds")
                    printf ", ETA: ${YELLOW}$eta_formatted${NC}"
                fi
            fi
            printf "\n"
        fi
    else
        printf "⚠️  No new directories yet\n"
    fi
    
    printf "Data Check: "
    validate_data_consistency
    printf "\n"
    
    local latest_activity
    latest_activity=$(get_latest_activity)
    if [[ -n "$latest_activity" ]]; then
        printf "Latest Activity: ${CYAN}$latest_activity${NC}\n"
    fi
}

cmd_status() {
    print_header
    
    printf "${BOLD}📊 EXECUTION STATUS:${NC}\n"
    printf "Status: "
    get_execution_status
    printf "\n\n"
    
    local current_season
    current_season=$(get_current_season)
    
    printf "${BOLD}📁 PROGRESS:${NC}\n"
    local dir_count
    dir_count=$(get_directory_count)
    printf "Total Directories: ${GREEN}$dir_count${NC}\n"
    printf "Baseline: ${CYAN}$BASELINE_DIRS${NC}\n"
    
    if [[ "$current_season" != "unknown" ]]; then
        printf "Current Season: ${PURPLE}$current_season${NC}\n"
        printf "Target per Season: ${CYAN}$TARGET_DIRS_PER_SEASON${NC} dates\n"
    fi
    printf "Total Target: ${CYAN}$TARGET_DIRS_TOTAL${NC} dates (3 seasons)\n"
    
    local progress_info
    progress_info=$(get_progress_info "$dir_count" "$current_season")
    local new_dirs=$(echo "$progress_info" | cut -d: -f1)
    local progress_percent=$(echo "$progress_info" | cut -d: -f2)
    local season_progress=$(echo "$progress_info" | cut -d: -f3)
    
    printf "New Collections: ${GREEN}+$new_dirs${NC}\n"
    if [[ "$current_season" != "unknown" && $season_progress -gt 0 ]]; then
        printf "Season Progress: ${PURPLE}$season_progress%%${NC} ($current_season)\n"
    fi
    printf "Total Progress: ${PURPLE}$progress_percent%%${NC}\n\n"
    
    printf "${BOLD}🔍 DATA VALIDATION:${NC}\n"
    validate_data_consistency
    printf "\n\n"
    
    printf "${BOLD}📄 RECENT ACTIVITY:${NC}\n"
    local recent_logs
    recent_logs=$(gcloud logging read \
        "resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME" \
        --limit=5 \
        --format="value(textPayload)" \
        --project="$PROJECT" \
        --freshness=2h 2>/dev/null || echo "")
    
    if [[ -n "$recent_logs" ]]; then
        echo "$recent_logs" | sed 's/^/  /'
    else
        printf "  ${YELLOW}No recent activity${NC}\n"
    fi
}

cmd_watch() {
    printf "${GREEN}Starting continuous monitoring (Ctrl+C to stop)${NC}\n"
    printf "${CYAN}Refresh: 15 seconds${NC}\n"
    printf "${YELLOW}Press Ctrl+C to stop...${NC}\n\n"
    
    sleep 2
    local update_count=0
    
    while true; do
        update_count=$((update_count + 1))
        
        if [[ $update_count -gt 1 ]]; then
            printf "\033[H"
            printf "${YELLOW}${BOLD}🔄 Refreshing data...${NC}$(printf '%*s' 50 '')\n"
            sleep 0.5
            printf "\033[H"
        else
            clear
        fi
        
        printf "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
        printf "${CYAN}${BOLD}📊 BETTINGPROS LIVE MONITOR${NC}\n"
        printf "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
        printf "${BLUE}Update #$update_count - $(date)${NC}\n"
        printf "${BLUE}Job: $JOB_NAME${NC}\n\n"
        
        cmd_quick
        
        printf "\033[K\n\033[K\n\033[K\n"
        printf "${YELLOW}⏱️  Next update in 15 seconds... (Ctrl+C to stop)${NC}\n"
        sleep 15
    done
}

cmd_logs() {
    local count=${1:-10}
    print_header
    
    printf "${BOLD}📄 RECENT LOGS (last $count):${NC}\n\n"
    local logs
    logs=$(gcloud logging read \
        "resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME" \
        --limit="$count" \
        --format="value(timestamp,textPayload)" \
        --project="$PROJECT" \
        --freshness=4h 2>/dev/null || echo "")
    
    if [[ -n "$logs" ]]; then
        echo "$logs" | sed 's/^/  /'
    else
        printf "  ${YELLOW}No recent logs found${NC}\n"
    fi
}

get_execution_timing() {
    # Get the most recent execution start time
    local exec_start_time
    exec_start_time=$(gcloud run jobs executions list \
        --job="$JOB_NAME" \
        --region="$REGION" \
        --limit=1 \
        --format="value(status.startTime)" \
        2>/dev/null | head -1)
    
    if [[ -n "$exec_start_time" ]]; then
        # Strip microseconds for easier parsing: 2025-08-13T01:32:44.077400Z -> 2025-08-13T01:32:44Z
        local clean_time
        clean_time=$(echo "$exec_start_time" | sed 's/\.[0-9]*Z/Z/')
        
        local start_epoch=""
        
        if [[ "$OSTYPE" == "darwin"* ]]; then
            # macOS date parsing
            start_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$clean_time" +%s 2>/dev/null || echo "")
        else
            # Linux date parsing
            start_epoch=$(date -d "$clean_time" +%s 2>/dev/null || echo "")
        fi
        
        if [[ -n "$start_epoch" && "$start_epoch" != "0" ]]; then
            local current_epoch
            current_epoch=$(date +%s)
            local elapsed_seconds=$((current_epoch - start_epoch))
            
            echo "$elapsed_seconds"
            return
        fi
    fi
    
    echo "0"
}

format_duration() {
    local seconds="$1"
    if [[ $seconds -lt 60 ]]; then
        echo "${seconds}s"
    elif [[ $seconds -lt 3600 ]]; then
        local minutes=$((seconds / 60))
        local secs=$((seconds % 60))
        printf "%dm %ds" "$minutes" "$secs"
    else
        local hours=$((seconds / 3600))
        local minutes=$(((seconds % 3600) / 60))
        printf "%dh %dm" "$hours" "$minutes"
    fi
}

cmd_progress() {
    print_header
    
    printf "${BOLD}📊 DETAILED PROGRESS ANALYSIS:${NC}\n\n"
    
    local dir_count
    dir_count=$(get_directory_count)
    local current_season
    current_season=$(get_current_season)
    
    printf "📁 Player Props Directories: ${GREEN}$dir_count${NC}\n"
    printf "📅 Baseline: ${CYAN}$BASELINE_DIRS${NC}\n"
    if [[ "$current_season" != "unknown" ]]; then
        printf "🎯 Current Season: ${PURPLE}$current_season${NC}\n"
        printf "🎯 Target per Season: ${PURPLE}$TARGET_DIRS_PER_SEASON${NC} dates\n"
    fi
    printf "🎯 Total Target: ${PURPLE}$TARGET_DIRS_TOTAL${NC} dates (3 seasons)\n\n"
    
    local progress_info
    progress_info=$(get_progress_info "$dir_count" "$current_season")
    local new_dirs=$(echo "$progress_info" | cut -d: -f1)
    local progress_percent=$(echo "$progress_info" | cut -d: -f2)
    local season_progress=$(echo "$progress_info" | cut -d: -f3)
    
    # Timing calculations
    local elapsed_seconds
    elapsed_seconds=$(get_execution_timing)
    local elapsed_formatted
    elapsed_formatted=$(format_duration "$elapsed_seconds")
    
    if [[ $new_dirs -gt 0 ]]; then
        printf "🆕 New Collections: ${GREEN}+$new_dirs${NC} dates\n"
        printf "📈 Total Progress: ${PURPLE}$progress_percent%%${NC}\n"
        
        local remaining_total=$((TARGET_DIRS_TOTAL - new_dirs))
        printf "📅 Estimated Remaining: ${YELLOW}~$remaining_total${NC} dates\n"
        
        # Time calculations
        if [[ $elapsed_seconds -gt 0 && $new_dirs -gt 0 ]]; then
            printf "⏰ Time Elapsed: ${CYAN}$elapsed_formatted${NC}\n"
            
            # Calculate ETA (simple arithmetic, fallback if bc not available)
            if command -v bc >/dev/null 2>&1; then
                local rate_per_second
                rate_per_second=$(echo "scale=6; $new_dirs / $elapsed_seconds" | bc 2>/dev/null || echo "0")
                
                if [[ $(echo "$rate_per_second > 0" | bc 2>/dev/null || echo "0") -eq 1 ]]; then
                    local eta_seconds
                    eta_seconds=$(echo "scale=0; $remaining_total / $rate_per_second" | bc 2>/dev/null || echo "0")
                    local eta_formatted
                    eta_formatted=$(format_duration "$eta_seconds")
                    printf "🎯 Estimated Completion: ${YELLOW}$eta_formatted${NC}\n"
                fi
            else
                # Fallback calculation without bc
                local eta_seconds=$((remaining_total * elapsed_seconds / new_dirs))
                local eta_formatted
                eta_formatted=$(format_duration "$eta_seconds")
                printf "🎯 Estimated Completion: ${YELLOW}~$eta_formatted${NC}\n"
            fi
        fi
        printf "\n"
    else
        printf "🚨 No new data collected yet\n\n"
    fi
    
    printf "${BOLD}🔍 DATA VALIDATION:${NC}\n"
    validate_data_consistency
    printf "\n\n"
    
    printf "${BOLD}📂 RECENT DIRECTORIES:${NC}\n"
    local recent_dirs
    recent_dirs=$(gcloud storage ls "$GCS_PROPS_PATH/" 2>/dev/null | sort | tail -10 || echo "")
    
    if [[ -n "$recent_dirs" ]]; then
        echo "$recent_dirs" | while read -r dir; do
            local date_name=$(basename "$dir" | sed 's|/$||')
            if [[ -n "$date_name" ]]; then
                printf "  📅 ${GREEN}%s${NC}\n" "$date_name"
            fi
        done
    else
        printf "  ${YELLOW}No directories found${NC}\n"
    fi
}

show_usage() {
    printf "Usage: $0 [command] [options]\n\n"
    printf "Commands:\n"
    printf "  quick       - Fast status check (default)\n"
    printf "  status      - Comprehensive overview\n"
    printf "  progress    - Detailed progress analysis\n"
    printf "  watch       - Continuous monitoring (15s updates)\n"
    printf "  logs [N]    - Show last N log entries\n"
    printf "\n"
    printf "Options:\n"
    printf "  --no-color     - Disable colored output\n"
    printf "  --baseline=N   - Set custom baseline directory count\n"
    printf "\n"
    printf "Examples:\n"
    printf "  $0 quick                 # Quick status\n"
    printf "  $0 watch                 # Continuous monitoring\n"
    printf "  $0 logs 20               # Show 20 recent logs\n"
    printf "  $0 status --baseline=5   # Status with custom baseline\n"
}

# Main command handling
case "$COMMAND" in
    "quick"|"")
        cmd_quick
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
        shift
        cmd_logs "$1"
        ;;
    "help"|"-h"|"--help")
        show_usage
        ;;
    *)
        printf "${RED}Unknown command: $COMMAND${NC}\n"
        show_usage
        exit 1
        ;;
esac