#!/bin/bash
# File: bin/backfill/nbac_injury_monitor.sh
# Purpose: OPTIMIZED monitoring for NBA Injury Reports backfill process  
# Usage: ./bin/backfill/nbac_injury_monitor.sh [command] [options]
# Updated: August 2025 - Injury reports pattern discovery and validation

set -e

PROJECT="nba-props-platform"
REGION="us-west2"
JOB_NAME="nba-injury-backfill"

# Performance settings
TIMEOUT_SHORT=15  # For quick operations
TIMEOUT_LONG=30   # For heavy operations
CACHE_DIR="/tmp/nba_injury_monitor_cache"
CACHE_TTL=300     # 5 minutes cache

# GCS bucket paths for injury reports
GCS_INJURY_PATH="gs://nba-scraped-data/nba-com/injury-report"
GCS_SCHEDULE_PATH="gs://nba-scraped-data/nba-com/schedule"
GCS_SCHEDULE_METADATA_PATH="gs://nba-scraped-data/nba-com/schedule-metadata"

# Seasons to monitor
SEASONS_TO_MONITOR=("2021-22" "2022-23" "2023-24" "2024-25")

# Injury report collection parameters
INTERVALS_PER_DAY=48  # Every 30 minutes
EXPECTED_COVERAGE_PCT=30  # We expect 30% success rate (reports aren't always available)

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
    echo -e "${CYAN}🏥 NBA INJURY REPORTS BACKFILL MONITOR${NC}"
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

# Count game dates from schedule metadata
calculate_expected_totals() {
    local cache_key="injury_expected_totals"
    local cache_file="$CACHE_DIR/${cache_key}.cache"
    local cache_time_file="$CACHE_DIR/${cache_key}.time"
    
    # Check cache validity
    if [[ -f "$cache_file" && -f "$cache_time_file" ]]; then
        local cache_time=$(cat "$cache_time_file" 2>/dev/null || echo "0")
        local current_time=$(date +%s)
        local age=$((current_time - cache_time))
        
        if [[ $age -lt $CACHE_TTL ]]; then
            cat "$cache_file"
            return 0
        fi
    fi
    
    echo -e "${BLUE}📊 Calculating expected totals from schedule metadata...${NC}"
    
    local total_game_dates=0
    local total_intervals=0
    local successful_seasons=0
    
    for season in "${SEASONS_TO_MONITOR[@]}"; do
        # Quick metadata check with timeout
        local metadata_files=""
        if metadata_files=$(timeout $TIMEOUT_SHORT gcloud storage ls "${GCS_SCHEDULE_METADATA_PATH}/${season}/*.json" 2>/dev/null | head -1); then
            if [[ -n "$metadata_files" ]]; then
                local temp_file="/tmp/injury_metadata_${season}_$$"
                if timeout $TIMEOUT_SHORT gcloud storage cp "$metadata_files" "$temp_file" 2>/dev/null; then
                    # Extract unique game dates (backfill.total_games represents completed games with unique dates)
                    local season_game_dates=$(jq -r '.backfill.total_games // 0' "$temp_file" 2>/dev/null || echo "0")
                    
                    if [[ "$season_game_dates" -gt 0 ]]; then
                        # For injury reports, we need to count unique game dates, not individual games
                        # Estimate unique dates as roughly total_games / 8 (average games per day)
                        local estimated_dates=$((season_game_dates / 8))
                        if [[ $estimated_dates -lt 100 ]]; then
                            estimated_dates=150  # Minimum reasonable estimate for a season
                        fi
                        
                        local season_intervals=$((estimated_dates * INTERVALS_PER_DAY))
                        total_game_dates=$((total_game_dates + estimated_dates))
                        total_intervals=$((total_intervals + season_intervals))
                        successful_seasons=$((successful_seasons + 1))
                        
                        echo -e "  ✅ ${season}: ~${estimated_dates} game dates → ${season_intervals} intervals"
                    fi
                    rm -f "$temp_file"
                fi
            fi
        fi
    done
    
    # Handle fallback
    if [[ $successful_seasons -eq 0 ]]; then
        echo -e "  ${RED}⚠️  No metadata available, using estimates${NC}"
        total_game_dates=600  # ~150 dates per season * 4 seasons
        total_intervals=$((total_game_dates * INTERVALS_PER_DAY))
    else
        echo -e "  ${GREEN}✅ Loaded $successful_seasons seasons${NC}"
    fi
    
    local result="$total_game_dates,$total_intervals"
    echo "$result" > "$CACHE_DIR/${cache_key}.cache"
    date +%s > "$CACHE_DIR/${cache_key}.time"
    echo "$result"
}

# Fast injury report counting using sampling
count_injury_files_fast() {
    local cache_key="injury_file_count"
    
    echo -e "  ${BLUE}🔍 Sampling injury report directories...${NC}" >&2
    
    # Strategy: Count date directories and sample recent ones for file estimates
    local date_dirs=""
    if date_dirs=$(timeout $TIMEOUT_SHORT gcloud storage ls "$GCS_INJURY_PATH/" 2>/dev/null); then
        local total_date_dirs=$(echo "$date_dirs" | grep -E "/[0-9]{4}-[0-9]{2}-[0-9]{2}/$" | wc -l | tr -d ' ')
        
        if [[ $total_date_dirs -gt 0 ]]; then
            # Sample recent dates to estimate files per date
            local sample_dates=$(echo "$date_dirs" | grep -E "/[0-9]{4}-[0-9]{2}-[0-9]{2}/$" | tail -5)
            local sample_file_count=0
            local sample_size=0
            
            while IFS= read -r date_dir && [[ $sample_size -lt 3 ]]; do
                if [[ -n "$date_dir" ]]; then
                    local date_files=""
                    if date_files=$(timeout $TIMEOUT_SHORT gcloud storage ls "${date_dir}**/*.pdf" "${date_dir}**/*.json" 2>/dev/null); then
                        local date_count=$(echo "$date_files" | wc -l | tr -d ' ')
                        sample_file_count=$((sample_file_count + date_count))
                        sample_size=$((sample_size + 1))
                    fi
                fi
            done <<< "$sample_dates"
            
            if [[ $sample_size -gt 0 ]]; then
                # Estimate total files
                local avg_per_date=$((sample_file_count / sample_size))
                local estimated_total=$((avg_per_date * total_date_dirs))
                
                echo -e "  ${GREEN}📊 Estimated: ~$estimated_total files across $total_date_dirs dates${NC}" >&2
                echo "$estimated_total"
                return 0
            fi
        fi
    fi
    
    echo -e "  ${YELLOW}⚠️  Sampling failed, checking for any files...${NC}" >&2
    
    # Fallback: quick check for existence
    local any_files=""
    if any_files=$(timeout $TIMEOUT_SHORT gcloud storage ls "$GCS_INJURY_PATH/**/*.pdf" 2>/dev/null | head -10); then
        local quick_count=$(echo "$any_files" | wc -l | tr -d ' ')
        echo $((quick_count * 10))  # Rough extrapolation
    else
        echo "0"
    fi
}

# Calculate progress for injury reports
calculate_injury_progress_fast() {
    echo -e "${BLUE}📊 Injury Reports Progress Analysis:${NC}"
    
    # Get expected totals
    local totals_line=$(calculate_expected_totals 2>/dev/null | tail -1)
    IFS=',' read -r EXPECTED_DATES EXPECTED_INTERVALS <<< "$totals_line"
    
    echo ""
    
    # Get current file counts
    local current_files=$(count_injury_files_fast)
    
    if [[ "$current_files" -gt 0 && "$EXPECTED_INTERVALS" -gt 0 ]]; then
        # Calculate progress percentages
        local progress_pct=$((current_files * 100 / EXPECTED_INTERVALS))
        local remaining=$((EXPECTED_INTERVALS - current_files))
        
        echo -e "${PURPLE}🏥 INJURY REPORTS PROGRESS:${NC}"
        echo -e "  📄 Files collected: ${GREEN}$current_files${NC} / ~$EXPECTED_INTERVALS intervals"
        echo -e "  📊 Progress: ${CYAN}$progress_pct%${NC} complete - ~$remaining remaining"
        echo -e "  🎯 Expected dates: ~$EXPECTED_DATES game dates"
        echo -e "  ⏰ Strategy: $INTERVALS_PER_DAY intervals per date (30-minute sampling)"
        
        # Pattern discovery info
        if [[ $progress_pct -gt 10 ]]; then
            echo ""
            echo -e "${YELLOW}📈 Pattern Discovery:${NC}"
            echo -e "  ✅ Sufficient data for pattern analysis"
            echo -e "  💡 Run full analysis to find optimal collection times"
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
                
                if [[ $elapsed_seconds -gt 0 && $current_files -gt 0 ]]; then
                    local rate=$(echo "scale=1; $current_files * 3600 / $elapsed_seconds" | bc -l 2>/dev/null || echo "0")
                    local eta_hours=$(echo "scale=1; $remaining / $rate" | bc -l 2>/dev/null || echo "0")
                    echo -e "  ⏱️  Current rate: ${CYAN}$rate intervals/hour${NC}, ETA: ${PURPLE}$eta_hours hours${NC}"
                fi
            fi
        fi
    else
        echo -e "  ${YELLOW}No injury report files found yet${NC}"
        echo -e "  🎯 Expected to collect: ~$EXPECTED_INTERVALS total intervals"
        echo -e "  📅 Across: ~$EXPECTED_DATES game dates"
    fi
}

# Pattern analysis for injury reports
analyze_injury_patterns() {
    echo -e "${BLUE}📈 INJURY REPORT PATTERN ANALYSIS:${NC}"
    echo ""
    
    # Sample recent data to find successful times
    local recent_dirs=""
    if recent_dirs=$(timeout $TIMEOUT_LONG gcloud storage ls "$GCS_INJURY_PATH/" | grep -E "/[0-9]{4}-[0-9]{2}-[0-9]{2}/$" | tail -10 2>/dev/null); then
        
        declare -A time_success
        declare -A time_total
        local analyzed_dates=0
        
        while IFS= read -r date_dir && [[ $analyzed_dates -lt 5 ]]; do
            if [[ -n "$date_dir" ]]; then
                # List hourly directories for this date
                local hour_dirs=""
                if hour_dirs=$(timeout $TIMEOUT_SHORT gcloud storage ls "$date_dir" 2>/dev/null); then
                    while IFS= read -r hour_dir; do
                        if [[ -n "$hour_dir" ]]; then
                            # Extract hour and period from path
                            local hour_period=$(basename "$hour_dir")
                            if [[ $hour_period =~ ^([0-9]{1,2})(AM|PM)$ ]]; then
                                local hour=${BASH_REMATCH[1]}
                                local period=${BASH_REMATCH[2]}
                                local time_key="${hour}:00 ${period}"
                                
                                # Check if files exist in this hour directory
                                local files=""
                                if files=$(timeout $TIMEOUT_SHORT gcloud storage ls "${hour_dir}*.pdf" "${hour_dir}*.json" 2>/dev/null); then
                                    if [[ -n "$files" ]]; then
                                        time_success["$time_key"]=$((${time_success["$time_key"]:-0} + 1))
                                    fi
                                fi
                                time_total["$time_key"]=$((${time_total["$time_key"]:-0} + 1))
                            fi
                        fi
                    done <<< "$hour_dirs"
                fi
                analyzed_dates=$((analyzed_dates + 1))
            fi
        done <<< "$recent_dirs"
        
        if [[ $analyzed_dates -gt 0 ]]; then
            echo -e "  ${GREEN}✅ Analyzed $analyzed_dates recent dates${NC}"
            echo ""
            echo -e "${CYAN}🕐 Times with reports found:${NC}"
            
            # Sort times and show successful ones
            local found_patterns=false
            for time_key in $(printf '%s\n' "${!time_total[@]}" | sort); do
                local success=${time_success["$time_key"]:-0}
                local total=${time_total["$time_key"]:-0}
                if [[ $success -gt 0 && $total -gt 0 ]]; then
                    local success_rate=$((success * 100 / total))
                    echo -e "    ${time_key}: ${GREEN}${success}/${total}${NC} (${success_rate}%)"
                    found_patterns=true
                fi
            done
            
            if [[ "$found_patterns" == "false" ]]; then
                echo -e "    ${YELLOW}No consistent patterns found yet${NC}"
                echo -e "    ${YELLOW}💡 More data needed for pattern discovery${NC}"
            fi
        else
            echo -e "  ${YELLOW}⚠️  Insufficient data for pattern analysis${NC}"
        fi
    else
        echo -e "  ${RED}❌ Unable to access injury report data${NC}"
    fi
}

# Validation specific to injury reports
cmd_validate_injury_reports() {
    local count=${1:-3}
    
    print_header
    echo -e "${BLUE}🔍 Injury Reports Validation (last $count dates):${NC}"
    echo ""
    
    # Get recent date directories
    local recent_dates=""
    if recent_dates=$(timeout $TIMEOUT_SHORT gcloud storage ls "$GCS_INJURY_PATH/" | grep -E "/[0-9]{4}-[0-9]{2}-[0-9]{2}/$" | tail -$count 2>/dev/null); then
        
        local validated=0
        local good_dates=0
        
        while IFS= read -r date_dir && [[ $validated -lt $count ]]; do
            if [[ -n "$date_dir" ]]; then
                validated=$((validated + 1))
                local date_name=$(basename "$date_dir")
                echo -e "${BLUE}[$validated/$count]${NC} Checking $date_name:"
                
                # Count files for this date
                local pdf_files=""
                local json_files=""
                if pdf_files=$(timeout $TIMEOUT_SHORT gcloud storage ls "${date_dir}**/*.pdf" 2>/dev/null); then
                    local pdf_count=$(echo "$pdf_files" | wc -l | tr -d ' ')
                    local pdf_count=${pdf_count:-0}
                    
                    if json_files=$(timeout $TIMEOUT_SHORT gcloud storage ls "${date_dir}**/*.json" 2>/dev/null); then
                        local json_count=$(echo "$json_files" | wc -l | tr -d ' ')
                        local json_count=${json_count:-0}
                        
                        local total_files=$((pdf_count + json_count))
                        
                        if [[ $total_files -gt 0 ]]; then
                            echo -e "  ${GREEN}✅ GOOD${NC} - Files: ${GREEN}$total_files${NC} (${pdf_count} PDFs, ${json_count} JSON)"
                            
                            # Check for pattern coverage (should have multiple time intervals)
                            local hour_dirs=""
                            if hour_dirs=$(timeout $TIMEOUT_SHORT gcloud storage ls "$date_dir" 2>/dev/null); then
                                local interval_count=$(echo "$hour_dirs" | wc -l | tr -d ' ')
                                if [[ $interval_count -gt 5 ]]; then
                                    echo -e "    ${GREEN}📊 Good coverage: $interval_count time intervals${NC}"
                                else
                                    echo -e "    ${YELLOW}⚠️  Low coverage: $interval_count time intervals${NC}"
                                fi
                            fi
                            
                            good_dates=$((good_dates + 1))
                        else
                            echo -e "  ${YELLOW}⚠️  EMPTY${NC} - No files found"
                        fi
                    else
                        echo -e "  ${RED}❌ Access failed${NC}"
                    fi
                else
                    echo -e "  ${YELLOW}⚠️  NO PDFs${NC} - May be normal (no reports released)"
                fi
            fi
        done <<< "$recent_dates"
        
        echo ""
        echo -e "${CYAN}📊 Validation Summary:${NC}"
        echo -e "  ${GREEN}✅ Dates with data: $good_dates / $validated${NC}"
        
        if [[ $good_dates -eq $validated && $good_dates -gt 0 ]]; then
            echo -e "  ${GREEN}🎉 Validation passed - collection working correctly${NC}"
        elif [[ $good_dates -gt 0 ]]; then
            echo -e "  ${YELLOW}⚠️  Partial success - some dates have data${NC}"
        else
            echo -e "  ${RED}❌ No data found - check collection process${NC}"
        fi
    else
        echo -e "${RED}❌ Failed to list date directories${NC}"
    fi
}

# Import common functions from gamebook monitor
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
                        # Additional check: if job has been running > 24 hours, it's likely stuck
                        if [[ -n "$creation_time" ]]; then
                            local start_epoch=$(parse_iso_timestamp "$creation_time")
                            local current_epoch=$(date +%s)
                            local elapsed_hours=$(( (current_epoch - start_epoch) / 3600 ))
                            
                            if [[ $elapsed_hours -gt 24 ]]; then
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
        "resource.type=cloud_run_job AND (textPayload:\"Downloaded\" OR textPayload:\"Progress\" OR textPayload:\"❌\" OR textPayload:\"No report\")" \
        --limit=$limit \
        --format="value(timestamp,textPayload)" \
        --project=$PROJECT \
        --freshness=30m 2>/dev/null | head -$limit
}

# Command implementations adapted for injury reports
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
    calculate_injury_progress_fast
}

cmd_patterns() {
    print_header
    analyze_injury_patterns
}

cmd_quick_injury() {
    # Check running status (fast)
    local running_exec=""
    if running_exec=$(timeout $TIMEOUT_SHORT gcloud run jobs executions list \
        --job=$JOB_NAME \
        --region=$REGION \
        --format="value(metadata.name)" \
        --limit=1 2>/dev/null); then
        
        if [[ -n "$running_exec" ]]; then
            local execution_check=$(find_running_execution)
            
            if [[ "$execution_check" =~ ^STUCK: ]]; then
                local stuck_name=$(echo "$execution_check" | cut -d: -f2)
                local stuck_hours=$(echo "$execution_check" | cut -d: -f3)
                echo "Status: STUCK ($stuck_name) - ${stuck_hours}h elapsed"
                echo "⚠️  Job appears stuck - consider stopping it manually"
                return 0
            elif [[ -n "$execution_check" ]]; then
                echo "Status: RUNNING ($execution_check)"
            else
                echo "Status: NO ACTIVE JOBS"
            fi
        else
            echo "Status: NO ACTIVE JOBS"
        fi
    else
        echo "Status: UNKNOWN (timeout)"
    fi
    
    # Fast progress check
    local totals_line=$(calculate_expected_totals 2>/dev/null | tail -1)
    IFS=',' read -r EXPECTED_DATES EXPECTED_INTERVALS <<< "$totals_line"
    
    local current_files=$(count_injury_files_fast)
    if [[ "$current_files" -gt 0 && "$EXPECTED_INTERVALS" -gt 0 ]]; then
        local progress_pct=$((current_files * 100 / EXPECTED_INTERVALS))
        echo "Progress: $current_files / $EXPECTED_INTERVALS intervals ($progress_pct% complete)"
        echo "Strategy: 30-minute interval sampling across ~$EXPECTED_DATES dates"
    else
        echo "Progress: Data collection not started yet"
    fi
}

cmd_clear_cache() {
    echo -e "${BLUE}🧹 Clearing injury reports monitor cache...${NC}"
    rm -rf "$CACHE_DIR"
    mkdir -p "$CACHE_DIR"
    echo -e "${GREEN}✅ Cache cleared${NC}"
}

show_execution_status() {
    echo -e "${BLUE}🏃 Recent Executions:${NC}"
    
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
            echo -e "${YELLOW}⚠️  Recommendation: Cancel the stuck job and restart${NC}"
        elif [[ -n "$execution_check" ]]; then
            echo -e "${GREEN}🔥 Currently Running: $execution_check${NC}"
        else
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

# Fix for the check_activity_health() function in nbac_injury_monitor.sh
check_activity_health() {
    echo -e "${BLUE}🏥 Activity Health:${NC}"
    
    local recent_logs=""
    if recent_logs=$(get_recent_logs 10 | cut -f2 2>/dev/null); then
        if [[ -n "$recent_logs" ]]; then
            # FIX: Clean the variables and ensure they're single numbers
            local recent_downloads=$(echo "$recent_logs" | grep -c "✅ Downloaded" 2>/dev/null || echo "0")
            local recent_no_reports=$(echo "$recent_logs" | grep -c "No report" 2>/dev/null || echo "0")
            local recent_errors=$(echo "$recent_logs" | grep -c -E "(❌|ERROR)" 2>/dev/null || echo "0")
            
            # CRITICAL FIX: Clean variables to ensure they're single numbers
            recent_downloads=$(echo "$recent_downloads" | tail -1 | tr -d '\n' | sed 's/[^0-9]//g')
            recent_no_reports=$(echo "$recent_no_reports" | tail -1 | tr -d '\n' | sed 's/[^0-9]//g')
            recent_errors=$(echo "$recent_errors" | tail -1 | tr -d '\n' | sed 's/[^0-9]//g')
            
            # Set defaults if empty
            recent_downloads=${recent_downloads:-0}
            recent_no_reports=${recent_no_reports:-0}
            recent_errors=${recent_errors:-0}
            
            echo -e "  Recent activity (last 10 logs):"
            echo -e "    Downloads: ${GREEN}$recent_downloads${NC}"
            echo -e "    No reports: ${YELLOW}$recent_no_reports${NC}"
            echo -e "    Errors: ${RED}$recent_errors${NC}"
            
            local total_attempts=$((recent_downloads + recent_no_reports + recent_errors))
            if [[ $total_attempts -gt 0 ]]; then
                local success_rate=$(( (recent_downloads + recent_no_reports) * 100 / total_attempts ))
                echo -e "    Success rate: ${CYAN}${success_rate}%${NC} (including 'no report' as success)"
            fi
            
            if [[ $recent_downloads -gt 0 ]]; then
                echo -e "  ${GREEN}✅ Active - Reports being found${NC}"
            elif [[ $recent_no_reports -gt 0 ]]; then
                echo -e "  ${YELLOW}⚠️  Active but no reports available (normal for some times)${NC}"
            elif [[ $recent_errors -gt 0 ]]; then
                echo -e "  ${YELLOW}⚠️  Issues detected${NC}"
            else
                echo -e "  ${YELLOW}⚠️  No recent activity${NC}"
            fi
        else
            echo -e "  ${YELLOW}⚠️  No recent logs found${NC}"
        fi
    else
        echo -e "  ${RED}❌ Failed to get recent logs (timeout)${NC}"
    fi
}

cmd_watch() {
    echo -e "${GREEN}Starting continuous injury reports monitoring (Ctrl+C to stop)...${NC}"
    
    while true; do
        clear
        cmd_quick_injury
        echo ""
        echo -e "${YELLOW}Next update in 60 seconds... (Ctrl+C to stop)${NC}"
        sleep 60
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

cmd_tail_logs() {
    echo -e "${GREEN}Watching injury backfill logs in real-time (Ctrl+C to stop)...${NC}"
    gcloud logging tail "resource.type=cloud_run_job AND resource.labels.job_name=nba-injury-backfill" \
        --location=$REGION \
        --format="value(timestamp,textPayload)" \
        2>/dev/null | while read line; do
            # Color code the output based on content
            if echo "$line" | grep -q "✅"; then
                echo -e "${GREEN}$line${NC}"
            elif echo "$line" | grep -q "❌\|ERROR"; then
                echo -e "${RED}$line${NC}"
            elif echo "$line" | grep -q "⏰\|TIMEOUT"; then
                echo -e "${YELLOW}$line${NC}"
            else
                echo "$line"
            fi
        done
}

# 2. Add success rate trending over time
track_success_rate_trend() {
    # Store hourly success rates in cache for trending
    local hour_key=$(date +"%Y%m%d_%H")
    local trend_file="$CACHE_DIR/success_trend.log"
    
    # Calculate current success rate and append to trend file
    local recent_logs=$(get_recent_logs 20 | cut -f2 2>/dev/null)
    if [[ -n "$recent_logs" ]]; then
        local downloads=$(echo "$recent_logs" | grep -c "✅ Downloaded" 2>/dev/null || echo "0")
        local no_reports=$(echo "$recent_logs" | grep -c "No report" 2>/dev/null || echo "0")
        local errors=$(echo "$recent_logs" | grep -c -E "(❌|ERROR)" 2>/dev/null || echo "0")
        local total=$((downloads + no_reports + errors))
        
        if [[ $total -gt 0 ]]; then
            local success_rate=$(( (downloads + no_reports) * 100 / total ))
            echo "$hour_key,$success_rate,$downloads,$no_reports,$errors" >> "$trend_file"
        fi
    fi
}

# 3. Add an alert mode for when success rate drops
cmd_health_check() {
    # This could be called by monitoring systems
    local recent_logs=$(get_recent_logs 20 | cut -f2 2>/dev/null)
    if [[ -n "$recent_logs" ]]; then
        local downloads=$(echo "$recent_logs" | grep -c "✅ Downloaded" 2>/dev/null || echo "0")
        local errors=$(echo "$recent_logs" | grep -c -E "(❌|ERROR)" 2>/dev/null || echo "0")
        local total=$(echo "$recent_logs" | wc -l)
        
        if [[ $total -gt 5 && $errors -gt $((total / 2)) ]]; then
            echo "UNHEALTHY: High error rate ($errors/$total)"
            exit 1
        else
            echo "HEALTHY: Error rate acceptable ($errors/$total)"
            exit 0
        fi
    else
        echo "UNKNOWN: No recent logs"
        exit 2
    fi
}

show_usage() {
    echo "Usage: $0 [command]"
    echo ""
    echo "INJURY REPORTS Commands:"
    echo "  quick          - Super fast status with cached progress"
    echo "  status         - Comprehensive status overview"
    echo "  progress       - Detailed progress analysis"
    echo "  patterns       - Analyze injury report release patterns"
    echo "  validate       - Validate recent injury report data"
    echo "  clear-cache    - Clear all cached data"
    echo ""
    echo "Standard Commands:"
    echo "  watch          - Continuous monitoring"
    echo "  logs [N]       - Show last N log lines"
    echo ""
    echo "Notes:"
    echo "  - Injury reports use 30-minute interval strategy"
    echo "  - Expected success rate: ~30% (reports not always available)"
    echo "  - Pattern analysis helps optimize future collection"
    echo "Advanced Commands:"
    echo "  tail           - Watch logs in real-time with color coding"
    echo "  health         - Health check for monitoring systems (exit codes)"
    echo "  trend          - Show success rate trends over time"
}

# Main command handling
case "${1:-quick}" in
    "status")
        cmd_status
        ;;
    "progress")
        cmd_progress
        ;;
    "patterns")
        cmd_patterns
        ;;
    "watch")
        cmd_watch
        ;;
    "quick"|"")
        cmd_quick_injury
        ;;
    "validate")
        cmd_validate_injury_reports "$2"
        ;;
    "clear-cache")
        cmd_clear_cache
        ;;
    "logs")
        cmd_logs "$2"
        ;;
    "help"|"-h"|"--help")
        show_usage
        ;;
    "tail"|"tail-logs")
        cmd_tail_logs
        ;;
    "health")
        cmd_health_check
        ;;
    "trend")
        track_success_rate_trend
        show_success_trend
        ;;
    *)
        echo "Unknown command: $1"
        show_usage
        exit 1
        ;;
esac