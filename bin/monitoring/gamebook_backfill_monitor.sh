#!/bin/bash
# File: bin/monitoring/nba_backfill_monitor.sh
# Purpose: Complete fixed monitoring for NBA Gamebook backfill process
# Usage: ./nba_backfill_monitor.sh [command] [options]
# Updated: August 2025 - Added dynamic metadata for accurate game totals

set -e

PROJECT="nba-props-platform"
REGION="us-west2"
JOB_NAME="nba-gamebook-backfill"

# Fallback total games (only used if metadata reading fails)
FALLBACK_TOTAL_GAMES=5583

# GCS bucket paths
GCS_DATA_PATH="gs://nba-scraped-data/nba-com/gamebooks-data"
GCS_PDF_PATH="gs://nba-scraped-data/nba-com/gamebooks-pdf"
GCS_METADATA_PATH="gs://nba-scraped-data/nba-com/schedule-metadata"

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

print_header() {
    echo -e "${CYAN}================================================${NC}"
    echo -e "${CYAN}🏀 NBA GAMEBOOK BACKFILL MONITOR${NC}"
    echo -e "${CYAN}================================================${NC}"
    echo -e "Time: $(date)"
    echo ""
}

# NEW: Dynamic metadata reading function
calculate_expected_games_from_metadata() {
    echo -e "${BLUE}📊 Reading season metadata for game totals...${NC}"
    
    local total_expected_games=0
    local successful_seasons=()
    local failed_seasons=()
    
    for season in "${SEASONS_TO_MONITOR[@]}"; do
        # Find the latest metadata file for this season
        local metadata_path=$(find_latest_metadata_file "$season")
        
        if [[ -n "$metadata_path" ]]; then
            # Download and parse metadata
            local temp_file="/tmp/metadata_${season}_$$"
            if gcloud storage cp "$metadata_path" "$temp_file" 2>/dev/null; then
                
                # Extract backfill total from metadata JSON
                local backfill_games=$(jq -r '.backfill.total_games // 0' "$temp_file" 2>/dev/null || echo "0")
                
                if [[ "$backfill_games" -gt 0 ]]; then
                    total_expected_games=$((total_expected_games + backfill_games))
                    successful_seasons+=("$season")
                    echo -e "  ✅ ${season}: ${GREEN}${backfill_games}${NC} backfill games"
                else
                    failed_seasons+=("$season")
                    echo -e "  ❌ ${season}: Invalid metadata (backfill_games=${backfill_games})"
                fi
                
                rm -f "$temp_file"
            else
                failed_seasons+=("$season")
                echo -e "  ❌ ${season}: Failed to download metadata"
            fi
        else
            failed_seasons+=("$season")
            echo -e "  ❌ ${season}: No metadata found"
        fi
    done
    
    # Handle fallback logic
    if [[ ${#successful_seasons[@]} -eq 0 ]]; then
        echo -e "  ${RED}⚠️  No season metadata found! Falling back to hardcoded estimate.${NC}"
        echo -e "  ${YELLOW}Fallback total: ${FALLBACK_TOTAL_GAMES} games${NC}"
        echo "$FALLBACK_TOTAL_GAMES"
    elif [[ ${#failed_seasons[@]} -gt 0 ]]; then
        echo -e "  ${YELLOW}⚠️  Some seasons failed (${failed_seasons[*]}), but continuing with partial data${NC}"
        echo -e "  ${GREEN}Total expected games: ${total_expected_games}${NC}"
        echo "$total_expected_games"
    else
        echo -e "  ${GREEN}✅ All metadata loaded successfully${NC}"
        echo -e "  ${GREEN}Total expected games: ${total_expected_games}${NC}"
        echo "$total_expected_games"
    fi
}

# NEW: Find latest metadata file for a season
find_latest_metadata_file() {
    local season="$1"
    
    # List all metadata files for this season
    local metadata_files=$(gcloud storage ls "${GCS_METADATA_PATH}/${season}/*.json" 2>/dev/null | sort -r)
    
    if [[ -n "$metadata_files" ]]; then
        # Return the latest file (first after reverse sort)
        echo "$metadata_files" | head -1
    else
        echo ""
    fi
}

# FIXED: Simplified date parsing with better timezone handling
parse_iso_timestamp() {
    local iso_time="$1"
    
    if [[ -n "$iso_time" ]]; then
        # Remove microseconds: 2025-08-08T20:39:48.375318Z -> 2025-08-08T20:39:48Z
        local clean_time=$(echo "$iso_time" | sed 's/\.[0-9]*Z$/Z/')
        
        # Try different parsing methods
        local epoch=""
        
        # Method 1: BSD date with UTC timezone (macOS)
        epoch=$(TZ=UTC date -j -f "%Y-%m-%dT%H:%M:%SZ" "$clean_time" "+%s" 2>/dev/null || echo "")
        
        # Method 2: GNU date (Linux)
        if [[ -z "$epoch" ]]; then
            epoch=$(date -d "$clean_time" +%s 2>/dev/null || echo "")
        fi
        
        # Method 3: Convert Z to +0000 format and try again
        if [[ -z "$epoch" ]]; then
            local alt_time=$(echo "$clean_time" | sed 's/Z$/+0000/')
            epoch=$(date -j -f "%Y-%m-%dT%H:%M:%S%z" "$alt_time" "+%s" 2>/dev/null || echo "")
        fi
        
        # Verify the result is reasonable (should be a recent timestamp)
        if [[ -n "$epoch" && "$epoch" -gt 1700000000 ]]; then
            echo "$epoch"
        else
            echo ""
        fi
    else
        echo ""
    fi
}

# FIXED: Calculate elapsed time with proper date parsing
calculate_elapsed_time() {
    local start_time="$1"
    local start_epoch=$(parse_iso_timestamp "$start_time")
    local current_epoch=$(date +%s)
    
    if [[ -n "$start_epoch" && "$start_epoch" -gt 0 ]]; then
        local duration_seconds=$((current_epoch - start_epoch))
        local duration_hours=$((duration_seconds / 3600))
        local duration_minutes=$(((duration_seconds % 3600) / 60))
        echo "${duration_hours}h ${duration_minutes}m"
    else
        echo ""
    fi
}

# ENHANCED: Find running execution with better detection
find_running_execution() {
    # Method 1: Check recent executions for running status
    local executions=$(gcloud run jobs executions list \
        --job=$JOB_NAME \
        --region=$REGION \
        --format="value(metadata.name)" \
        --limit=5 2>/dev/null)
    
    # Check each execution to see if it's running
    while IFS= read -r exec_name; do
        if [[ -n "$exec_name" ]]; then
            local status=$(gcloud run jobs executions describe "$exec_name" \
                --region=$REGION \
                --format="value(status.conditions[0].type)" 2>/dev/null)
            
            # Check for running indicators
            if [[ "$status" == "Succeeded" || "$status" == "Completed" ]]; then
                continue
            elif [[ "$status" == "Failed" ]]; then
                continue
            else
                # If not succeeded or failed, likely running
                echo "$exec_name"
                return 0
            fi
        fi
    done <<< "$executions"
    
    # Method 2: Check for recent log activity (backup detection)
    local recent_activity=$(gcloud logging read \
        "resource.type=cloud_run_job AND textPayload:\"Downloaded\"" \
        --limit=5 \
        --format="value(textPayload)" \
        --project=$PROJECT \
        --freshness=5m 2>/dev/null)
    
    if [[ -n "$recent_activity" ]]; then
        # If there's recent activity, assume the latest execution is running
        local latest_exec=$(gcloud run jobs executions list \
            --job=$JOB_NAME \
            --region=$REGION \
            --format="value(metadata.name)" \
            --limit=1 2>/dev/null)
        echo "$latest_exec"
        return 0
    fi
    
    return 1
}

# ENHANCED: Get recent logs with better filtering
get_recent_logs() {
    local limit=${1:-20}
    gcloud logging read \
        "resource.type=cloud_run_job AND (textPayload:\"Downloaded\" OR textPayload:\"Progress\" OR textPayload:\"❌\" OR textPayload:\"ERROR\" OR textPayload:\"CRITICAL\")" \
        --limit=$limit \
        --format="value(timestamp,textPayload)" \
        --project=$PROJECT \
        --freshness=30m 2>/dev/null | \
        head -$limit
}

# ENHANCED: Show execution status with better formatting
show_execution_status() {
    echo -e "${BLUE}🏃 Recent Executions:${NC}"
    
    # Show execution list with status
    gcloud run jobs executions list \
        --job=$JOB_NAME \
        --region=$REGION \
        --limit=5 \
        --format="table(
            metadata.name:label=EXECUTION,
            status.conditions[0].type:label=STATUS,
            metadata.creationTimestamp:label=CREATED
        )" 2>/dev/null
    
    echo ""
    
    # Find running executions
    local running_exec=$(find_running_execution)
    
    if [[ -n "$running_exec" ]]; then
        echo -e "${GREEN}🔥 Currently Running: $running_exec${NC}"
        
        # Calculate and show runtime using fixed date parsing
        local start_time=$(gcloud run jobs executions describe "$running_exec" \
            --region=$REGION \
            --format="value(metadata.creationTimestamp)" 2>/dev/null)
        
        if [[ -n "$start_time" ]]; then
            local elapsed=$(calculate_elapsed_time "$start_time")
            if [[ -n "$elapsed" ]]; then
                echo -e "  Runtime: ${PURPLE}${elapsed}${NC}"
            fi
        fi
    else
        echo -e "${YELLOW}No currently running executions detected${NC}"
    fi
}

# ENHANCED: Activity health check with parser fix validation
check_activity_health() {
    echo -e "${BLUE}🏥 Activity Health:${NC}"
    
    local recent_logs=$(get_recent_logs 10 | cut -f2)
    if [[ -z "$recent_logs" ]]; then
        echo -e "  ${RED}❌ No recent logs found${NC}"
        return
    fi
    
    # Count recent activity
    local recent_downloads=$(echo "$recent_logs" | grep "✅ Downloaded" | wc -l)
    local recent_errors=$(echo "$recent_logs" | grep -E "(❌|ERROR|CRITICAL)" | wc -l)
    
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
}

# ENHANCED: Calculate progress based on actual GCS files with dynamic totals
calculate_gcs_progress() {
    echo -e "${BLUE}📊 GCS Progress Analysis:${NC}"
    
    # Get dynamic total games from metadata
    local TOTAL_GAMES=$(calculate_expected_games_from_metadata)
    echo ""
    
    # Count actual files in GCS
    local json_count=$(gcloud storage ls "$GCS_DATA_PATH/**/*.json" 2>/dev/null | wc -l | tr -d ' ')
    local pdf_count=$(gcloud storage ls "$GCS_PDF_PATH/**/*.pdf" 2>/dev/null | wc -l | tr -d ' ')
    
    if [[ "$json_count" -gt 0 ]]; then
        local json_pct=$((json_count * 100 / TOTAL_GAMES))
        local pdf_pct=$((pdf_count * 100 / TOTAL_GAMES))
        
        echo -e "  📄 JSON files: ${GREEN}$json_count${NC} / $TOTAL_GAMES (${GREEN}$json_pct%${NC})"
        echo -e "  📋 PDF files: ${GREEN}$pdf_count${NC} / $TOTAL_GAMES (${GREEN}$pdf_pct%${NC})"
        
        # Calculate ETA if we have a running job
        local running_exec=$(find_running_execution)
        if [[ -n "$running_exec" ]]; then
            local start_time=$(gcloud run jobs executions describe "$running_exec" \
                --region=$REGION \
                --format="value(metadata.creationTimestamp)" 2>/dev/null)
            
            if [[ -n "$start_time" ]]; then
                local start_epoch=$(parse_iso_timestamp "$start_time")
                local current_epoch=$(date +%s)
                local elapsed_seconds=$((current_epoch - start_epoch))
                
                if [[ $elapsed_seconds -gt 0 && $json_count -gt 0 ]]; then
                    local rate=$(echo "scale=1; $json_count * 3600 / $elapsed_seconds" | bc -l 2>/dev/null || echo "0")
                    local remaining=$((TOTAL_GAMES - json_count))
                    local eta_hours=$(echo "scale=1; $remaining / $rate" | bc -l 2>/dev/null || echo "0")
                    
                    echo -e "  ⏱️  Processing rate: ${CYAN}$rate games/hour${NC}"
                    echo -e "  🎯 ETA: ${PURPLE}$eta_hours hours${NC} remaining"
                fi
            fi
        fi
    else
        echo -e "  ${YELLOW}No files found in GCS yet${NC}"
    fi
}

# Enhanced error analysis with retry detection (bash 3.x compatible)
analyze_nba_errors() {
    local timeframe="${1:-12h}"
    echo -e "${BLUE}🚨 NBA Gamebook Error Analysis (last $timeframe):${NC}"
    
    # Get dynamic total games for context
    local TOTAL_GAMES=$(calculate_expected_games_from_metadata 2>/dev/null | tail -1)
    if [[ -z "$TOTAL_GAMES" || "$TOTAL_GAMES" -eq 0 ]]; then
        TOTAL_GAMES=$FALLBACK_TOTAL_GAMES
    fi
    
    # Get all errors from current job timeframe
    local errors_raw
    errors_raw=$(gcloud logging read \
        "resource.type=cloud_run_job AND textPayload:\"❌\"" \
        --limit=50 \
        --format="value(timestamp,textPayload)" \
        --project="$PROJECT" \
        --freshness="$timeframe" 2>/dev/null)
    
    if [ -z "$errors_raw" ]; then
        echo -e "  ${GREEN}✅ No NBA gamebook errors found in last $timeframe${NC}"
        return 0
    fi
    
    # Create temporary directory for storing error data
    local temp_dir="/tmp/nba_errors_$$"
    mkdir -p "$temp_dir"
    local game_codes_file="$temp_dir/game_codes.txt"
    local error_details_file="$temp_dir/error_details.txt"
    local error_timestamps_file="$temp_dir/error_timestamps.txt"
    
    # Parse errors and extract game codes
    local error_count=0
    
    # Process each error line
    echo "$errors_raw" | while IFS=$'\t' read -r timestamp textPayload; do
        if [ -n "$textPayload" ] && echo "$textPayload" | grep -q "❌ Failed"; then
            error_count=$((error_count + 1))
            
            # Extract game code using sed
            local game_code
            game_code=$(echo "$textPayload" | sed -n 's/.*❌ Failed \([0-9]\{8\}\/[A-Z]\{6\}\).*/\1/p')
            
            if [ -n "$game_code" ]; then
                # Store data in files
                echo "$game_code" >> "$game_codes_file"
                echo "$game_code|$textPayload" >> "$error_details_file"
                
                # Format timestamp for display (HH:MM:SS)
                local time_display
                time_display=$(echo "$timestamp" | sed 's/.*T\([0-9:]*\)\..*/\1/')
                echo "$game_code|$time_display" >> "$error_timestamps_file"
            fi
        fi
    done
    
    # Read the error count from the files created
    if [ -f "$game_codes_file" ]; then
        error_count=$(wc -l < "$game_codes_file" | tr -d ' ')
    else
        error_count=0
    fi
    
    if [ "$error_count" -eq 0 ]; then
        echo -e "  ${GREEN}✅ No NBA gamebook errors found${NC}"
        rm -rf "$temp_dir"
        return 0
    fi
    
    # Get unique game codes
    local unique_game_codes
    unique_game_codes=$(sort "$game_codes_file" | uniq)
    
    # Check for retry successes
    echo -e "  ${YELLOW}Checking for retry successes...${NC}"
    
    local retry_success_count=0
    echo "$unique_game_codes" | while IFS= read -r game_code; do
        if [ -n "$game_code" ]; then
            # Look for successful download of the same game code
            local success_check
            success_check=$(gcloud logging read \
                "resource.type=cloud_run_job AND textPayload:\"✅ Downloaded $game_code\"" \
                --limit=5 \
                --format="value(timestamp,textPayload)" \
                --project="$PROJECT" \
                --freshness="$timeframe" 2>/dev/null)
            
            if [ -n "$success_check" ]; then
                retry_success_count=$((retry_success_count + 1))
                
                # Extract success timestamp
                local success_timestamp
                success_timestamp=$(echo "$success_check" | head -1 | cut -f1)
                local success_time
                success_time=$(echo "$success_timestamp" | sed 's/.*T\([0-9:]*\)\..*/\1/')
                
                # Update timestamp file with success info (create backup for macOS)
                if [ -f "$error_timestamps_file" ]; then
                    sed -i.bak "s/^${game_code}|\(.*\)$/\1 → ✅ ${success_time}/" "$error_timestamps_file"
                    rm -f "$error_timestamps_file.bak"
                fi
            fi
        fi
    done
    
    # Update retry_success_count by checking the updated timestamps file
    if [ -f "$error_timestamps_file" ]; then
        retry_success_count=$(grep -c "✅" "$error_timestamps_file" 2>/dev/null || echo "0")
    else
        retry_success_count=0
    fi
    
    # Display detailed error report
    echo ""
    echo -e "${RED}NBA Gamebook Errors from current job:${NC}"
    
    local error_num=0
    echo "$unique_game_codes" | while IFS= read -r game_code; do
        if [ -n "$game_code" ]; then
            error_num=$((error_num + 1))
            
            # Get timestamp and details for this game code
            local timestamp
            timestamp=$(grep "^$game_code|" "$error_timestamps_file" | head -1 | cut -d'|' -f2-)
            local details
            details=$(grep "^$game_code|" "$error_details_file" | head -1 | cut -d'|' -f2-)
            
            echo -e "  ${YELLOW}[$error_num/$error_count]${NC} $timestamp - $game_code"
            echo -e "      $(echo "$details" | sed 's/.*WARNING - //')"
            
            # Check if retry succeeded
            if echo "$timestamp" | grep -q "✅"; then
                echo -e "      ${GREEN}✅ Later succeeded - retry worked!${NC}"
            else
                echo -e "      ${RED}⚠️  No retry success found - possible invalid NBA game code${NC}"
            fi
            echo ""
        fi
    done
    
    # Error pattern analysis
    echo -e "${CYAN}📊 NBA Gamebook Error Analysis:${NC}"
    echo -e "  Total NBA games failed: ${RED}$error_count${NC} out of $TOTAL_GAMES"
    echo -e "  Successful retries: ${GREEN}$retry_success_count${NC}"
    
    if [ "$error_count" -gt 0 ]; then
        # Ensure retry_success_count is a valid number
        if [ -z "$retry_success_count" ] || ! echo "$retry_success_count" | grep -q '^[0-9]*$'; then
            retry_success_count=0
        fi
        
        local retry_rate=0
        if [ "$retry_success_count" -gt 0 ] && [ "$error_count" -gt 0 ]; then
            retry_rate=$((retry_success_count * 100 / error_count))
        fi
        echo -e "  Retry success rate: ${GREEN}$retry_rate%${NC}"
        
        # Analyze patterns - get unique dates
        local unique_dates
        unique_dates=$(echo "$unique_game_codes" | cut -d'/' -f1 | sort | uniq)
        local date_count
        date_count=$(echo "$unique_dates" | wc -l | tr -d ' ')
        
        if [ "$date_count" -eq 1 ]; then
            local problem_date
            problem_date=$(echo "$unique_dates" | head -1)
            echo -e "  Pattern: ${YELLOW}All from $problem_date - likely corrupted NBA game codes for that date${NC}"
        elif [ "$date_count" -lt 4 ] && [ "$date_count" -gt 0 ]; then
            echo -e "  Pattern: ${YELLOW}Failures from $date_count dates: $(echo "$unique_dates" | tr '\n' ' ')${NC}"
        fi
        
        # Check for suspicious team codes
        local suspicious_codes
        suspicious_codes=$(echo "$unique_game_codes" | cut -d'/' -f2 | grep -E "(BARIAH|PAYBAR|WORIAH|IAH$|BAR$|JKM|PAU)" | wc -l | tr -d ' ')
        if [ "$suspicious_codes" -gt 0 ]; then
            echo -e "  Assessment: ${YELLOW}Contains $suspicious_codes suspicious team codes - likely All-Star/data corruption${NC}"
        fi
        
        # Overall assessment with dynamic totals
        local error_rate
        error_rate=$(echo "scale=2; $error_count * 100 / $TOTAL_GAMES" | bc -l 2>/dev/null || echo "0.01")
        local success_rate
        success_rate=$(echo "scale=2; 100 - $error_rate" | bc -l 2>/dev/null || echo "99.99")
        echo -e "  Overall: ${GREEN}NBA gamebook backfill running well (${success_rate}% success rate)${NC}"
    fi
    
    # Cleanup temporary files
    rm -rf "$temp_dir"
    echo ""
}

# Enhanced progress analysis function to replace existing analyze_progress()
analyze_progress_enhanced() {
    echo -e "${BLUE}📊 Progress Analysis:${NC}"
    
    # Show job timing context with start time (keep existing logic)
    local running_exec
    running_exec=$(find_running_execution)
    local start_time=""
    
    if [ -n "$running_exec" ]; then
        start_time=$(gcloud run jobs executions describe "$running_exec" \
            --region="$REGION" \
            --format="value(metadata.creationTimestamp)" 2>/dev/null)
        
        if [ -n "$start_time" ]; then
            local elapsed
            elapsed=$(calculate_elapsed_time "$start_time")
            local start_epoch
            start_epoch=$(parse_iso_timestamp "$start_time")
            
            # Show both start time and elapsed time
            if [ -n "$start_epoch" ]; then
                local start_display
                start_display=$(date -r "$start_epoch" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "Unknown")
                if [ -n "$elapsed" ]; then
                    echo -e "  ${PURPLE}⏱️  Job Started: ${start_display} (${elapsed} elapsed)${NC}"
                fi
            fi
        fi
    fi
    
    # Show actual GCS progress (keep existing logic)
    calculate_gcs_progress
    echo ""
    
    # Show recent successful downloads (keep existing logic)
    local logs
    logs=$(get_recent_logs 50)
    echo -e "  Recent downloads:"
    echo "$logs" | cut -f2 | grep "✅ Downloaded" | head -5 | sed 's/^/    /'
    echo ""
    
    # NEW: Enhanced error analysis instead of simple error display
    analyze_nba_errors "12h"
}

# NEW: Enhanced metadata reading with dual totals
calculate_dual_totals_from_metadata() {
    echo -e "${BLUE}📊 Reading season metadata for dual progress tracking...${NC}"
    
    local backfill_total=0
    local comprehensive_total=0
    local successful_seasons=()
    local failed_seasons=()
    
    # Track breakdown by game type
    local total_regular=0
    local total_playoffs=0
    local total_preseason=0
    local total_allstar=0
    
    for season in "${SEASONS_TO_MONITOR[@]}"; do
        local metadata_path=$(find_latest_metadata_file "$season")
        
        if [[ -n "$metadata_path" ]]; then
            local temp_file="/tmp/metadata_${season}_$$"
            if gcloud storage cp "$metadata_path" "$temp_file" 2>/dev/null; then
                
                # Extract counts from metadata
                local backfill_games=$(jq -r '.backfill.total_games // 0' "$temp_file" 2>/dev/null || echo "0")
                local season_total=$(jq -r '.total_games // 0' "$temp_file" 2>/dev/null || echo "0")
                local regular=$(jq -r '.regular_season.completed // 0' "$temp_file" 2>/dev/null || echo "0")
                local playoffs=$(jq -r '.playoffs.completed // 0' "$temp_file" 2>/dev/null || echo "0")
                local preseason=$(jq -r '.preseason.completed // 0' "$temp_file" 2>/dev/null || echo "0")
                local allstar=$(jq -r '.allstar.completed // 0' "$temp_file" 2>/dev/null || echo "0")
                
                if [[ "$backfill_games" -gt 0 && "$season_total" -gt 0 ]]; then
                    backfill_total=$((backfill_total + backfill_games))
                    comprehensive_total=$((comprehensive_total + season_total))
                    
                    # Track breakdowns
                    total_regular=$((total_regular + regular))
                    total_playoffs=$((total_playoffs + playoffs))
                    total_preseason=$((total_preseason + preseason))
                    total_allstar=$((total_allstar + allstar))
                    
                    successful_seasons+=("$season")
                    echo -e "  ✅ ${season}: Core ${GREEN}${backfill_games}${NC}, Total ${CYAN}${season_total}${NC}"
                else
                    failed_seasons+=("$season")
                    echo -e "  ❌ ${season}: Invalid metadata"
                fi
                
                rm -f "$temp_file"
            else
                failed_seasons+=("$season")
                echo -e "  ❌ ${season}: Failed to download metadata"
            fi
        else
            failed_seasons+=("$season")
            echo -e "  ❌ ${season}: No metadata found"
        fi
    done
    
    # Handle fallback logic
    if [[ ${#successful_seasons[@]} -eq 0 ]]; then
        echo -e "  ${RED}⚠️  No season metadata found! Using fallback estimates.${NC}"
        echo -e "  ${YELLOW}Fallback: Core ${FALLBACK_TOTAL_GAMES}, Total ~7500${NC}"
        echo "$FALLBACK_TOTAL_GAMES,7500,0,0,0,0"
    else
        if [[ ${#failed_seasons[@]} -gt 0 ]]; then
            echo -e "  ${YELLOW}⚠️  Some seasons failed (${failed_seasons[*]}), continuing with partial data${NC}"
        else
            echo -e "  ${GREEN}✅ All metadata loaded successfully${NC}"
        fi
        
        echo -e "  ${GREEN}Core Backfill Total: ${backfill_total}${NC} (Regular + Playoffs only)"
        echo -e "  ${CYAN}Comprehensive Total: ${comprehensive_total}${NC} (All game types)"
        echo "$backfill_total,$comprehensive_total,$total_regular,$total_playoffs,$total_preseason,$total_allstar"
    fi
}

# ENHANCED: Dual progress calculation and display
calculate_dual_gcs_progress() {
    echo -e "${BLUE}📊 Dual Progress Analysis:${NC}"
    
    # Get both totals from metadata
    local totals_output=$(calculate_dual_totals_from_metadata)
    local totals_line=$(echo "$totals_output" | tail -1)
    
    # Parse the comma-separated values
    IFS=',' read -r CORE_TOTAL COMPREHENSIVE_TOTAL REGULAR_TOTAL PLAYOFFS_TOTAL PRESEASON_TOTAL ALLSTAR_TOTAL <<< "$totals_line"
    
    echo ""
    
    # Count actual files in GCS
    local json_count=$(gcloud storage ls "gs://nba-scraped-data/nba-com/gamebooks-data/*/*/*.json" 2>/dev/null | wc -l | tr -d ' ')
    local pdf_count=$(gcloud storage ls "gs://nba-scraped-data/nba-com/gamebooks-pdf/*/*/*.pdf" 2>/dev/null | wc -l | tr -d ' ')
    
    if [[ "$json_count" -gt 0 ]]; then
        # Calculate core backfill progress (for props team)
        local core_pct=$((json_count * 100 / CORE_TOTAL))
        local core_remaining=$((CORE_TOTAL - json_count))
        
        # Calculate comprehensive progress (for data team)
        local comp_pct=$((json_count * 100 / COMPREHENSIVE_TOTAL))
        local comp_remaining=$((COMPREHENSIVE_TOTAL - json_count))
        
        echo -e "${PURPLE}🎯 CORE BACKFILL PROGRESS (Props Betting):${NC}"
        if [[ $core_pct -gt 100 ]]; then
            echo -e "  📄 JSON files: ${GREEN}$json_count${NC} / $CORE_TOTAL (${GREEN}COMPLETE + ${core_pct}%${NC}) ✅"
            echo -e "  📋 PDF files: ${GREEN}$pdf_count${NC} / $CORE_TOTAL (${GREEN}COMPLETE + extra${NC}) ✅"
            echo -e "  ${GREEN}✨ Core backfill COMPLETE! Downloaded ${json_count} games (Regular + Playoffs)${NC}"
        else
            echo -e "  📄 JSON files: ${GREEN}$json_count${NC} / $CORE_TOTAL (${YELLOW}$core_pct%${NC}) - $core_remaining remaining"
            echo -e "  📋 PDF files: ${GREEN}$pdf_count${NC} / $CORE_TOTAL (${YELLOW}$core_pct%${NC})"
        fi
        
        echo ""
        echo -e "${CYAN}📊 COMPREHENSIVE DOWNLOAD (All Game Types):${NC}"
        echo -e "  📄 Total files: ${GREEN}$json_count${NC} / $COMPREHENSIVE_TOTAL (${CYAN}$comp_pct%${NC}) - $comp_remaining remaining"
        
        # Show breakdown by game type (estimated)
        echo -e "  ${BLUE}Game Type Breakdown (Estimated):${NC}"
        echo -e "    Regular Season: ${GREEN}$REGULAR_TOTAL${NC} expected"
        echo -e "    Playoffs: ${GREEN}$PLAYOFFS_TOTAL${NC} expected" 
        echo -e "    Preseason: ${YELLOW}$PRESEASON_TOTAL${NC} expected"
        echo -e "    All-Star: ${PURPLE}$ALLSTAR_TOTAL${NC} expected"
        
        # Calculate ETA if we have a running job
        local running_exec=$(find_running_execution)
        if [[ -n "$running_exec" ]]; then
            local start_time=$(gcloud run jobs executions describe "$running_exec" \
                --region=$REGION \
                --format="value(metadata.creationTimestamp)" 2>/dev/null)
            
            if [[ -n "$start_time" ]]; then
                local start_epoch=$(parse_iso_timestamp "$start_time")
                local current_epoch=$(date +%s)
                local elapsed_seconds=$((current_epoch - start_epoch))
                
                if [[ $elapsed_seconds -gt 0 && $json_count -gt 0 ]]; then
                    local rate=$(echo "scale=1; $json_count * 3600 / $elapsed_seconds" | bc -l 2>/dev/null || echo "0")
                    
                    if [[ $comp_remaining -gt 0 ]]; then
                        local eta_hours=$(echo "scale=1; $comp_remaining / $rate" | bc -l 2>/dev/null || echo "0")
                        echo -e "  ⏱️  Processing rate: ${CYAN}$rate games/hour${NC}"
                        echo -e "  🎯 ETA: ${PURPLE}$eta_hours hours${NC} remaining for comprehensive download"
                    else
                        echo -e "  ⏱️  Processing rate: ${CYAN}$rate games/hour${NC}"
                        echo -e "  🎉 ${GREEN}Comprehensive download appears complete!${NC}"
                    fi
                fi
            fi
        fi
    else
        echo -e "  ${YELLOW}No files found in GCS yet${NC}"
    fi
}

# ENHANCED: Quick command with dual progress
cmd_quick_enhanced() {
    local running_exec=$(find_running_execution)
    if [[ -n "$running_exec" ]]; then
        # Calculate elapsed time
        local start_time=$(gcloud run jobs executions describe "$running_exec" \
            --region=$REGION \
            --format="value(metadata.creationTimestamp)" 2>/dev/null)
        
        local elapsed_display=""
        if [[ -n "$start_time" ]]; then
            local elapsed=$(calculate_elapsed_time "$start_time")
            if [[ -n "$elapsed" ]]; then
                elapsed_display=" (${elapsed} elapsed)"
            fi
        fi
        
        echo "Status: RUNNING ($running_exec)$elapsed_display"
        
        # Get dual totals (suppress detailed output for quick command)
        local totals_output=$(calculate_dual_totals_from_metadata 2>/dev/null)
        local totals_line=$(echo "$totals_output" | tail -1)
        IFS=',' read -r CORE_TOTAL COMPREHENSIVE_TOTAL _ _ _ _ <<< "$totals_line"
        
        if [[ -z "$CORE_TOTAL" || "$CORE_TOTAL" -eq 0 ]]; then
            CORE_TOTAL=$FALLBACK_TOTAL_GAMES
            COMPREHENSIVE_TOTAL=7500
            echo "Note: Using fallback totals - metadata unavailable"
        fi
        
        # Get actual progress
        local json_count=$(gcloud storage ls "gs://nba-scraped-data/nba-com/gamebooks-data/*/*/*.json" 2>/dev/null | wc -l | tr -d ' ')
        if [[ "$json_count" -gt 0 ]]; then
            local core_pct=$((json_count * 100 / CORE_TOTAL))
            local comp_pct=$((json_count * 100 / COMPREHENSIVE_TOTAL))
            local core_remaining=$((CORE_TOTAL - json_count))
            local comp_remaining=$((COMPREHENSIVE_TOTAL - json_count))
            
            echo "Core Progress (Props): $json_count / $CORE_TOTAL games ($core_pct% complete)"
            echo "Total Progress (All): $json_count / $COMPREHENSIVE_TOTAL games ($comp_pct% complete)"
            
            # Show processing rate and ETA based on comprehensive total
            if [[ -n "$start_time" && "$json_count" -gt 50 ]]; then
                local start_epoch=$(parse_iso_timestamp "$start_time")
                local current_epoch=$(date +%s)
                local elapsed_seconds=$((current_epoch - start_epoch))
                
                if [[ $elapsed_seconds -gt 0 ]]; then
                    local rate=$(echo "scale=1; $json_count * 3600 / $elapsed_seconds" | bc -l 2>/dev/null || echo "0")
                    local eta_hours=$(echo "scale=1; $comp_remaining / $rate" | bc -l 2>/dev/null || echo "0")
                    echo "Rate: $rate games/hour, ETA: $eta_hours hours remaining"
                fi
            fi
        fi
    else
        echo "Status: NO ACTIVE JOBS"
        
        # Show final counts even when not running
        local totals_output=$(calculate_dual_totals_from_metadata 2>/dev/null)
        local totals_line=$(echo "$totals_output" | tail -1)
        IFS=',' read -r CORE_TOTAL COMPREHENSIVE_TOTAL _ _ _ _ <<< "$totals_line"
        
        local json_count=$(gcloud storage ls "gs://nba-scraped-data/nba-com/gamebooks-data/*/*/*.json" 2>/dev/null | wc -l | tr -d ' ')
        if [[ "$json_count" -gt 0 && "$CORE_TOTAL" -gt 0 ]]; then
            local core_pct=$((json_count * 100 / CORE_TOTAL))
            local comp_pct=$((json_count * 100 / COMPREHENSIVE_TOTAL))
            echo "Final: Core $core_pct% ($json_count/$CORE_TOTAL), Total $comp_pct% ($json_count/$COMPREHENSIVE_TOTAL)"
        fi
    fi
    
    # Show latest download
    local latest=$(get_recent_logs 3 | cut -f2 | grep "✅ Downloaded" | head -1)
    if [[ -n "$latest" ]]; then
        echo "$latest"
    fi
}

# New command for focused error analysis
cmd_errors() {
    local timeframe="${1:-12h}"
    print_header
    analyze_nba_errors "$timeframe"
    
    # Also show some context
    echo -e "${BLUE}🔍 Context - Recent Successful Downloads:${NC}"
    local recent_success
    recent_success=$(get_recent_logs 10 | cut -f2 | grep "✅ Downloaded" | head -3)
    if [ -n "$recent_success" ]; then
        echo "$recent_success" | sed 's/^/  /'
    else
        echo -e "  ${YELLOW}No recent successful downloads in logs${NC}"
    fi
}

# IMPROVED: Quick command prioritizing GCS data over stale logs
cmd_quick() {
    local running_exec=$(find_running_execution)
    if [[ -n "$running_exec" ]]; then
        # Calculate elapsed time using fixed date parsing
        local start_time=$(gcloud run jobs executions describe "$running_exec" \
            --region=$REGION \
            --format="value(metadata.creationTimestamp)" 2>/dev/null)
        
        local elapsed_display=""
        if [[ -n "$start_time" ]]; then
            local elapsed=$(calculate_elapsed_time "$start_time")
            if [[ -n "$elapsed" ]]; then
                elapsed_display=" (${elapsed} elapsed)"
            fi
        fi
        
        echo "Status: RUNNING ($running_exec)$elapsed_display"
        
        # Get dynamic total games (but suppress the detailed output for quick command)
        local TOTAL_GAMES=$(calculate_expected_games_from_metadata 2>/dev/null | tail -1)
        if [[ -z "$TOTAL_GAMES" || "$TOTAL_GAMES" -eq 0 ]]; then
            TOTAL_GAMES=$FALLBACK_TOTAL_GAMES
            echo "Note: Using fallback total games ($TOTAL_GAMES) - metadata unavailable"
        fi
        
        # Use GCS data for accurate progress (not stale logs)
        local json_count=$(gcloud storage ls "$GCS_DATA_PATH/**/*.json" 2>/dev/null | wc -l | tr -d ' ')
        if [[ "$json_count" -gt 0 ]]; then
            local pct=$((json_count * 100 / TOTAL_GAMES))
            local remaining=$((TOTAL_GAMES - json_count))
            echo "Progress: $json_count / $TOTAL_GAMES games ($pct% complete, $remaining remaining)"
            
            # Show processing rate and ETA based on GCS data (not logs)
            if [[ -n "$start_time" && "$json_count" -gt 50 ]]; then
                local start_epoch=$(parse_iso_timestamp "$start_time")
                local current_epoch=$(date +%s)
                local elapsed_seconds=$((current_epoch - start_epoch))
                
                if [[ $elapsed_seconds -gt 0 ]]; then
                    local rate=$(echo "scale=1; $json_count * 3600 / $elapsed_seconds" | bc -l 2>/dev/null || echo "0")
                    local eta_hours=$(echo "scale=1; $remaining / $rate" | bc -l 2>/dev/null || echo "0")
                    echo "Rate: $rate games/hour, ETA: $eta_hours hours remaining"
                fi
            fi
        fi
    else
        echo "Status: NO ACTIVE JOBS"
    fi
    
    # Show latest download
    local latest=$(get_recent_logs 3 | cut -f2 | grep "✅ Downloaded" | head -1)
    if [[ -n "$latest" ]]; then
        echo "$latest"
    fi
}

# ENHANCED: Data validation for new JSON structure with better game code extraction
cmd_validate() {
    local count=${1:-5}
    
    print_header
    echo -e "${BLUE}🔍 Data Quality Validation (last $count files):${NC}"
    echo ""
    
    # Get recent JSON files (updated for new path structure)
    local recent_files=$(gcloud storage ls "$GCS_DATA_PATH/**/*.json" 2>/dev/null | \
        sort -r | \
        head -$count)
    
    if [[ -z "$recent_files" ]]; then
        echo -e "${YELLOW}No JSON files found in $GCS_DATA_PATH${NC}"
        echo -e "Checking if job has started writing files..."
        
        # Check if any directories exist at all
        local dirs=$(gcloud storage ls "$GCS_DATA_PATH/" 2>/dev/null | head -3)
        if [[ -n "$dirs" ]]; then
            echo -e "Found directories: $(echo "$dirs" | wc -l) date directories exist"
            echo "$dirs" | head -3
        else
            echo -e "${YELLOW}No directories found - job may still be starting up${NC}"
        fi
        return 1
    fi
    
    echo -e "${GREEN}Found $count recent JSON files for validation:${NC}"
    echo ""
    
    local file_num=0
    local good_files=0
    local bad_files=0
    
    while IFS= read -r file_path; do
        if [[ -n "$file_path" ]]; then
            file_num=$((file_num + 1))
            
            # IMPROVED: Extract game code from new path structure
            # Path: gs://bucket/nba-com/gamebooks-data/2021-10-08/20211008-MILBKN/timestamp.json
            local path_parts=($(echo "$file_path" | tr '/' ' '))
            local game_dir=""
            
            # Find the game directory (format: YYYYMMDD-TEAMTEAM)
            for part in "${path_parts[@]}"; do
                if [[ "$part" =~ ^[0-9]{8}-[A-Z]{6}$ ]]; then
                    game_dir="$part"
                    break
                fi
            done
            
            local game_code=""
            if [[ -n "$game_dir" ]]; then
                # Convert 20211008-MILBKN to 20211008/MILBKN
                game_code=$(echo "$game_dir" | sed 's/-/\//')
            else
                game_code="Unknown"
            fi
            
            echo -e "${BLUE}[$file_num/$count]${NC} $game_code:"
            
            # Download and validate
            local temp_file="/tmp/validate_$(basename "$file_path")_$$"
            if gcloud storage cp "$file_path" "$temp_file" 2>/dev/null; then
                
                # IMPROVED: Validate new JSON structure
                if jq empty "$temp_file" 2>/dev/null; then
                    # Extract data using new JSON structure
                    local active=$(jq -r '.active_count // 0' "$temp_file")
                    local dnp=$(jq -r '.dnp_count // 0' "$temp_file")
                    local inactive=$(jq -r '.inactive_count // 0' "$temp_file")
                    local total=$(jq -r '.total_players // 0' "$temp_file")
                    local arena=$(jq -r '.arena // "Unknown"' "$temp_file")
                    local first_active=$(jq -r '.active_players[0].name // "None"' "$temp_file")
                    
                    # CRITICAL: Parser fix validation
                    if [[ "$active" -gt 15 ]]; then
                        echo -e "  ${GREEN}✅ PARSER FIX WORKING${NC} - Active: ${GREEN}$active${NC}, DNP: $dnp, Inactive: $inactive, Total: $total"
                        echo -e "    📍 Arena: $arena"
                        echo -e "    🏀 First player: $first_active"
                        good_files=$((good_files + 1))
                        
                        # Show sample stats for verification
                        local sample_stats=$(jq -r '.active_players[0] | "Points: \(.stats.points // 0), Minutes: \(.stats.minutes // "0:00")"' "$temp_file" 2>/dev/null)
                        if [[ -n "$sample_stats" && "$sample_stats" != "null" ]]; then
                            echo -e "    📊 Sample stats: $sample_stats"
                        fi
                    elif [[ "$active" -gt 0 ]]; then
                        echo -e "  ${YELLOW}⚠️  LOW ACTIVE COUNT${NC} - Active: ${YELLOW}$active${NC}, DNP: $dnp, Inactive: $inactive, Total: $total"
                        echo -e "    📍 Arena: $arena"
                    else
                        echo -e "  ${RED}❌ PARSER BROKEN${NC} - Active: ${RED}$active${NC}, DNP: $dnp, Inactive: $inactive, Total: $total"
                        echo -e "    📍 Arena: $arena"
                        bad_files=$((bad_files + 1))
                    fi
                else
                    echo -e "  ${RED}❌ Invalid JSON${NC}"
                    bad_files=$((bad_files + 1))
                fi
                
                rm -f "$temp_file"
            else
                echo -e "  ${RED}❌ Download failed${NC}"
                bad_files=$((bad_files + 1))
            fi
            
            echo ""
        fi
    done <<< "$recent_files"
    
    # Summary
    echo -e "${CYAN}📊 Validation Summary:${NC}"
    echo -e "  ${GREEN}✅ Good files: $good_files${NC}"
    echo -e "  ${RED}❌ Bad files: $bad_files${NC}"
    
    if [[ $good_files -gt 0 && $bad_files -eq 0 ]]; then
        echo -e "  ${GREEN}🎉 PARSER FIX IS WORKING! All validated files have active players.${NC}"
    elif [[ $bad_files -gt 0 ]]; then
        echo -e "  ${RED}⚠️  ISSUES DETECTED: Some files have missing active players.${NC}"
    fi
    
    # Overall progress
    echo ""
    calculate_gcs_progress
}

# NEW: Command to show metadata status
cmd_metadata() {
    print_header
    echo -e "${BLUE}🗂️  Season Metadata Status:${NC}"
    echo ""
    
    for season in "${SEASONS_TO_MONITOR[@]}"; do
        echo -e "${CYAN}Season: ${season}${NC}"
        
        local metadata_path=$(find_latest_metadata_file "$season")
        if [[ -n "$metadata_path" ]]; then
            echo -e "  📄 Latest file: $(basename "$metadata_path")"
            
            # Download and show details
            local temp_file="/tmp/metadata_${season}_$$"
            if gcloud storage cp "$metadata_path" "$temp_file" 2>/dev/null; then
                local scraped_at=$(jq -r '.scraped_at // "Unknown"' "$temp_file" 2>/dev/null)
                local total_games=$(jq -r '.total_games // 0' "$temp_file" 2>/dev/null)
                local backfill_games=$(jq -r '.backfill.total_games // 0' "$temp_file" 2>/dev/null)
                local regular_completed=$(jq -r '.regular_season.completed // 0' "$temp_file" 2>/dev/null)
                local playoffs_completed=$(jq -r '.playoffs.completed // 0' "$temp_file" 2>/dev/null)
                
                echo -e "  📅 Scraped: $scraped_at"
                echo -e "  🏀 Total games: $total_games"
                echo -e "  📊 Backfill eligible: ${GREEN}$backfill_games${NC}"
                echo -e "  ✅ Completed: Regular $regular_completed, Playoffs $playoffs_completed"
                
                rm -f "$temp_file"
            else
                echo -e "  ${RED}❌ Failed to download metadata${NC}"
            fi
        else
            echo -e "  ${RED}❌ No metadata found${NC}"
        fi
        echo ""
    done
    
    # Show current expected total
    echo -e "${BLUE}📊 Current Expected Totals:${NC}"
    local TOTAL_GAMES=$(calculate_expected_games_from_metadata)
    echo ""
}

# Standard command functions
cmd_status() {
    print_header
    show_execution_status
    echo ""
    check_activity_health
    echo ""
    
    echo -e "${BLUE}📄 Latest Activity:${NC}"
    local recent=$(get_recent_logs 3 | cut -f2)
    if [[ -n "$recent" ]]; then
        echo "$recent" | sed 's/^/  /'
    else
        echo -e "  ${YELLOW}No recent activity${NC}"
    fi
}

cmd_progress() {
    print_header
    analyze_progress_enhanced
}

cmd_watch() {
    echo -e "${GREEN}Starting continuous monitoring (Ctrl+C to stop)...${NC}"
    
    while true; do
        clear
        cmd_status
        echo ""
        analyze_progress_enhanced
        echo ""
        echo -e "${YELLOW}Next update in 60 seconds... (Ctrl+C to stop)${NC}"
        sleep 60
    done
}

cmd_logs() {
    local count=${1:-20}
    print_header
    echo -e "${BLUE}📄 Recent Logs (last $count):${NC}"
    get_recent_logs $count | sed 's/^/  /'
}

show_usage_enhanced() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  status         - Full status overview with elapsed time"
    echo "  progress       - Detailed progress analysis with enhanced error reporting"
    echo "  metadata       - Show season metadata status and expected game totals"
    echo "  errors [time]  - Focused NBA gamebook error analysis (default: 12h)"
    echo "  watch          - Continuous monitoring"
    echo "  quick          - Quick status with elapsed time and progress"
    echo "  logs [N]       - Show last N log lines"
    echo "  validate [N]   - Validate last N JSON files from GCS (default: 5)"
    echo ""
    echo "Examples:"
    echo "  $0 status      - Complete status check"
    echo "  $0 metadata    - Check season metadata and expected totals"
    echo "  $0 errors      - NBA error analysis (last 12h)"
    echo "  $0 errors 24h  - NBA error analysis (last 24h)"
    echo "  $0 progress    - Progress with enhanced error details"
    echo "  $0 quick       - Fast status with progress"
    echo "  $0 validate    - Check if parser fix is working"
    echo "  $0 watch       - Monitor continuously"
}

# Main command handling
case "${1:-status}" in
    "status"|"")
        cmd_status
        ;;
    "metadata")
        cmd_metadata
        ;;
    "validate")
        cmd_validate "$2"
        ;;
    "progress")
        cmd_progress
        ;;
    "watch")
        cmd_watch
        ;;
    "quick")
        cmd_quick
        ;;
    "logs")
        cmd_logs "$2"
        ;;
    "help"|"-h"|"--help")
        show_usage_enhanced
        ;;
    "errors")
        cmd_errors "$2"
        ;;
    *)
        echo "Unknown command: $1"
        show_usage_enhanced
        exit 1
        ;;
esac