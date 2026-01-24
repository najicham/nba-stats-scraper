#!/bin/bash
# File: bin/validation/validate_bdl_boxscore.sh  
# Purpose: Season-targeted validator for Ball Don't Lie boxscore data

set -euo pipefail

PROJECT="nba-props-platform"
BUCKET="gs://nba-scraped-data"
JSON_PATH="ball-dont-lie/boxscores"

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
    echo -e "${CYAN}🏀 BDL BOXSCORE DATA VALIDATOR${NC}"
    echo -e "${CYAN}================================================${NC}"
    echo -e "Time: $(date)"
    echo -e "Bucket: $BUCKET/$JSON_PATH"
    echo ""
}

# Get recent activity from monitoring logs (for BDL boxscore backfill)
get_recent_activity_from_logs() {
    local count="${1:-10}"
    
    # Look for BDL boxscore download logs
    local recent_logs=$(gcloud logging read \
        "resource.type=cloud_run_job AND textPayload:\"✅ Downloaded\"" \
        --limit=50 \
        --format="value(textPayload)" \
        --project="nba-props-platform" \
        --freshness=30m 2>/dev/null | grep -E "[0-9]{4}-[0-9]{2}-[0-9]{2}" | head -$count)
    
    if [[ -z "$recent_logs" ]]; then
        return 1
    fi
    
    # Extract dates from logs (BDL uses YYYY-MM-DD format directly)
    local recent_dates=()
    while IFS= read -r log_line; do
        if [[ -n "$log_line" ]]; then
            # Extract date in YYYY-MM-DD format
            local date_match=$(echo "$log_line" | grep -o '[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}')
            if [[ -n "$date_match" ]]; then
                recent_dates+=("$date_match")
            fi
        fi
    done <<< "$recent_logs"
    
    # Return unique dates
    printf '%s\n' "${recent_dates[@]}" | sort -u | head -$count
}

# Fallback method using directory scanning
get_recent_activity_dates_fallback() {
    local count="${1:-5}"
    
    echo -e "Scanning for recent date directories..."
    
    # Look for YYYY-MM-DD format directories
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

# Check a specific date for BDL boxscore data
check_date_for_boxscores() {
    local date="$1"
    local date_path="$BUCKET/$JSON_PATH/$date/"
    
    echo -e "  ${BLUE}Checking path:${NC} $date_path" >&2
    
    # Check if date directory exists with timeout
    if ! timeout 30 gcloud storage ls "$date_path" >/dev/null 2>&1; then
        echo -e "    ${YELLOW}No data for $date${NC} (path: $date_path)" >&2
        return 1
    fi
    
    # Get JSON files from this specific date
    local json_files=$(timeout 60 gcloud storage ls --recursive "$date_path" 2>/dev/null | grep "\.json$")
    
    if [[ -n "$json_files" ]]; then
        local json_count=$(echo "$json_files" | wc -l | tr -d ' ')
        echo -e "    ${GREEN}$date${NC}: $json_count JSON files" >&2
        echo -e "    ${BLUE}JSON files found:${NC}" >&2
        echo "$json_files" | sed 's/^/      /' >&2
        
        # Return ONLY the JSON files for validation (to stdout)
        echo "$json_files"
        return 0
    else
        echo -e "    ${YELLOW}No JSON files found in $date${NC}" >&2
        return 1
    fi
}

# Enhanced JSON validation for BDL boxscore structure
validate_json_file() {
    local file_path="$1"
    local temp_file="/tmp/bdl_validate_$(date +%s)_$.json"
    
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
    
    # BDL-specific data analysis
    local analysis=$(jq -r '
        {
            date: (.date // "Unknown"),
            timestamp: (.timestamp // "Unknown"),
            row_count: (.rowCount // 0),
            box_scores_count: ((.boxScores // []) | length),
            has_box_scores: ((.boxScores // []) | length > 0),
            sample_player: ((.boxScores // [])[0].player.first_name // "None") + " " + ((.boxScores // [])[0].player.last_name // ""),
            sample_team: ((.boxScores // [])[0].team.full_name // "Unknown"),
            sample_game_id: ((.boxScores // [])[0].game.id // 0),
            sample_points: ((.boxScores // [])[0].pts // 0),
            sample_minutes: ((.boxScores // [])[0].min // "0:00")
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
    local date=$(echo "$analysis" | jq -r '.date // "Unknown"')
    local timestamp=$(echo "$analysis" | jq -r '.timestamp // "Unknown"')
    local row_count=$(echo "$analysis" | jq -r '.row_count // 0')
    local box_scores_count=$(echo "$analysis" | jq -r '.box_scores_count // 0')
    local has_box_scores=$(echo "$analysis" | jq -r '.has_box_scores // false')
    local sample_player=$(echo "$analysis" | jq -r '.sample_player // "None"')
    local sample_team=$(echo "$analysis" | jq -r '.sample_team // "Unknown"')
    local sample_game_id=$(echo "$analysis" | jq -r '.sample_game_id // 0')
    local sample_points=$(echo "$analysis" | jq -r '.sample_points // 0')
    local sample_minutes=$(echo "$analysis" | jq -r '.sample_minutes // "0:00"')
    
    # Quality assessment for BDL boxscore data
    local quality_score=0
    local quality_notes=()
    
    # Basic structure validation
    if [[ "$has_box_scores" == "true" && $box_scores_count -gt 0 ]]; then
        quality_score=$((quality_score + 25))
    else
        quality_notes+=("No box score data")
    fi
    
    # Row count consistency
    if [[ $row_count -eq $box_scores_count && $row_count -gt 0 ]]; then
        quality_score=$((quality_score + 25))
    else
        quality_notes+=("Row count mismatch: declared $row_count, actual $box_scores_count")
    fi
    
    # Date validation
    if [[ "$date" != "Unknown" && "$date" != "null" && -n "$date" ]]; then
        quality_score=$((quality_score + 20))
    else
        quality_notes+=("Missing/invalid date")
    fi
    
    # Sample data validation
    if [[ "$sample_player" != "None" && "$sample_player" != " " && -n "$sample_player" ]]; then
        quality_score=$((quality_score + 15))
    else
        quality_notes+=("No player names found")
    fi
    
    # Game ID validation
    if [[ $sample_game_id -gt 0 ]]; then
        quality_score=$((quality_score + 15))
    else
        quality_notes+=("Invalid game IDs")
    fi
    
    # Display results with color coding
    local quality_color=$GREEN
    [[ $quality_score -lt 75 ]] && quality_color=$YELLOW
    [[ $quality_score -lt 50 ]] && quality_color=$RED
    
    echo -e "    ${GREEN}✅ Valid BDL Boxscore JSON${NC} - ${file_size}B"
    echo -e "    📅 Date: $date | ⏰ Timestamp: $(echo $timestamp | cut -d'T' -f1)"
    echo -e "    📊 Box Scores: $box_scores_count records (declared: $row_count)"
    echo -e "    👤 Sample Player: ${sample_player} (${sample_team})"
    echo -e "    🏀 Sample Stats: ${sample_points} pts, ${sample_minutes} min (Game ID: $sample_game_id)"
    echo -e "    📈 Quality: ${quality_color}$quality_score/100${NC}"
    
    # Show quality notes if any
    if [[ ${#quality_notes[@]} -gt 0 ]]; then
        echo -e "    ⚠️  Notes: ${quality_notes[*]}"
    fi
    
    # Show additional stats if available
    local stats_summary=$(jq -r '
        if (.boxScores // []) | length > 0 then
            {
                avg_points: ((.boxScores // []) | map(.pts // 0) | add / length | floor),
                max_points: ((.boxScores // []) | map(.pts // 0) | max),
                total_games: ((.boxScores // []) | map(.game.id // 0) | unique | length),
                total_teams: ((.boxScores // []) | map(.team.id // 0) | unique | length)
            }
        else
            null
        end
    ' "$temp_file" 2>/dev/null)
    
    if [[ -n "$stats_summary" && "$stats_summary" != "null" ]]; then
        local avg_points=$(echo "$stats_summary" | jq -r '.avg_points // 0')
        local max_points=$(echo "$stats_summary" | jq -r '.max_points // 0')
        local total_games=$(echo "$stats_summary" | jq -r '.total_games // 0')
        local total_teams=$(echo "$stats_summary" | jq -r '.total_teams // 0')
        
        echo -e "    📊 Stats: Avg ${avg_points} pts, Max ${max_points} pts, ${total_games} games, ${total_teams} teams"
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

# Validate a sample of files from specific dates
validate_date_sample() {
    local dates=("$@")
    
    echo -e "${BLUE}🔍 Validating sample files from selected dates:${NC}"
    echo ""
    
    local total_files=0
    local valid_files=0
    local sample_files=()
    
    # Collect files from each date
    for date in "${dates[@]}"; do
        echo -e "${CYAN}Checking $date:${NC}"
        
        # Call check_date_for_boxscores and capture output
        local date_files
        if date_files=$(check_date_for_boxscores "$date"); then
            # Process the returned files
            if [[ -n "$date_files" ]]; then
                # Add files to our sample (limit to first 2 per date for speed)
                while IFS= read -r file; do
                    if [[ -n "$file" ]]; then
                        sample_files+=("$file")
                    fi
                done <<< "$(echo "$date_files" | head -2)"
            fi
        fi
        echo ""
    done
    
    # Validate the collected sample files
    if [[ ${#sample_files[@]} -gt 0 ]]; then
        validate_sample_files "${sample_files[@]}"
    else
        echo -e "${YELLOW}No files found in the specified dates${NC}"
        
        # Show which dates were checked for debugging
        echo -e "${BLUE}Dates checked:${NC}"
        for date in "${dates[@]}"; do
            echo -e "  $date -> $BUCKET/$JSON_PATH/$date/"
        done
    fi
}

# Recent activity command - uses monitoring logs
cmd_recent_activity() {
    local count="${1:-5}"
    
    print_header
    echo -e "${BLUE}📅 Recent Activity Validation (from BDL backfill logs):${NC}"
    echo ""
    
    # Get recent activity from logs
    echo -e "Getting recent activity from BDL backfill logs..."
    local recent_activities
    recent_activities=$(get_recent_activity_from_logs "$count")
    
    if [[ -n "$recent_activities" ]]; then
        echo -e "${GREEN}Found recent activity from backfill logs:${NC}"
        echo "$recent_activities" | sed 's/^/  /'
        echo ""
        
        # Convert to array for validation
        local dates_array=()
        while IFS= read -r date; do
            if [[ -n "$date" && "$date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
                dates_array+=("$date")
            fi
        done <<< "$recent_activities"
        
        if [[ ${#dates_array[@]} -gt 0 ]]; then
            validate_date_sample "${dates_array[@]}"
        else
            echo -e "${YELLOW}No valid dates found in recent activity${NC}"
        fi
    else
        echo -e "${YELLOW}No recent activity found in logs, trying fallback method...${NC}"
        echo ""
        
        # Fallback to date-based checking
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

# Custom date validation
cmd_custom_dates() {
    local dates=("$@")
    
    if [[ ${#dates[@]} -eq 0 ]]; then
        echo "Usage: $0 dates YYYY-MM-DD [YYYY-MM-DD ...]"
        echo ""
        echo "Examples:"
        echo "  $0 dates 2023-01-15 2023-02-20 2023-03-10"
        echo "  $0 dates 2024-01-01"
        return 1
    fi
    
    print_header
    echo -e "${BLUE}🗓️ Custom Date Validation:${NC}"
    
    # Validate date format
    local validated_dates=()
    for date in "${dates[@]}"; do
        if [[ "$date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
            validated_dates+=("$date")
            echo -e "  Using $date"
        else
            echo -e "  ${RED}Invalid date format: $date${NC} (expected YYYY-MM-DD)"
            return 1
        fi
    done
    
    echo ""
    validate_date_sample "${validated_dates[@]}"
}

# Quick test command
cmd_test() {
    print_header
    echo -e "${BLUE}🧪 Simple Test Mode (BDL Boxscores):${NC}"
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
        grep -E "[0-9]{4}-[0-9]{2}-[0-9]{2}" | sort -r | head -3)
    
    if [[ -n "$recent_dirs" ]]; then
        echo -e "   ${GREEN}✅ Found recent directories:${NC}"
        echo "$recent_dirs" | sed 's/^/     /'
        
        # Test one directory
        local test_date=$(echo "$recent_dirs" | head -1 | xargs basename)
        echo -e "3. Testing directory: $test_date"
        
        local test_path="$BUCKET/$JSON_PATH/$test_date/"
        local files=$(timeout 30 gcloud storage ls --recursive "$test_path" 2>/dev/null | grep "\.json$" | head -2)
        
        if [[ -n "$files" ]]; then
            echo -e "   ${GREEN}✅ Found JSON files in $test_date:${NC}"
            echo "$files" | sed 's/^/     /'
            
            # Test one JSON file
            local test_file=$(echo "$files" | head -1)
            echo -e "4. Testing JSON file download and validation..."
            
            if validate_json_file "$test_file"; then
                echo -e "   ${GREEN}✅ File validation passed${NC}"
            else
                echo -e "   ${RED}❌ File validation failed${NC}"
            fi
        else
            echo -e "   ${YELLOW}⚠️  No JSON files found in $test_date${NC}"
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
    echo "  test                   - Simple test of GCS access and validation"
    echo "  recent [N]             - Validate from recent monitoring logs (default: 5)"
    echo "  dates DATE [DATE...]   - Validate specific dates (YYYY-MM-DD format)"
    echo ""
    echo "Examples:"
    echo "  $0 test                - Test basic functionality"
    echo "  $0 recent 5            - Check 5 most recent downloads from logs"
    echo "  $0 dates 2023-11-30 2023-11-29  - Check specific dates"
    echo ""
    echo "BDL-Specific Notes:"
    echo "  - Validates Ball Don't Lie boxscore JSON structure"
    echo "  - Checks for player stats, game data, and data consistency"
    echo "  - Uses YYYY-MM-DD date format (same as API)"
    echo "  - Faster validation than gamebook (fewer fields to check)"
}

# Main command handling
case "${1:-test}" in
    "test")
        cmd_test
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