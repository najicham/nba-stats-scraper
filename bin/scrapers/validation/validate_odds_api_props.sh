#!/bin/bash
# File: bin/validation/validate_odds_api_props.sh
# Purpose: Validate NBA Player Props data from Odds API

set -e

PROJECT="nba-props-platform"
BUCKET="gs://nba-scraped-data"
ODDS_PATH="odds-api/player-props-history"

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
    echo -e "${CYAN}🏀 NBA ODDS API DATA VALIDATOR${NC}"
    echo -e "${CYAN}================================================${NC}"
    echo -e "Time: $(date)"
    echo -e "Bucket: $BUCKET/$ODDS_PATH/"
    echo ""
}

# Validate individual odds JSON file
validate_odds_json() {
    local file_path="$1"
    local temp_file="/tmp/odds_validate_$(date +%s)_$.json"
    
    echo -e "    ${BLUE}Downloading:${NC} $(basename "$file_path")"
    
    # Download file
    if ! gcloud storage cp "$file_path" "$temp_file" >/dev/null 2>&1; then
        echo -e "    ${RED}❌ Download failed${NC}"
        return 1
    fi
    
    # Check file size
    local file_size=$(stat -f%z "$temp_file" 2>/dev/null || stat -c%s "$temp_file" 2>/dev/null || echo "0")
    if [[ $file_size -eq 0 ]]; then
        echo -e "    ${RED}❌ File is empty${NC}"
        rm -f "$temp_file"
        return 1
    fi
    
    # Validate JSON
    if ! jq empty "$temp_file" 2>/dev/null; then
        echo -e "    ${RED}❌ Invalid JSON format${NC}"
        rm -f "$temp_file"
        return 1
    fi
    
    # Extract key data points
    local analysis=$(jq -r '
        {
            has_timestamp: (has("timestamp")),
            has_data: (has("data")),
            game_id: (.data.id // "missing"),
            home_team: (.data.home_team // "missing"),
            away_team: (.data.away_team // "missing"),
            bookmaker_count: (.data.bookmakers | length),
            bookmaker_names: (.data.bookmakers | map(.key) | join(",")),
            total_outcomes: (.data.bookmakers | map(.markets[0].outcomes | length) | add),
            player_count: (.data.bookmakers[0].markets[0].outcomes | map(.description) | unique | length),
            point_range: (.data.bookmakers[0].markets[0].outcomes | map(.point) | [min, max]),
            price_range: (.data.bookmakers[0].markets[0].outcomes | map(.price) | [min, max])
        }
    ' "$temp_file" 2>/dev/null)
    
    if [[ -z "$analysis" ]]; then
        echo -e "    ${RED}❌ Failed to analyze JSON structure${NC}"
        rm -f "$temp_file"
        return 1
    fi
    
    # Extract values
    local has_timestamp=$(echo "$analysis" | jq -r '.has_timestamp')
    local has_data=$(echo "$analysis" | jq -r '.has_data')
    local game_id=$(echo "$analysis" | jq -r '.game_id')
    local home_team=$(echo "$analysis" | jq -r '.home_team')
    local away_team=$(echo "$analysis" | jq -r '.away_team')
    local bookmaker_count=$(echo "$analysis" | jq -r '.bookmaker_count')
    local bookmaker_names=$(echo "$analysis" | jq -r '.bookmaker_names')
    local total_outcomes=$(echo "$analysis" | jq -r '.total_outcomes')
    local player_count=$(echo "$analysis" | jq -r '.player_count')
    local point_min=$(echo "$analysis" | jq -r '.point_range[0]')
    local point_max=$(echo "$analysis" | jq -r '.point_range[1]')
    local price_min=$(echo "$analysis" | jq -r '.price_range[0]')
    local price_max=$(echo "$analysis" | jq -r '.price_range[1]')
    
    # Validation checks
    local quality_score=0
    local issues=()
    
    # Required structure
    [[ "$has_timestamp" == "true" ]] && quality_score=$((quality_score + 10)) || issues+=("Missing timestamp")
    [[ "$has_data" == "true" ]] && quality_score=$((quality_score + 10)) || issues+=("Missing data")
    
    # Game info
    [[ "$game_id" != "missing" && "$game_id" != "null" ]] && quality_score=$((quality_score + 10)) || issues+=("Missing game ID")
    [[ "$home_team" != "missing" && "$away_team" != "missing" ]] && quality_score=$((quality_score + 10)) || issues+=("Missing team info")
    
    # Bookmaker validation
    if [[ $bookmaker_count -eq 2 ]]; then
        quality_score=$((quality_score + 20))
        if [[ "$bookmaker_names" == *"fanduel"* ]]; then
            quality_score=$((quality_score + 10))
        else
            issues+=("Missing fanduel")
        fi
    else
        issues+=("Expected 2 bookmakers, got $bookmaker_count")
    fi
    
    # Props count validation (expecting 20-60 total outcomes for a good file)
    if [[ $total_outcomes -ge 20 && $total_outcomes -le 100 ]]; then
        quality_score=$((quality_score + 15))
    else
        issues+=("Unusual outcome count: $total_outcomes")
    fi
    
    # Point range validation (0-50 reasonable for NBA)
    if [[ $(echo "$point_min >= 0 && $point_max <= 50" | bc -l 2>/dev/null || echo 0) -eq 1 ]]; then
        quality_score=$((quality_score + 10))
    else
        issues+=("Point range: $point_min-$point_max")
    fi
    
    # Price range validation (1.5-3.0 typical)
    if [[ $(echo "$price_min >= 1.4 && $price_max <= 3.5" | bc -l 2>/dev/null || echo 0) -eq 1 ]]; then
        quality_score=$((quality_score + 15))
    else
        issues+=("Price range: $price_min-$price_max")
    fi
    
    # Display results
    local quality_color=$GREEN
    [[ $quality_score -lt 75 ]] && quality_color=$YELLOW
    [[ $quality_score -lt 50 ]] && quality_color=$RED
    
    echo -e "    ${GREEN}✅ Valid Odds JSON${NC} - ${file_size}B"
    echo -e "    🏀 Game: $away_team @ $home_team"
    echo -e "    📊 Bookmakers: $bookmaker_count ($bookmaker_names)"
    echo -e "    🎯 Props: $total_outcomes outcomes for $player_count players"
    echo -e "    📈 Points: $point_min-$point_max | 💰 Odds: $price_min-$price_max"
    echo -e "    📈 Quality: ${quality_color}$quality_score/100${NC}"
    
    if [[ ${#issues[@]} -gt 0 ]]; then
        echo -e "    ⚠️  Issues: ${issues[*]}"
    fi
    
    rm -f "$temp_file"
    return 0
}

# Check a specific date directory for games
check_date_for_odds() {
    local date="$1"
    local date_path="$BUCKET/$ODDS_PATH/$date/"
    
    echo -e "  ${BLUE}Checking date:${NC} $date" >&2
    
    if ! timeout 30 gcloud storage ls "$date_path" >/dev/null 2>&1; then
        echo -e "    ${YELLOW}No data for $date${NC}" >&2
        return 1
    fi
    
    # Get game directories
    local game_dirs=$(timeout 30 gcloud storage ls "$date_path" 2>/dev/null | grep "/" | head -5)
    local game_count=$(echo "$game_dirs" | wc -l | tr -d ' ')
    
    echo -e "    ${GREEN}Found $game_count games${NC}" >&2
    
    # Get sample JSON files from games
    local sample_files=()
    while IFS= read -r game_dir; do
        if [[ -n "$game_dir" ]]; then
            local json_files=$(timeout 20 gcloud storage ls "$game_dir" 2>/dev/null | grep "\.json$" | head -1)
            if [[ -n "$json_files" ]]; then
                sample_files+=("$json_files")
            fi
        fi
    done <<< "$game_dirs"
    
    if [[ ${#sample_files[@]} -gt 0 ]]; then
        echo -e "    ${BLUE}Sample files found: ${#sample_files[@]}${NC}" >&2
        # Return files for validation
        printf '%s\n' "${sample_files[@]}"
        return 0
    else
        echo -e "    ${YELLOW}No JSON files found${NC}" >&2
        return 1
    fi
}

# Get recent dates from the odds API data
get_recent_dates() {
    local count="${1:-3}"
    
    echo -e "Scanning for recent dates..." >&2
    local recent_dates=$(timeout 45 gcloud storage ls "$BUCKET/$ODDS_PATH/" 2>/dev/null | \
        grep -E "[0-9]{4}-[0-9]{2}-[0-9]{2}" | \
        sort -r | head -$count | xargs -I {} basename {})
    
    if [[ -n "$recent_dates" ]]; then
        echo "$recent_dates"
        return 0
    else
        return 1
    fi
}

# Validate sample files
validate_sample_files() {
    local files=("$@")
    
    echo -e "${BLUE}📊 Validating ${#files[@]} sample files:${NC}"
    echo ""
    
    local valid_files=0
    local file_num=0
    
    for file_path in "${files[@]}"; do
        file_num=$((file_num + 1))
        
        echo -e "${CYAN}[$file_num/${#files[@]}]${NC} $(basename "$(dirname "$file_path")")/$(basename "$file_path")"
        
        if validate_odds_json "$file_path"; then
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

# Commands
cmd_test() {
    print_header
    echo -e "${BLUE}🧪 Basic Test Mode${NC}"
    echo ""
    
    # Test GCS access
    echo -e "1. Testing GCS access..."
    if gcloud storage ls "$BUCKET/$ODDS_PATH/" >/dev/null 2>&1; then
        echo -e "   ${GREEN}✅ Can access odds data path${NC}"
    else
        echo -e "   ${RED}❌ Cannot access $BUCKET/$ODDS_PATH/${NC}"
        return 1
    fi
    
    # Find a recent date
    echo -e "2. Finding recent dates..."
    local test_date=$(get_recent_dates 1)
    
    if [[ -n "$test_date" ]]; then
        echo -e "   ${GREEN}✅ Found recent date: $test_date${NC}"
        
        # Check this date
        local sample_files
        if sample_files=$(check_date_for_odds "$test_date"); then
            if [[ -n "$sample_files" ]]; then
                echo -e "   ${GREEN}✅ Found JSON files${NC}"
                
                # Test one file
                local test_file=$(echo "$sample_files" | head -1)
                echo -e "3. Testing file validation..."
                validate_odds_json "$test_file"
            else
                echo -e "   ${YELLOW}⚠️ No files found in $test_date${NC}"
            fi
        else
            echo -e "   ${YELLOW}⚠️ No games found in $test_date${NC}"
        fi
    else
        echo -e "   ${RED}❌ No recent dates found${NC}"
    fi
}

cmd_recent() {
    local count="${1:-3}"
    
    print_header
    echo -e "${BLUE}📅 Recent Dates Validation${NC}"
    echo ""
    
    local recent_dates
    if recent_dates=$(get_recent_dates "$count"); then
        echo -e "${GREEN}Recent dates found:${NC}"
        echo "$recent_dates" | sed 's/^/  /'
        echo ""
        
        # Collect sample files from each date
        local all_files=()
        while IFS= read -r date; do
            if [[ -n "$date" ]]; then
                echo -e "${CYAN}Processing $date:${NC}"
                local date_files
                if date_files=$(check_date_for_odds "$date"); then
                    while IFS= read -r file; do
                        if [[ -n "$file" ]]; then
                            all_files+=("$file")
                        fi
                    done <<< "$date_files"
                fi
                echo ""
            fi
        done <<< "$recent_dates"
        
        # Validate collected files
        if [[ ${#all_files[@]} -gt 0 ]]; then
            validate_sample_files "${all_files[@]}"
        else
            echo -e "${YELLOW}No files found to validate${NC}"
        fi
    else
        echo -e "${RED}No recent dates found${NC}"
    fi
}

cmd_dates() {
    local dates=("$@")
    
    if [[ ${#dates[@]} -eq 0 ]]; then
        echo "Usage: $0 dates YYYY-MM-DD [YYYY-MM-DD ...]"
        echo ""
        echo "Examples:"
        echo "  $0 dates 2023-10-25"
        echo "  $0 dates 2023-10-25 2023-10-26 2023-10-27"
        return 1
    fi
    
    print_header
    echo -e "${BLUE}🗓️ Custom Date Validation${NC}"
    echo ""
    
    # Collect files from specified dates
    local all_files=()
    for date in "${dates[@]}"; do
        echo -e "${CYAN}Processing $date:${NC}"
        local date_files
        if date_files=$(check_date_for_odds "$date"); then
            while IFS= read -r file; do
                if [[ -n "$file" ]]; then
                    all_files+=("$file")
                fi
            done <<< "$date_files"
        fi
        echo ""
    done
    
    # Validate collected files
    if [[ ${#all_files[@]} -gt 0 ]]; then
        validate_sample_files "${all_files[@]}"
    else
        echo -e "${YELLOW}No files found in specified dates${NC}"
    fi
}

show_usage() {
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  test           - Basic test of GCS access and file validation"
    echo "  recent [N]     - Validate N most recent dates (default: 3)"
    echo "  dates DATE ... - Validate specific dates (YYYY-MM-DD format)"
    echo ""
    echo "Examples:"
    echo "  $0 test                    - Test basic functionality"
    echo "  $0 recent 5                - Check 5 most recent dates"
    echo "  $0 dates 2023-10-25       - Check specific date"
    echo "  $0 dates 2023-10-25 2023-10-26  - Check multiple dates"
    echo ""
    echo "What it validates:"
    echo "  ✅ JSON structure and required fields"
    echo "  ✅ Bookmaker presence (expecting fanduel + 1 other)"
    echo "  ✅ Props count per game (20-100 outcomes expected)"
    echo "  ✅ Point ranges (0-50 for NBA scoring)"
    echo "  ✅ Odds/price ranges (1.4-3.5 typical)"
    echo "  ✅ Game and team information completeness"
}

# Main command handling
case "${1:-test}" in
    "test")
        cmd_test
        ;;
    "recent")
        cmd_recent "${2:-3}"
        ;;
    "dates")
        shift  # Remove 'dates' command
        cmd_dates "$@"
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