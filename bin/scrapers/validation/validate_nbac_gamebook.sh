#!/bin/bash
# File: bin/validation/validate_nbac_gamebook.sh  
# Purpose: Season-targeted validator that samples random dates for efficiency

set -euo pipefail

PROJECT="nba-props-platform"
BUCKET="gs://nba-scraped-data"
JSON_PATH="nba-com/gamebooks-data"

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
    echo -e "${CYAN}🏀 NBA SEASON-TARGETED VALIDATOR${NC}"
    echo -e "${CYAN}================================================${NC}"
    echo -e "Time: $(date)"
    echo -e "Bucket: $BUCKET/$JSON_PATH"
    echo ""
}

# Convert YYYYMMDD to YYYY-MM-DD format
convert_date_format() {
    local date_input="$1"
    
    if [[ "$date_input" =~ ^[0-9]{8}$ ]]; then
        # Convert YYYYMMDD to YYYY-MM-DD
        local year="${date_input:0:4}"
        local month="${date_input:4:2}"
        local day="${date_input:6:2}"
        echo "$year-$month-$day"
    elif [[ "$date_input" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
        # Already in correct format
        echo "$date_input"
    else
        echo ""
    fi
}

# Get recent activity from monitoring logs (fixed for correct format conversion)
get_recent_activity_from_logs() {
    local count="${1:-10}"
    
    # Use the same log reading as the monitoring script (quietly)
    local recent_logs=$(gcloud logging read \
        "resource.type=cloud_run_job" \
        --limit=50 \
        --format="value(textPayload)" \
        --project="nba-props-platform" \
        --freshness=30m 2>/dev/null | grep "✅ Downloaded" | head -$count)
    
    if [[ -z "$recent_logs" ]]; then
        return 1
    fi
    
    # Extract date/game combinations and convert format
    local recent_paths=()
    while IFS= read -r log_line; do
        if [[ -n "$log_line" ]]; then
            # Extract the date/game part (like "20231130/PORCLE")
            local path_match=$(echo "$log_line" | grep -o '[0-9]\{8\}/[A-Z]\{6\}')
            if [[ -n "$path_match" ]]; then
                # Split into date and game
                local date_part=$(echo "$path_match" | cut -d'/' -f1)
                local game_part=$(echo "$path_match" | cut -d'/' -f2)
                
                # Convert date format: 20231130 -> 2023-11-30
                local converted_date=$(convert_date_format "$date_part")
                
                if [[ -n "$converted_date" ]]; then
                    recent_paths+=("$converted_date/$game_part")
                fi
            fi
        fi
    done <<< "$recent_logs"
    
    # Return unique date/game combinations
    printf '%s\n' "${recent_paths[@]}" | sort -u | head -$count
}

# Fallback method using directory scanning (updated for correct format)
get_recent_activity_dates_fallback() {
    local count="${1:-5}"
    
    echo -e "Scanning for recent date directories..."
    
    # Look for YYYY-MM-DD format directories (this is what actually exists)
    local recent_dirs=$(timeout 60 gcloud storage ls "$BUCKET/$JSON_PATH/" 2>/dev/null | \
        grep -E "[0-9]{4}-[0-9]{2}-[0-9]{2}" | \
        sort -r | \
        head -$count)
    
    if [[ -n "$recent_dirs" ]]; then
        # Extract just the date part
        while IFS= read -r dir; do
            if [[ -n "$dir" ]]; then
                local date_dir=$(basename "$dir" | grep -E "^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
                if [[ -n "$date_dir" ]]; then
                    echo "$date_dir"
                fi
            fi
        done <<< "$recent_dirs"
    fi
}

# Check a specific date/game combination (expects YYYY-MM-DD/TEAMCODE format) - fixed output
check_date_game_combination() {
    local date_game="$1"  # Format: "2023-11-30/PORCLE"
    local full_path="$BUCKET/$JSON_PATH/$date_game/"
    
    echo -e "  ${BLUE}Checking path:${NC} $full_path" >&2
    
    # Check if game directory exists with timeout
    if ! timeout 30 gcloud storage ls "$full_path" >/dev/null 2>&1; then
        echo -e "    ${YELLOW}No data for $date_game${NC} (path: $full_path)" >&2
        return 1
    fi
    
    # Get JSON and PDF files from this specific game with timeout
    local json_files=$(timeout 30 gcloud storage ls "$full_path" 2>/dev/null | grep "\.json$")
    local pdf_files=$(timeout 30 gcloud storage ls "$full_path" 2>/dev/null | grep "\.pdf$")
    
    local json_count=0
    local pdf_count=0
    
    if [[ -n "$json_files" ]]; then
        json_count=$(echo "$json_files" | wc -l | tr -d ' ')
    fi
    
    if [[ -n "$pdf_files" ]]; then
        pdf_count=$(echo "$pdf_files" | wc -l | tr -d ' ')
    fi
    
    echo -e "    ${GREEN}$date_game${NC}: $json_count JSON, $pdf_count PDF files" >&2
    
    if [[ -n "$json_files" ]]; then
        echo -e "    ${BLUE}JSON files found:${NC}" >&2
        echo "$json_files" | sed 's/^/      /' >&2
        
        # Return ONLY the JSON files for validation (to stdout)
        echo "$json_files"
        return 0
    else
        echo -e "    ${YELLOW}No JSON files found in $date_game${NC}" >&2
        return 1
    fi
}

# Check a specific date for games (expects YYYY-MM-DD format) - fixed output parsing
check_date_for_games() {
    local date="$1"
    local date_path="$BUCKET/$JSON_PATH/$date/"
    
    echo -e "  ${BLUE}Checking path:${NC} $date_path" >&2
    
    # Check if date directory exists with timeout
    if ! timeout 30 gcloud storage ls "$date_path" >/dev/null 2>&1; then
        echo -e "    ${YELLOW}No data for $date${NC} (path: $date_path)" >&2
        return 1
    fi
    
    # Count games for this date with timeout
    local game_dirs=$(timeout 30 gcloud storage ls "$date_path" 2>/dev/null | wc -l | tr -d ' ')
    local json_files_count=$(timeout 60 gcloud storage ls --recursive "$date_path" 2>/dev/null | grep "\.json$" | wc -l | tr -d ' ')
    local pdf_files_count=$(timeout 60 gcloud storage ls --recursive "$date_path" 2>/dev/null | grep "\.pdf$" | wc -l | tr -d ' ')
    
    echo -e "    ${GREEN}$date${NC}: $game_dirs games, $json_files_count JSON, $pdf_files_count PDF" >&2
    
    # Get actual JSON files for validation (limit to first 3 for speed)
    local json_list=$(timeout 60 gcloud storage ls --recursive "$date_path" 2>/dev/null | grep "\.json$" | head -3)
    
    if [[ -n "$json_list" ]]; then
        echo -e "    ${BLUE}Sample JSON files found:${NC}" >&2
        echo "$json_list" | sed 's/^/      /' >&2
        
        # Return ONLY the file paths for processing (to stdout)
        echo "$json_list"
        return 0
    else
        echo -e "    ${YELLOW}No JSON files found in $date${NC}" >&2
        return 1
    fi
}

# Enhanced JSON validation with correct structure for NBA gamebook files
validate_json_file() {
    local file_path="$1"
    local temp_file="/tmp/nba_validate_$(date +%s)_$.json"
    
    # Download file with better error reporting
    echo -e "    ${BLUE}Downloading:${NC} $file_path"
    if ! gcloud storage cp "$file_path" "$temp_file" >/dev/null 2>&1; then
        echo -e "    ${RED}❌ Download failed${NC}"
        echo -e "    ${RED}   Failed path: $file_path${NC}"
        return 1
    fi
    
    # Check file size
    local file_size=$(stat -f%z "$temp_file" 2>/dev/null || stat -c%s "$temp_file" 2>/dev/null || echo "0")
    if [[ $file_size -eq 0 ]]; then
        echo -e "    ${RED}❌ Downloaded file is empty${NC}"
        rm -f "$temp_file"
        return 1
    fi
    
    # Validate JSON structure
    if ! jq empty "$temp_file" 2>/dev/null; then
        echo -e "    ${RED}❌ Invalid JSON format${NC}"
        echo -e "    ${RED}   File size: ${file_size}B${NC}"
        rm -f "$temp_file"
        return 1
    fi
    
    # Quick data analysis with correct structure for NBA gamebook files
    local analysis=$(jq -r '
        {
            total_players: ((.active_players | length) + (.dnp_players | length) + (.inactive_players | length)),
            active: (.active_players | length),
            dnp: (.dnp_players | length),
            inactive: (.inactive_players | length),
            arena: (.arena // "Unknown"),
            home_team: (.home_team // "Unknown"),
            away_team: (.away_team // "Unknown"),
            date: (.date // "Unknown"),
            game_code: (.game_code // "Unknown"),
            matchup: (.matchup // "Unknown"),
            attendance: (.attendance // "Unknown"),
            game_duration: (.game_duration // "Unknown")
        }
    ' "$temp_file" 2>/dev/null)
    
    if [[ -z "$analysis" ]]; then
        echo -e "    ${RED}❌ Failed to analyze JSON structure${NC}"
        echo -e "    ${RED}   File may be corrupted or have unexpected format${NC}"
        
        # Show first few lines for debugging
        echo -e "    ${YELLOW}First 3 lines of file:${NC}"
        head -3 "$temp_file" | sed 's/^/      /'
        
        rm -f "$temp_file"
        return 1
    fi
    
    # Extract values safely
    local total_players=$(echo "$analysis" | jq -r '.total_players // 0')
    local active=$(echo "$analysis" | jq -r '.active // 0')
    local dnp=$(echo "$analysis" | jq -r '.dnp // 0')
    local inactive=$(echo "$analysis" | jq -r '.inactive // 0')
    local arena=$(echo "$analysis" | jq -r '.arena // "Unknown"')
    local home_team=$(echo "$analysis" | jq -r '.home_team // "Unknown"')
    local away_team=$(echo "$analysis" | jq -r '.away_team // "Unknown"')
    local game_date=$(echo "$analysis" | jq -r '.date // "Unknown"')
    local game_code=$(echo "$analysis" | jq -r '.game_code // "Unknown"')
    local matchup=$(echo "$analysis" | jq -r '.matchup // "Unknown"')
    local attendance=$(echo "$analysis" | jq -r '.attendance // "Unknown"')
    local game_duration=$(echo "$analysis" | jq -r '.game_duration // "Unknown"')
    
    # Quality assessment for NBA gamebook data
    local quality_score=0
    local quality_notes=()
    
    # Player count validation (NBA gamebooks typically have fewer players listed than full rosters)
    if [[ $total_players -ge 5 && $total_players -le 50 ]]; then
        quality_score=$((quality_score + 20))
    else
        quality_notes+=("Player count: $total_players")
    fi
    
    # Game info completeness
    if [[ "$arena" != "Unknown" && "$arena" != "null" && -n "$arena" ]]; then
        quality_score=$((quality_score + 20))
    else
        quality_notes+=("Missing arena")
    fi
    
    if [[ "$home_team" != "Unknown" && "$away_team" != "Unknown" ]]; then
        quality_score=$((quality_score + 20))
    else
        quality_notes+=("Missing team info")
    fi
    
    if [[ "$game_code" != "Unknown" && "$game_code" != "null" ]]; then
        quality_score=$((quality_score + 20))
    else
        quality_notes+=("Missing game code")
    fi
    
    if [[ "$attendance" != "Unknown" && "$attendance" != "null" ]]; then
        quality_score=$((quality_score + 20))
    else
        quality_notes+=("Missing attendance")
    fi
    
    # Display results with color coding
    local quality_color=$GREEN
    [[ $quality_score -lt 75 ]] && quality_color=$YELLOW
    [[ $quality_score -lt 50 ]] && quality_color=$RED
    
    echo -e "    ${GREEN}✅ Valid NBA Gamebook JSON${NC} - ${file_size}B"
    echo -e "    🏀 Game: ${matchup} (${game_code})"
    echo -e "    📅 Date: $game_date | 🏟️  Arena: $arena"
    echo -e "    👥 Players: $total_players total ($active active, $dnp DNP, $inactive inactive)"
    echo -e "    🎫 Attendance: $attendance | ⏱️  Duration: $game_duration"
    echo -e "    📈 Quality: ${quality_color}$quality_score/100${NC}"
    
    # Show quality notes if any
    if [[ ${#quality_notes[@]} -gt 0 ]]; then
        echo -e "    ⚠️  Notes: ${quality_notes[*]}"
    fi
    
    # Show sample player data if available
    local sample_dnp=$(jq -r '.dnp_players[0].name // empty' "$temp_file" 2>/dev/null)
    if [[ -n "$sample_dnp" ]]; then
        echo -e "    🚫 Sample DNP: $sample_dnp"
    fi
    
    rm -f "$temp_file"
    return 0
}

# Helper function to validate a list of sample files
validate_sample_files() {
    local files=("$@")
    
    echo -e "${BLUE}📊 Validating ${#files[@]} sample files:${NC}"
    echo ""
    
    local valid_files=0
    local file_num=0
    
    for file_path in "${files[@]}"; do
        file_num=$((file_num + 1))
        
        echo -e "${CYAN}[$file_num/${#files[@]}]${NC} $(basename "$(dirname "$file_path")")/$(basename "$file_path")"
        echo -e "  ${BLUE}Full path:${NC} $file_path"
        
        if validate_json_file "$file_path"; then
            valid_files=$((valid_files + 1))
        fi
        echo ""
    done
    
    # Summary
    echo -e "${CYAN}📋 Validation Summary:${NC}"
    echo -e "  Files validated: ${#files[@]}"
    echo -e "  Valid files: ${GREEN}$valid_files${NC}"
    [[ ${#files[@]} -gt 0 ]] && echo -e "  Success rate: $(( valid_files * 100 / ${#files[@]} ))%"
}

# Validate a sample of files from specific dates (fixed for hanging)
validate_date_sample() {
    local dates=("$@")
    
    echo -e "${BLUE}🔍 Validating sample files from selected dates:${NC}"
    echo ""
    
    local total_files=0
    local valid_files=0
    local total_games=0
    local sample_files=()
    
    # Collect files from each date
    for date in "${dates[@]}"; do
        echo -e "${CYAN}Checking $date:${NC}"
        
        # Call check_date_for_games and capture output
        local date_files
        if date_files=$(check_date_for_games "$date"); then
            # Process the returned files
            if [[ -n "$date_files" ]]; then
                # Add files to our sample
                while IFS= read -r file; do
                    if [[ -n "$file" ]]; then
                        sample_files+=("$file")
                    fi
                done <<< "$date_files"
                
                # Count games for this date  
                local game_count=$(gcloud storage ls "$BUCKET/$JSON_PATH/$date/" 2>/dev/null | wc -l | tr -d ' ')
                total_games=$((total_games + game_count))
            fi
        fi
        echo ""
    done
    
    # Validate the collected sample files
    if [[ ${#sample_files[@]} -gt 0 ]]; then
        echo -e "${BLUE}📊 Validating ${#sample_files[@]} sample files:${NC}"
        echo ""
        
        local file_num=0
        for file_path in "${sample_files[@]}"; do
            file_num=$((file_num + 1))
            total_files=$((total_files + 1))
            
            echo -e "${CYAN}[$file_num/${#sample_files[@]}]${NC} $(basename "$(dirname "$file_path")")/$(basename "$file_path")"
            
            if validate_json_file "$file_path"; then
                valid_files=$((valid_files + 1))
            fi
            echo ""
        done
        
        # Summary
        echo -e "${CYAN}📋 Sample Validation Summary:${NC}"
        echo -e "  Dates checked: ${#dates[@]}"
        echo -e "  Games found: $total_games"
        echo -e "  Files validated: $total_files"
        echo -e "  Valid files: ${GREEN}$valid_files${NC}"
        [[ $total_files -gt 0 ]] && echo -e "  Success rate: $(( valid_files * 100 / total_files ))%"
    else
        echo -e "${YELLOW}No files found in the specified dates${NC}"
        
        # Show which dates were checked for debugging
        echo -e "${BLUE}Dates checked:${NC}"
        for date in "${dates[@]}"; do
            echo -e "  $date -> $BUCKET/$JSON_PATH/$date/"
        done
    fi
}

# Recent activity command - uses monitoring logs with format conversion
cmd_recent_activity() {
    local count="${1:-5}"
    
    print_header
    echo -e "${BLUE}📅 Recent Activity Validation (from monitoring logs):${NC}"
    echo ""
    
    # Get recent activity from logs and convert format
    echo -e "Getting recent activity from backfill logs..."
    local recent_activities
    recent_activities=$(get_recent_activity_from_logs "$count")
    
    if [[ -n "$recent_activities" ]]; then
        echo -e "${GREEN}Found recent activity from backfill logs (converted to GCS format):${NC}"
        echo "$recent_activities" | sed 's/^/  /'
        echo ""
        
        # Process each date/game combination
        local sample_files=()
        local total_games=0
        
        while IFS= read -r date_game; do
            if [[ -n "$date_game" && "$date_game" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}/[A-Z]{6}$ ]]; then
                echo -e "${CYAN}Validating: $date_game${NC}"
                
                local game_files
                if game_files=$(check_date_game_combination "$date_game"); then
                    if [[ -n "$game_files" ]]; then
                        # Add files to our sample (limit to 2 per game for speed)
                        while IFS= read -r file; do
                            if [[ -n "$file" ]]; then
                                sample_files+=("$file")
                            fi
                        done <<< "$(echo "$game_files" | head -2)"
                        
                        total_games=$((total_games + 1))
                    fi
                fi
                echo ""
            fi
        done <<< "$recent_activities"
        
        # Validate the collected sample files
        if [[ ${#sample_files[@]} -gt 0 ]]; then
            validate_sample_files "${sample_files[@]}"
        else
            echo -e "${YELLOW}No JSON files found in recent activity${NC}"
        fi
    else
        echo -e "${YELLOW}No recent activity found in logs, trying fallback method...${NC}"
        echo ""
        
        # Fallback to date-based checking (this should work now with YYYY-MM-DD format)
        echo -e "Scanning recent date directories..."
        local recent_dates
        recent_dates=$(get_recent_activity_dates_fallback "$count")
        
        if [[ -n "$recent_dates" ]]; then
            local dates_array=()
            while IFS= read -r date; do
                if [[ -n "$date" ]]; then
                    dates_array+=("$date")
                fi
            done <<< "$recent_dates"
            
            if [[ ${#dates_array[@]} -gt 0 ]]; then
                echo -e "${GREEN}Found recent dates:${NC}"
                printf '  %s\n' "${dates_array[@]}"
                echo ""
                validate_date_sample "${dates_array[@]}"
            else
                echo -e "${RED}No valid dates found${NC}"
            fi
        else
            echo -e "${RED}No recent date directories found${NC}"
        fi
    fi
}

# Custom date validation - accepts both YYYY-MM-DD and YYYYMMDD formats
cmd_custom_dates() {
    local dates=("$@")
    
    if [[ ${#dates[@]} -eq 0 ]]; then
        echo "Usage: $0 dates YYYYMMDD [YYYYMMDD ...]"
        echo "   or: $0 dates YYYY-MM-DD [YYYY-MM-DD ...]"
        echo ""
        echo "Examples:"
        echo "  $0 dates 20230115 20230220 20230310"
        echo "  $0 dates 2023-01-15 2023-02-20 2023-03-10"
        echo "  $0 dates 20240101"
        return 1
    fi
    
    print_header
    echo -e "${BLUE}🗓️ Custom Date Validation:${NC}"
    
    # Convert dates to YYYY-MM-DD format (what GCS actually uses)
    local converted_dates=()
    for date in "${dates[@]}"; do
        local converted_date=$(convert_date_format "$date")
        
        if [[ -n "$converted_date" ]]; then
            converted_dates+=("$converted_date")
            if [[ "$date" != "$converted_date" ]]; then
                echo -e "  Converted $date -> $converted_date"
            else
                echo -e "  Using $date"
            fi
        else
            echo -e "  ${RED}Invalid date format: $date${NC} (expected YYYY-MM-DD or YYYYMMDD)"
            return 1
        fi
    done
    
    echo ""
    
    validate_date_sample "${converted_dates[@]}"
}

# Quick command to test with known existing dates
cmd_known() {
    print_header
    echo -e "${BLUE}🎯 Testing with known existing dates from debug output:${NC}"
    echo ""
    
    # Test dates we know exist from the debug output
    local known_dates=("2021-10-19" "2021-10-20" "2021-10-21")
    
    echo -e "Testing with dates we know exist:"
    for date in "${known_dates[@]}"; do
        echo -e "  $date"
    done
    echo ""
    
    validate_date_sample "${known_dates[@]}"
}
cmd_debug() {
    print_header
    echo -e "${BLUE}🔍 DEBUG: Exploring actual GCS structure${NC}"
    echo ""
    
    # Show what's actually in the main directory
    echo -e "1. Contents of main directory:"
    echo -e "   Path: $BUCKET/$JSON_PATH/"
    echo -e "   ${BLUE}Listing all contents:${NC}"
    local main_contents=$(gcloud storage ls "$BUCKET/$JSON_PATH/" 2>/dev/null | head -20)
    if [[ -n "$main_contents" ]]; then
        echo "$main_contents" | sed 's/^/     /'
        
        # Count total directories
        local total_dirs=$(gcloud storage ls "$BUCKET/$JSON_PATH/" 2>/dev/null | wc -l)
        echo -e "   ${GREEN}Total directories: $total_dirs${NC}"
    else
        echo -e "     ${YELLOW}No contents found${NC}"
    fi
    
    echo ""
    
    # Check if there's a different pattern
    echo -e "2. Looking for different date patterns:"
    echo -e "   ${BLUE}YYYY-MM-DD pattern:${NC}"
    local dash_dates=$(gcloud storage ls "$BUCKET/$JSON_PATH/" 2>/dev/null | grep -E "[0-9]{4}-[0-9]{2}-[0-9]{2}" | head -5)
    if [[ -n "$dash_dates" ]]; then
        echo "$dash_dates" | sed 's/^/     /'
    else
        echo -e "     ${YELLOW}None found${NC}"
    fi
    
    echo -e "   ${BLUE}YYYYMMDD pattern:${NC}"
    local yyyymmdd_dates=$(gcloud storage ls "$BUCKET/$JSON_PATH/" 2>/dev/null | grep -E "[0-9]{8}" | head -5)
    if [[ -n "$yyyymmdd_dates" ]]; then
        echo "$yyyymmdd_dates" | sed 's/^/     /'
    else
        echo -e "     ${YELLOW}None found${NC}"
    fi
    
    echo ""
    
    # Check recent activity paths from logs
    echo -e "3. Testing paths from monitoring logs:"
    local recent_logs=$(gcloud logging read \
        "resource.type=cloud_run_job" \
        --limit=10 \
        --format="value(textPayload)" \
        --project="nba-props-platform" \
        --freshness=60m 2>/dev/null | grep "✅ Downloaded" | head -3)
    
    if [[ -n "$recent_logs" ]]; then
        echo -e "   ${BLUE}Recent download logs:${NC}"
        echo "$recent_logs" | sed 's/^/     /'
        
        echo ""
        echo -e "   ${BLUE}Testing these paths:${NC}"
        
        while IFS= read -r log_line; do
            if [[ -n "$log_line" ]]; then
                # Extract the date/game part
                local path_match=$(echo "$log_line" | grep -o '[0-9]\{8\}/[A-Z]\{6\}')
                if [[ -n "$path_match" ]]; then
                    echo -e "     Testing: $path_match"
                    
                    # Try different path structures
                    local paths_to_try=(
                        "$BUCKET/$JSON_PATH/$path_match/"
                        "$BUCKET/$JSON_PATH/$(echo $path_match | cut -d'/' -f1)/"
                        "$BUCKET/nba-com/gamebook-data/$path_match/"
                        "$BUCKET/nba-com/gamebooks/$path_match/"
                    )
                    
                    for test_path in "${paths_to_try[@]}"; do
                        if timeout 15 gcloud storage ls "$test_path" >/dev/null 2>&1; then
                            echo -e "       ${GREEN}✅ Found: $test_path${NC}"
                            
                            # Show what's in there
                            local files=$(timeout 15 gcloud storage ls "$test_path" 2>/dev/null | head -3)
                            if [[ -n "$files" ]]; then
                                echo -e "       ${BLUE}Contents:${NC}"
                                echo "$files" | sed 's/^/         /'
                            fi
                            break
                        else
                            echo -e "       ${YELLOW}❌ Not found: $test_path${NC}"
                        fi
                    done
                fi
            fi
        done <<< "$recent_logs"
    else
        echo -e "   ${YELLOW}No recent download logs found${NC}"
    fi
    
    echo ""
    
    # Check if files might be at the root level differently
    echo -e "4. Checking alternate bucket structures:"
    local alt_paths=(
        "gs://nba-scraped-data/nba-com/"
        "gs://nba-scraped-data/gamebooks-data/"
        "gs://nba-scraped-data/gamebook-data/"
        "gs://nba-scraped-data/nba-gamebooks/"
    )
    
    for alt_path in "${alt_paths[@]}"; do
        echo -e "   Testing: $alt_path"
        if timeout 15 gcloud storage ls "$alt_path" >/dev/null 2>&1; then
            echo -e "     ${GREEN}✅ Accessible${NC}"
            local sample_content=$(timeout 15 gcloud storage ls "$alt_path" 2>/dev/null | head -3)
            if [[ -n "$sample_content" ]]; then
                echo "$sample_content" | sed 's/^/       /'
            fi
        else
            echo -e "     ${YELLOW}❌ Not accessible${NC}"
        fi
    done
    
    echo ""
    echo -e "${CYAN}Debug complete!${NC}"
    echo -e "${BLUE}💡 This should help us find where your files actually live${NC}"
}
cmd_test() {
    print_header
    echo -e "${BLUE}🧪 Simple Test Mode:${NC}"
    echo ""
    
    # Test basic GCS access
    echo -e "1. Testing basic GCS access..."
    if gcloud storage ls "$BUCKET/$JSON_PATH/" >/dev/null 2>&1; then
        echo -e "   ${GREEN}✅ Can access bucket and path${NC}"
    else
        echo -e "   ${RED}❌ Cannot access $BUCKET/$JSON_PATH/${NC}"
        return 1
    fi
    
    # Get a few recent date directories
    echo -e "2. Finding recent date directories..."
    local recent_dirs=$(gcloud storage ls "$BUCKET/$JSON_PATH/" 2>/dev/null | \
        grep -E "[0-9]{8}" | sort -r | head -3)
    
    if [[ -n "$recent_dirs" ]]; then
        echo -e "   ${GREEN}✅ Found recent directories:${NC}"
        echo "$recent_dirs" | sed 's/^/     /'
        
        # Test one directory
        local test_date=$(echo "$recent_dirs" | head -1 | xargs basename)
        echo -e "3. Testing directory: $test_date"
        
        local test_path="$BUCKET/$JSON_PATH/$test_date/"
        local games=$(timeout 30 gcloud storage ls "$test_path" 2>/dev/null | head -3)
        
        if [[ -n "$games" ]]; then
            echo -e "   ${GREEN}✅ Found games in $test_date:${NC}"
            echo "$games" | sed 's/^/     /'
            
            # Test one game
            local test_game=$(echo "$games" | head -1 | xargs basename)
            echo -e "4. Testing game: $test_game"
            
            local game_path="$test_path$test_game/"
            local files=$(timeout 30 gcloud storage ls "$game_path" 2>/dev/null | head -2)
            
            if [[ -n "$files" ]]; then
                echo -e "   ${GREEN}✅ Found files in $test_game:${NC}"
                echo "$files" | sed 's/^/     /'
                
                # Test one JSON file if available
                local json_file=$(echo "$files" | grep "\.json$" | head -1)
                if [[ -n "$json_file" ]]; then
                    echo -e "5. Testing JSON file download..."
                    local temp_file="/tmp/test_$(date +%s).json"
                    
                    if gcloud storage cp "$json_file" "$temp_file" >/dev/null 2>&1; then
                        echo -e "   ${GREEN}✅ Downloaded successfully${NC}"
                        
                        if jq empty "$temp_file" 2>/dev/null; then
                            echo -e "   ${GREEN}✅ Valid JSON${NC}"
                            
                            local player_count=$(jq -r '.players | length' "$temp_file" 2>/dev/null)
                            echo -e "   📊 Players: $player_count"
                        else
                            echo -e "   ${RED}❌ Invalid JSON${NC}"
                        fi
                        rm -f "$temp_file"
                    else
                        echo -e "   ${RED}❌ Download failed${NC}"
                    fi
                fi
            else
                echo -e "   ${YELLOW}⚠️  No files found in $test_game${NC}"
            fi
        else
            echo -e "   ${YELLOW}⚠️  No games found in $test_date${NC}"
        fi
    else
        echo -e "   ${RED}❌ No date directories found${NC}"
    fi
    
    echo ""
    echo -e "${CYAN}Test complete!${NC}"
}

show_usage() {
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  test                   - Simple test of GCS access and basic functionality"
    echo "  known                  - Test with dates we know exist (from debug output)"
    echo "  debug                  - Deep exploration of actual GCS structure"
    echo "  recent [N]             - Validate from recent monitoring logs (default: 5)"
    echo "  dates DATE [DATE...]   - Validate specific dates (YYYYMMDD or YYYY-MM-DD)"
    echo ""
    echo "Examples:"
    echo "  $0 test                - Test basic functionality (good for debugging)"
    echo "  $0 known               - Test with confirmed existing dates (2021-10-xx)"
    echo "  $0 debug               - Explore actual GCS structure (BEST for troubleshooting)"
    echo "  $0 recent 5            - Check 5 most recent downloads from logs (FAST)"
    echo "  $0 dates 20231130 20231129  - Check specific dates (YYYYMMDD format)"
    echo "  $0 dates 2023-11-30 2023-11-29  - Check specific dates (YYYY-MM-DD format)" 
    echo ""
    echo "Format Info:"
    echo "  - Monitoring logs use: YYYYMMDD/TEAMCODE (20231130/PORCLE)"
    echo "  - GCS storage uses: YYYY-MM-DD/TEAMCODE (2023-11-30/PORCLE)"
    echo "  - Script automatically converts between formats"
    echo ""
    echo "Tips:"
    echo "  - Use 'known' to test with confirmed existing data"
    echo "  - Use 'debug' to find where your files actually live"
    echo "  - Use 'recent' for fastest results (uses monitoring logs + auto-conversion)"
    echo "  - Script handles both date formats automatically"
    echo "  - All paths are shown for debugging when issues occur"
}

# Main command handling
case "${1:-test}" in
    "test")
        cmd_test
        ;;
    "known")
        cmd_known
        ;;
    "debug")
        cmd_debug
        ;;
    "recent")
        cmd_recent_activity "${2:-5}"
        ;;
    "dates")
        shift  # Remove 'dates' command
        cmd_custom_dates "$@"
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