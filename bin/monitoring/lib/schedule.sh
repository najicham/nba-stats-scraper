#!/bin/bash
# File: bin/monitoring/lib/schedule.sh
# Purpose: Schedule parsing and game type detection

# Map date to NBA season (Mac-compatible)
date_to_season() {
    local date="$1"
    local year=$(echo "$date" | cut -d'-' -f1)
    local month=$(echo "$date" | cut -d'-' -f2)
    
    # NBA season runs Oct-Jun, so:
    # Oct-Dec = current year season (e.g., 2021-10 = 2021-22 season)  
    # Jan-Jun = previous year season (e.g., 2022-01 = 2021-22 season)
    if [[ $month -ge 10 ]]; then
        echo "$year-$((year + 1 - 2000))"  # 2021 -> 2021-22
    else
        echo "$((year - 1))-$((year - 2000))"  # 2022 -> 2021-22
    fi
}

# Get schedule data for a specific season (Mac-compatible file cache)
get_schedule_for_season() {
    local season="$1"
    local cache_file="$SCHEDULE_CACHE_DIR/schedule_${season}.json"
    
    # Check cache first
    if [[ -f "$cache_file" ]]; then
        echo "$cache_file"
        return 0
    fi
    
    local schedule_path="$BUCKET/nba-com/schedule/$season/"
    
    # Find latest schedule file for this season
    local schedule_files=$(timeout 30 gcloud storage ls "$schedule_path" 2>/dev/null | grep "\.json$" | head -5)
    
    if [[ -z "$schedule_files" ]]; then
        echo ""
        return 1
    fi
    
    # Use the first schedule file found
    local schedule_file=$(echo "$schedule_files" | head -1)
    
    # Download schedule file to cache
    if ! download_file_safe "$schedule_file" "$cache_file"; then
        echo ""
        return 1
    fi
    
    echo "$cache_file"
    return 0
}

# Check game type for a specific date (with robust error handling)
get_game_type_for_date() {
    local date="$1"
    
    # Simple preseason logic based on date (primary method)
    local month=$(echo "$date" | cut -d'-' -f2)
    local day=$(echo "$date" | cut -d'-' -f3)
    
    # October 1-15 is typically preseason
    if [[ "$month" == "10" && "$day" -le "15" ]]; then
        echo "preseason"
        return 0
    fi
    
    # Try to get more specific data from schedule
    local season=$(date_to_season "$date")
    local schedule_file=$(get_schedule_for_season "$season")
    
    if [[ -z "$schedule_file" || ! -f "$schedule_file" ]]; then
        # Fall back to date-based logic
        if [[ "$month" == "10" && "$day" -le "20" ]]; then
            echo "preseason"
        else
            echo "regular"
        fi
        return 0
    fi
    
    # Validate schedule file
    if ! jq empty "$schedule_file" 2>/dev/null; then
        echo "preseason"  # Default for early October dates
        return 0
    fi
    
    # Check if file has expected structure
    local has_game_dates=$(jq -r 'has("gameDates")' "$schedule_file" 2>/dev/null)
    if [[ "$has_game_dates" != "true" ]]; then
        echo "preseason"  # Default for early October dates
        return 0
    fi
    
    # Convert YYYY-MM-DD to MM/DD/YYYY (Mac-compatible)
    local date_mm_dd_yyyy=""
    if command -v gdate >/dev/null 2>&1; then
        date_mm_dd_yyyy=$(gdate -d "$date" "+%m/%d/%Y" 2>/dev/null)
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        date_mm_dd_yyyy=$(date -j -f "%Y-%m-%d" "$date" "+%m/%d/%Y" 2>/dev/null)
    else
        date_mm_dd_yyyy=$(date -d "$date" "+%m/%d/%Y" 2>/dev/null)
    fi
    
    if [[ -z "$date_mm_dd_yyyy" ]]; then
        echo "preseason"
        return 0
    fi
    
    # Try to parse schedule data carefully
    local game_analysis=$(jq -r --arg target_date "$date_mm_dd_yyyy" '
        try (
            .gameDates[]? | 
            select(.gameDate | startswith($target_date)) | 
            .games[]? | 
            {
                weekNumber: (.weekNumber // -1),
                weekName: (.weekName // ""),
                gameLabel: (.gameLabel // ""),
                gameSubLabel: (.gameSubLabel // "")
            }
        ) catch empty
    ' "$schedule_file" 2>/dev/null | head -1)
    
    if [[ -z "$game_analysis" ]]; then
        # If no games found in schedule, assume no games that day
        echo "none"
        return 0
    fi
    
    # Extract values safely
    local week_number=$(echo "$game_analysis" | jq -r 'try .weekNumber catch -1' 2>/dev/null)
    local week_name=$(echo "$game_analysis" | jq -r 'try .weekName catch ""' 2>/dev/null)
    local game_label=$(echo "$game_analysis" | jq -r 'try .gameLabel catch ""' 2>/dev/null)
    local game_sub_label=$(echo "$game_analysis" | jq -r 'try .gameSubLabel catch ""' 2>/dev/null)
    
    # Apply same logic as odds API script
    if [[ "$week_number" == "0" ]]; then
        echo "preseason"
        return 0
    fi
    
    if [[ "$week_name" == "All-Star" || -n "$game_label" || -n "$game_sub_label" ]]; then
        echo "allstar"
        return 0
    fi
    
    echo "regular"
    return 0
}