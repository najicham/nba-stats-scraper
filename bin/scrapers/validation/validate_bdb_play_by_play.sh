#!/bin/bash
# File: bin/scrapers/validation/validate_bdb_play_by_play.sh
# Purpose: Validate BigDataBall play-by-play data in GCS
# Usage: ./bin/scrapers/validation/validate_bdb_play_by_play.sh [command] [options]

set -e

PROJECT_ID=${GCP_PROJECT_ID:-"nba-props-platform"}
BUCKET="gs://nba-scraped-data"
GCS_PATH="bigdataball/play-by-play"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_header() {
    echo -e "${CYAN}================================================${NC}"
    echo -e "${CYAN}BigDataBall Play-by-Play Data Validator${NC}"
    echo -e "${CYAN}================================================${NC}"
    echo -e "Time: $(date)"
    echo -e "Bucket: $BUCKET/$GCS_PATH"
    echo ""
}

show_usage() {
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  test                   - Test basic GCS access and validate a sample file"
    echo "  recent [N]             - Validate N most recent date directories (default: 5)"
    echo "  dates DATE [DATE...]   - Validate specific dates (YYYY-MM-DD format)"
    echo "  summary                - Show overall data summary"
    echo ""
    echo "Examples:"
    echo "  $0 test                     - Quick test"
    echo "  $0 recent 10                - Check 10 most recent dates"
    echo "  $0 dates 2024-01-15         - Check specific date"
    echo "  $0 summary                  - Overall statistics"
}

# Validate a JSON file's structure
validate_json_file() {
    local file_path="$1"
    local temp_file="/tmp/bdb_pbp_validate_$$.json"

    echo -e "  ${BLUE}Downloading:${NC} $file_path"
    if ! gcloud storage cp "$file_path" "$temp_file" >/dev/null 2>&1; then
        echo -e "  ${RED}Failed to download${NC}"
        return 1
    fi

    # Check file size
    local file_size=$(stat -c%s "$temp_file" 2>/dev/null || stat -f%z "$temp_file" 2>/dev/null || echo "0")
    if [[ $file_size -eq 0 ]]; then
        echo -e "  ${RED}Downloaded file is empty${NC}"
        rm -f "$temp_file"
        return 1
    fi

    # Validate JSON
    if ! jq empty "$temp_file" 2>/dev/null; then
        echo -e "  ${RED}Invalid JSON format${NC}"
        rm -f "$temp_file"
        return 1
    fi

    # Analyze play-by-play structure
    local analysis=$(jq -r '
        {
            game_id: (.game_id // .gameId // "Unknown"),
            date: (.date // .game_date // "Unknown"),
            total_plays: (if type == "array" then length else (.plays // []) | length end),
            has_plays: (if type == "array" then length > 0 else ((.plays // []) | length) > 0 end),
            teams: (.teams // [(.home_team // "?"), (.away_team // "?")] | join(" vs "))
        }
    ' "$temp_file" 2>/dev/null)

    if [[ -n "$analysis" ]]; then
        local game_id=$(echo "$analysis" | jq -r '.game_id')
        local date_val=$(echo "$analysis" | jq -r '.date')
        local total_plays=$(echo "$analysis" | jq -r '.total_plays')
        local teams=$(echo "$analysis" | jq -r '.teams')

        echo -e "  ${GREEN}Valid JSON${NC} - ${file_size} bytes"
        echo -e "    Game ID: $game_id"
        echo -e "    Date: $date_val"
        echo -e "    Plays: $total_plays"
        echo -e "    Teams: $teams"
    else
        echo -e "  ${GREEN}Valid JSON${NC} - ${file_size} bytes (structure varies)"
    fi

    rm -f "$temp_file"
    return 0
}

# Test command
cmd_test() {
    print_header
    echo -e "${BLUE}Running quick test...${NC}"
    echo ""

    # Test GCS access
    echo "1. Testing GCS access..."
    if gcloud storage ls "$BUCKET/$GCS_PATH/" >/dev/null 2>&1; then
        echo -e "   ${GREEN}GCS access OK${NC}"
    else
        echo -e "   ${RED}Cannot access $BUCKET/$GCS_PATH/${NC}"
        return 1
    fi

    # Find recent directories
    echo "2. Finding recent data..."
    local recent_dirs=$(gcloud storage ls "$BUCKET/$GCS_PATH/" 2>/dev/null | sort -r | head -3)

    if [[ -n "$recent_dirs" ]]; then
        echo -e "   ${GREEN}Found directories:${NC}"
        echo "$recent_dirs" | sed 's/^/     /'

        # Test first file from most recent directory
        local test_dir=$(echo "$recent_dirs" | head -1)
        echo "3. Testing sample file from: $test_dir"

        local test_file=$(gcloud storage ls "$test_dir" 2>/dev/null | grep "\.json$" | head -1)
        if [[ -n "$test_file" ]]; then
            validate_json_file "$test_file"
        else
            echo -e "   ${YELLOW}No JSON files found in directory${NC}"
        fi
    else
        echo -e "   ${YELLOW}No data directories found${NC}"
    fi

    echo ""
    echo -e "${CYAN}Test complete!${NC}"
}

# Recent validation command
cmd_recent() {
    local count="${1:-5}"
    print_header
    echo -e "${BLUE}Validating $count most recent dates...${NC}"
    echo ""

    local recent_dirs=$(gcloud storage ls "$BUCKET/$GCS_PATH/" 2>/dev/null | \
        grep -E "[0-9]{4}-[0-9]{2}-[0-9]{2}" | sort -r | head -$count)

    if [[ -z "$recent_dirs" ]]; then
        echo -e "${RED}No date directories found${NC}"
        return 1
    fi

    local valid_count=0
    local total_count=0

    while IFS= read -r dir; do
        if [[ -n "$dir" ]]; then
            local date_name=$(basename "$dir")
            echo -e "${CYAN}Checking $date_name:${NC}"

            # Count JSON files
            local json_files=$(gcloud storage ls "$dir" 2>/dev/null | grep "\.json$" || true)
            local file_count=$(echo "$json_files" | grep -c "\.json$" 2>/dev/null || echo "0")

            echo -e "  Files: $file_count JSON files"

            if [[ $file_count -gt 0 ]]; then
                # Validate first file
                local sample_file=$(echo "$json_files" | head -1)
                if validate_json_file "$sample_file"; then
                    valid_count=$((valid_count + 1))
                fi
            fi

            total_count=$((total_count + 1))
            echo ""
        fi
    done <<< "$recent_dirs"

    echo -e "${CYAN}Summary: $valid_count/$total_count dates validated successfully${NC}"
}

# Custom dates command
cmd_dates() {
    local dates=("$@")

    if [[ ${#dates[@]} -eq 0 ]]; then
        echo "Usage: $0 dates YYYY-MM-DD [YYYY-MM-DD ...]"
        return 1
    fi

    print_header
    echo -e "${BLUE}Validating specified dates...${NC}"
    echo ""

    for date in "${dates[@]}"; do
        if [[ ! "$date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
            echo -e "${RED}Invalid date format: $date (expected YYYY-MM-DD)${NC}"
            continue
        fi

        local date_path="$BUCKET/$GCS_PATH/$date/"
        echo -e "${CYAN}Checking $date:${NC}"

        if ! gcloud storage ls "$date_path" >/dev/null 2>&1; then
            echo -e "  ${YELLOW}No data for $date${NC}"
            continue
        fi

        local json_files=$(gcloud storage ls "$date_path" 2>/dev/null | grep "\.json$" || true)
        local file_count=$(echo "$json_files" | grep -c "\.json$" 2>/dev/null || echo "0")

        echo -e "  Files: $file_count JSON files"

        if [[ $file_count -gt 0 ]]; then
            local sample_file=$(echo "$json_files" | head -1)
            validate_json_file "$sample_file"
        fi
        echo ""
    done
}

# Summary command
cmd_summary() {
    print_header
    echo -e "${BLUE}Overall Data Summary${NC}"
    echo ""

    echo "1. Total date directories:"
    local total_dirs=$(gcloud storage ls "$BUCKET/$GCS_PATH/" 2>/dev/null | \
        grep -E "[0-9]{4}-[0-9]{2}-[0-9]{2}" | wc -l || echo "0")
    echo -e "   ${GREEN}$total_dirs dates${NC}"

    echo ""
    echo "2. Date range:"
    local all_dates=$(gcloud storage ls "$BUCKET/$GCS_PATH/" 2>/dev/null | \
        grep -E "[0-9]{4}-[0-9]{2}-[0-9]{2}" | sort)
    local first_date=$(echo "$all_dates" | head -1 | xargs basename 2>/dev/null || echo "N/A")
    local last_date=$(echo "$all_dates" | tail -1 | xargs basename 2>/dev/null || echo "N/A")
    echo -e "   First: $first_date"
    echo -e "   Last:  $last_date"

    echo ""
    echo "3. Recent 5 dates:"
    echo "$all_dates" | tail -5 | while read dir; do
        local date_name=$(basename "$dir")
        local file_count=$(gcloud storage ls "$dir" 2>/dev/null | grep -c "\.json$" 2>/dev/null || echo "0")
        echo -e "   $date_name: $file_count files"
    done

    echo ""
    echo -e "${CYAN}Summary complete!${NC}"
}

# Main command handling
case "${1:-test}" in
    "test")
        cmd_test
        ;;
    "recent")
        cmd_recent "${2:-5}"
        ;;
    "dates")
        shift
        cmd_dates "$@"
        ;;
    "summary")
        cmd_summary
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
