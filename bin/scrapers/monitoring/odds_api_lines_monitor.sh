#!/bin/bash
# File: bin/scrapers/monitoring/odds_api_lines_monitor.sh
# NBA Odds API Game Lines Backfill Monitor
# Usage: ./bin/scrapers/monitoring/odds_api_lines_monitor.sh [command] [options]

set -euo pipefail

# Configuration
PROJECT="nba-props-platform"
REGION="us-west2"
JOB_NAME="nba-odds-api-lines-backfill"
GCS_PATH="gs://nba-scraped-data/odds-api/game-lines-history"
BASELINE_DIRS=0   # Starting from scratch for game lines
TARGET_DIRS=1200  # ~1,200 game dates across 4 seasons

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

for arg in "$@"; do
    case $arg in
        --no-color) NO_COLOR=true ;;
    esac
done

if [[ "$NO_COLOR" == true ]]; then
    RED="" GREEN="" YELLOW="" BLUE="" PURPLE="" CYAN="" BOLD="" NC=""
fi

# Helper functions
print_header() {
    printf "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
    printf "${CYAN}${BOLD}📊 NBA ODDS API GAME LINES BACKFILL MONITOR${NC}\n"
    printf "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
    printf "${BLUE}Time: $(date)${NC}\n"
    printf "${BLUE}Job: $JOB_NAME${NC}\n\n"
}

get_execution_status() {
    local exec_data
    exec_data=$(gcloud run jobs executions list \
        --job="$JOB_NAME" \
        --region="$REGION" \
        --limit=1 \
        --format="value(metadata.name,status.runningCount,status.succeededCount)" \
        2>/dev/null || echo "")
    
    if [[ -n "$exec_data" ]]; then
        local exec_name=$(echo "$exec_data" | cut -f1)
        local running_count=$(echo "$exec_data" | cut -f2)
        local succeeded_count=$(echo "$exec_data" | cut -f3)
        
        if [[ "$running_count" -gt 0 ]]; then
            printf "${GREEN}RUNNING${NC} ($exec_name)"
        elif [[ "$succeeded_count" -gt 0 ]]; then
            printf "${BLUE}COMPLETED${NC} ($exec_name)"
        else
            printf "${YELLOW}PENDING${NC} ($exec_name)"
        fi
    else
        printf "${RED}NO EXECUTIONS${NC}"
    fi
}

get_directory_count() {
    local count
    count=$(gcloud storage ls "$GCS_PATH/" 2>/dev/null | wc -l | tr -d ' ' || echo "0")
    echo "$count"
}

get_progress_info() {
    local current_count="$1"
    local new_dirs=$((current_count - BASELINE_DIRS))
    local progress_percent=0
    
    if [[ $new_dirs -gt 0 && $TARGET_DIRS -gt 0 ]]; then
        progress_percent=$((new_dirs * 100 / TARGET_DIRS))
    fi
    
    echo "$new_dirs:$progress_percent"
}

get_latest_activity() {
    gcloud logging read \
        "resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME" \
        --limit=1 \
        --format="value(textPayload)" \
        --project="$PROJECT" \
        --freshness=1h 2>/dev/null | head -1
}

get_estimated_completion() {
    local current_count="$1"
    local progress_info
    progress_info=$(get_progress_info "$current_count")
    local new_dirs=$(echo "$progress_info" | cut -d: -f1)
    local progress_percent=$(echo "$progress_info" | cut -d: -f2)
    
    if [[ $new_dirs -gt 0 ]]; then
        local remaining_dirs=$((TARGET_DIRS - new_dirs))
        # Estimate: ~2 API calls per date, 1 second each = ~2 seconds per directory
        local est_remaining_minutes=$((remaining_dirs * 2 / 60))
        local est_hours=$((est_remaining_minutes / 60))
        local est_mins=$((est_remaining_minutes % 60))
        
        if [[ $est_hours -gt 0 ]]; then
            echo "${est_hours}h ${est_mins}m"
        else
            echo "${est_mins}m"
        fi
    else
        echo "Unknown"
    fi
}

# Commands
cmd_quick() {
    printf "Status: "
    get_execution_status
    printf "\n"
    
    local dir_count
    dir_count=$(get_directory_count)
    printf "Directory Count: ${GREEN}$dir_count${NC}"
    
    local progress_info
    progress_info=$(get_progress_info "$dir_count")
    local new_dirs=$(echo "$progress_info" | cut -d: -f1)
    local progress_percent=$(echo "$progress_info" | cut -d: -f2)
    
    if [[ $new_dirs -gt 0 ]]; then
        printf " (${PURPLE}$progress_percent%%${NC} complete)\n"
        local eta=$(get_estimated_completion "$dir_count")
        printf "🕐 ETA: ${YELLOW}~$eta${NC} remaining\n"
    else
        printf "\n⚠️  No data collected yet\n"
    fi
    
    local latest_activity
    latest_activity=$(get_latest_activity)
    if [[ -n "$latest_activity" ]]; then
        printf "Latest: ${CYAN}$latest_activity${NC}\n"
    fi
}

cmd_status() {
    print_header
    
    printf "${BOLD}📊 EXECUTION STATUS:${NC}\n"
    printf "Status: "
    get_execution_status
    printf "\n\n"
    
    printf "${BOLD}📁 PROGRESS:${NC}\n"
    local dir_count
    dir_count=$(get_directory_count)
    printf "Total Directories: ${GREEN}$dir_count${NC}\n"
    printf "Target: ${CYAN}$TARGET_DIRS${NC} game dates (4 seasons)\n"
    
    local progress_info
    progress_info=$(get_progress_info "$dir_count")
    local new_dirs=$(echo "$progress_info" | cut -d: -f1)
    local progress_percent=$(echo "$progress_info" | cut -d: -f2)
    
    printf "Progress: ${PURPLE}$progress_percent%%${NC} complete\n"
    
    if [[ $new_dirs -gt 0 ]]; then
        local remaining_dirs=$((TARGET_DIRS - new_dirs))
        printf "Remaining: ${YELLOW}$remaining_dirs${NC} dates\n"
        local eta=$(get_estimated_completion "$dir_count")
        printf "ETA: ${YELLOW}~$eta${NC}\n"
    fi
    
    printf "\n${BOLD}📄 RECENT ACTIVITY:${NC}\n"
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
        printf "${CYAN}${BOLD}📊 NBA ODDS API GAME LINES LIVE MONITOR${NC}\n"
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

cmd_progress() {
    print_header
    
    printf "${BOLD}📊 DETAILED PROGRESS ANALYSIS:${NC}\n\n"
    
    local dir_count
    dir_count=$(get_directory_count)
    printf "📁 Total Directories: ${GREEN}$dir_count${NC}\n"
    printf "🎯 Target: ${PURPLE}$TARGET_DIRS${NC} (4 seasons: 2021-22 through 2024-25)\n"
    printf "📅 Data Range: ${CYAN}2021-10-01${NC} onwards\n\n"
    
    local progress_info
    progress_info=$(get_progress_info "$dir_count")
    local new_dirs=$(echo "$progress_info" | cut -d: -f1)
    local progress_percent=$(echo "$progress_info" | cut -d: -f2)
    
    if [[ $new_dirs -gt 0 ]]; then
        printf "📈 Progress: ${PURPLE}$progress_percent%%${NC} complete\n"
        printf "✅ Collected: ${GREEN}$new_dirs${NC} game dates\n"
        
        local remaining_dirs=$((TARGET_DIRS - new_dirs))
        printf "📅 Remaining: ${YELLOW}$remaining_dirs${NC} dates\n"
        
        local eta=$(get_estimated_completion "$dir_count")
        printf "🕐 ETA: ${YELLOW}~$eta${NC}\n\n"
        
        # Season breakdown estimate
        local avg_games_per_season=$((TARGET_DIRS / 4))
        local seasons_complete=$((new_dirs / avg_games_per_season))
        printf "🏀 Estimated seasons complete: ${GREEN}~$seasons_complete${NC}/4\n\n"
    else
        printf "🚨 No data collected yet\n\n"
    fi
    
    printf "${BOLD}📂 RECENT GAME DATES:${NC}\n"
    local recent_dirs
    recent_dirs=$(gcloud storage ls "$GCS_PATH/" 2>/dev/null | sort | tail -10 || echo "")
    
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

cmd_compare() {
    print_header
    
    printf "${BOLD}⚖️  GAME LINES vs PROPS COMPARISON:${NC}\n\n"
    
    local lines_count
    lines_count=$(get_directory_count)
    
    local props_count
    props_count=$(gcloud storage ls "gs://nba-scraped-data/odds-api/player-props-history/" 2>/dev/null | wc -l | tr -d ' ' || echo "0")
    
    printf "📊 Game Lines: ${GREEN}$lines_count${NC} dates\n"
    printf "🎯 Player Props: ${BLUE}$props_count${NC} dates\n\n"
    
    printf "${BOLD}📅 DATA COVERAGE:${NC}\n"
    printf "Game Lines: ${CYAN}2021-10-01${NC} onwards (4 seasons)\n"
    printf "Player Props: ${CYAN}2023-05-03${NC} onwards (playoffs + 1 season)\n\n"
    
    printf "${BOLD}🔄 COLLECTION PATTERN:${NC}\n"
    printf "Game Lines: 1 API call per date (simpler)\n"
    printf "Player Props: Multiple calls per date (per game)\n"
}

show_usage() {
    printf "Usage: $0 [command] [options]\n\n"
    printf "Commands:\n"
    printf "  quick       - Fast status check (default)\n"
    printf "  status      - Comprehensive overview\n"
    printf "  progress    - Detailed progress analysis\n"
    printf "  watch       - Continuous monitoring (15s updates)\n"
    printf "  logs [N]    - Show last N log entries\n"
    printf "  compare     - Compare with props collection\n"
    printf "\n"
    printf "Options:\n"
    printf "  --no-color  - Disable colored output\n"
    printf "\n"
    printf "Examples:\n"
    printf "  $0 quick             # Quick status\n"
    printf "  $0 watch             # Continuous monitoring\n"
    printf "  $0 logs 20           # Show 20 recent logs\n"
    printf "  $0 compare           # Compare with props\n"
    printf "  $0 status --no-color # Status without colors\n"
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
    "compare")
        cmd_compare
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