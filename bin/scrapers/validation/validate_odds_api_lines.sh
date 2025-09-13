#!/bin/bash
# File: bin/scrapers/validation/validate_odds_api_lines.sh
# Purpose: Validate NBA Game Lines data from Odds API

set -e

PROJECT="nba-props-platform"
BUCKET="gs://nba-scraped-data"
LINES_PATH="odds-api/game-lines-history"

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
    echo -e "${CYAN}🏀 NBA ODDS API GAME LINES VALIDATOR${NC}"
    echo -e "${CYAN}================================================${NC}"
    echo -e "Time: $(date)"
    echo -e "Bucket: $BUCKET/$LINES_PATH/"
    echo ""
}

# Validate individual game lines JSON file
validate_lines_json() {
    local file_path="$1"
    local temp_file="/tmp/lines_validate_$(date +%s)_$.json"
    
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
    
    # Extract key data points for game lines
    local analysis=$(jq -r '
        {
            has_timestamp: (has("timestamp")),
            has_data: (has("data") and (.data | type == "array")),
            game_count: (.data | length),
            first_game: (if (.data | length) > 0 then .data[0] else null end)
        } as $base |
        if $base.first_game then
            $base + {
                game_id: ($base.first_game.id // "missing"),
                home_team: ($base.first_game.home_team // "missing"),
                away_team: ($base.first_game.away_team // "missing"),
                commence_time: ($base.first_game.commence_time // "missing"),
                bookmaker_count: ($base.first_game.bookmakers | length),
                bookmaker_names: ($base.first_game.bookmakers | map(.key) | join(",")),
                has_spreads: ($base.first_game.bookmakers | map(select(.markets[] | select(.key == "spreads"))) | length > 0),
                has_totals: ($base.first_game.bookmakers | map(select(.markets[] | select(.key == "totals"))) | length > 0),
                has_h2h: ($base.first_game.bookmakers | map(select(.markets[] | select(.key == "h2h"))) | length > 0),
                spread_range: ([$base.first_game.bookmakers[].markets[] | select(.key == "spreads") | .outcomes[].point] | [min, max]),
                total_range: ([$base.first_game.bookmakers[].markets[] | select(.key == "totals") | .outcomes[].point] | [min, max]),
                h2h_price_range: ([$base.first_game.bookmakers[].markets[] | select(.key == "h2h") | .outcomes[].price] | [min, max])
            }
        else
            $base + {
                game_id: "missing",
                home_team: "missing", 
                away_team: "missing",
                commence_time: "missing",
                bookmaker_count: 0,
                bookmaker_names: "",
                has_spreads: false,
                has_totals: false,
                has_h2h: false,
                spread_range: [null, null],
                total_range: [null, null],
                h2h_price_range: [null, null]
            }
        end
    ' "$temp_file" 2>/dev/null)
    
    if [[ -z "$analysis" ]]; then
        echo -e "    ${RED}❌ Failed to analyze JSON structure${NC}"
        rm -f "$temp_file"
        return 1
    fi
    
    # Extract values
    local has_timestamp=$(echo "$analysis" | jq -r '.has_timestamp')
    local has_data=$(echo "$analysis" | jq -r '.has_data')
    local game_count=$(echo "$analysis" | jq -r '.game_count')
    local game_id=$(echo "$analysis" | jq -r '.game_id')
    local home_team=$(echo "$analysis" | jq -r '.home_team')
    local away_team=$(echo "$analysis" | jq -r '.away_team')
    local commence_time=$(echo "$analysis" | jq -r '.commence_time')
    local bookmaker_count=$(echo "$analysis" | jq -r '.bookmaker_count')
    local bookmaker_names=$(echo "$analysis" | jq -r '.bookmaker_names')
    local has_spreads=$(echo "$analysis" | jq -r '.has_spreads')
    local has_totals=$(echo "$analysis" | jq -r '.has_totals')
    local has_h2h=$(echo "$analysis" | jq -r '.has_h2h')
    local spread_min=$(echo "$analysis" | jq -r '.spread_range[0]')
    local spread_max=$(echo "$analysis" | jq -r '.spread_range[1]')
    local total_min=$(echo "$analysis" | jq -r '.total_range[0]')
    local total_max=$(echo "$analysis" | jq -r '.total_range[1]')
    local h2h_price_min=$(echo "$analysis" | jq -r '.h2h_price_range[0]')
    local h2h_price_max=$(echo "$analysis" | jq -r '.h2h_price_range[1]')
    
    # Validation checks
    local quality_score=0
    local issues=()
    
    # Required structure
    [[ "$has_timestamp" == "true" ]] && quality_score=$((quality_score + 10)) || issues+=("Missing timestamp")
    [[ "$has_data" == "true" ]] && quality_score=$((quality_score + 10)) || issues+=("Missing/invalid data array")
    
    # Game count (expecting 1-15 games per date)
    if [[ $game_count -ge 1 && $game_count -le 15 ]]; then
        quality_score=$((quality_score + 15))
    else
        issues+=("Unusual game count: $game_count")
    fi
    
    # Game info (if we have games)
    if [[ $game_count -gt 0 ]]; then
        [[ "$game_id" != "missing" && "$game_id" != "null" ]] && quality_score=$((quality_score + 10)) || issues+=("Missing game ID")
        [[ "$home_team" != "missing" && "$away_team" != "missing" ]] && quality_score=$((quality_score + 10)) || issues+=("Missing team info")
        [[ "$commence_time" != "missing" ]] && quality_score=$((quality_score + 5)) || issues+=("Missing commence time")
        
        # Bookmaker validation (expecting 2-8 bookmakers)
        if [[ $bookmaker_count -ge 2 && $bookmaker_count -le 8 ]]; then
            quality_score=$((quality_score + 15))
            if [[ "$bookmaker_names" == *"fanduel"* ]]; then
                quality_score=$((quality_score + 10))
            else
                issues+=("Missing fanduel")
            fi
        else
            issues+=("Expected 2-8 bookmakers, got $bookmaker_count")
        fi
        
        # Market type validation
        local market_score=0
        [[ "$has_spreads" == "true" ]] && market_score=$((market_score + 1))
        [[ "$has_totals" == "true" ]] && market_score=$((market_score + 1))
        [[ "$has_h2h" == "true" ]] && market_score=$((market_score + 1))
        
        if [[ $market_score -eq 3 ]]; then
            quality_score=$((quality_score + 15))
        elif [[ $market_score -eq 2 ]]; then
            quality_score=$((quality_score + 10))
            issues+=("Missing 1 market type")
        else
            issues+=("Missing ${$((3 - market_score))} market types")
        fi
        
        # Spread range validation (typically -20 to +20)
        if [[ "$spread_min" != "null" && "$spread_max" != "null" ]]; then
            if [[ $(echo "$spread_min >= -25 && $spread_max <= 25" | bc -l 2>/dev/null || echo 0) -eq 1 ]]; then
                quality_score=$((quality_score + 5))
            else
                issues+=("Spread range: $spread_min to $spread_max")
            fi
        fi
        
        # Total range validation (typically 200-250 for NBA)
        if [[ "$total_min" != "null" && "$total_max" != "null" ]]; then
            if [[ $(echo "$total_min >= 180 && $total_max <= 280" | bc -l 2>/dev/null || echo 0) -eq 1 ]]; then
                quality_score=$((quality_score + 5))
            else
                issues+=("Total range: $total_min to $total_max")
            fi
        fi
        
        # H2H price range validation (typically 1.4-3.0)
        if [[ "$h2h_price_min" != "null" && "$h2h_price_max" != "null" ]]; then
            if [[ $(echo "$h2h_price_min >= 1.2 && $h2h_price_max <= 4.0" | bc -l 2>/dev/null || echo 0) -eq 1 ]]; then
                quality_score=$((quality_score + 5))
            else
                issues+=("H2H price range: $h2h_price_min to $h2h_price_max")
            fi
        fi
    fi
    
    # Display results
    local quality_color=$GREEN
    [[ $quality_score -lt 75 ]] && quality_color=$YELLOW
    [[ $quality_score -lt 50 ]] && quality_color=$RED
    
    echo -e "    ${GREEN}✅ Valid Lines JSON${NC} - ${file_size}B"
    echo -e "    🏀 Games: $game_count"
    
    if [[ $game_count -gt 0 ]]; then
        echo -e "    🏀 Sample: $away_team @ $home_team"
        echo -e "    📊 Bookmakers: $bookmaker_count ($bookmaker_names)"
        echo -e "    📈 Markets: $([ "$has_spreads" == "true" ] && echo "Spreads" || echo "")$([ "$has_totals" == "true" ] && echo " Totals" || echo "")$([ "$has_h2h" == "true" ] && echo " H2H" || echo "")"
        
        if [[ "$spread_min" != "null" ]]; then
            echo -e "    📊 Spreads: $spread_min to $spread_max"
        fi
        if [[ "$total_min" != "null" ]]; then
            echo -e "    📊 Totals: $total_min to $total_max"
        fi
        if [[ "$h2h_price_min" != "null" ]]; then
            echo -e "    💰 H2H Odds: $h2h_price_min to $h2h_price_max"
        fi
    fi
    
    echo -e "    📈 Quality: ${quality_color}$quality_score/100${NC}"
    
    if [[ ${#issues[@]} -gt 0 ]]; then
        echo -e "    ⚠️  Issues: ${issues[*]}"
    fi
    
    rm -f "$temp_file"
    return 0
}

# Check a specific date directory for game lines
check_date_for_lines() {
    local date="$1"
    local date_path="$BUCKET/$LINES_PATH/$date/"
    
    echo -e "  ${BLUE}Checking date:${NC} $date" >&2
    
    if ! timeout 30 gcloud storage ls "$date_path" >/dev/null 2>&1; then
        echo -e "    ${YELLOW}No data for $date${NC}" >&2
        return 1
    fi
    
    # Get JSON files directly from the date directory
    local json_files=$(timeout 30 gcloud storage ls "$date_path" 2>/dev/null | grep "\.json$" | head -3)
    local file_count=$(echo "$json_files" | wc -l | tr -d ' ')
    
    if [[ -n "$json_files" && "$file_count" -gt 0 ]]; then
        echo -e "    ${GREEN}Found $file_count JSON files${NC}" >&2
        echo "$json_files"
        return 0
    else
        echo -e "    ${YELLOW}No JSON files found${NC}" >&2
        return 1
    fi
}

# Get recent dates from the game lines data
get_recent_dates() {
    local count="${1:-3}"
    
    echo -e "Scanning for recent dates..." >&2
    local recent_dates=$(timeout 45 gcloud storage ls "$BUCKET/$LINES_PATH/" 2>/dev/null | \
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
        
        echo -e "${CYAN}[$file_num/${#files[@]}]${NC} $(basename "$file_path")"
        
        if validate_lines_json "$file_path"; then
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
    if gcloud storage ls "$BUCKET/$LINES_PATH/" >/dev/null 2>&1; then
        echo -e "   ${GREEN}✅ Can access game lines data path${NC}"
    else
        echo -e "   ${RED}❌ Cannot access $BUCKET/$LINES_PATH/${NC}"
        return 1
    fi
    
    # Find a recent date
    echo -e "2. Finding recent dates..."
    local test_date=$(get_recent_dates 1)
    
    if [[ -n "$test_date" ]]; then
        echo -e "   ${GREEN}✅ Found recent date: $test_date${NC}"
        
        # Check this date
        local sample_files
        if sample_files=$(check_date_for_lines "$test_date"); then
            if [[ -n "$sample_files" ]]; then
                echo -e "   ${GREEN}✅ Found JSON files${NC}"
                
                # Test one file
                local test_file=$(echo "$sample_files" | head -1)
                echo -e "3. Testing file validation..."
                validate_lines_json "$test_file"
            else
                echo -e "   ${YELLOW}⚠️ No files found in $test_date${NC}"
            fi
        else
            echo -e "   ${YELLOW}⚠️ No data found in $test_date${NC}"
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
                if date_files=$(check_date_for_lines "$date"); then
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
        if date_files=$(check_date_for_lines "$date"); then
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
    echo "  ✅ Game count per date (1-15 games expected)"
    echo "  ✅ Bookmaker presence (2-8 bookmakers, expecting fanduel)"
    echo "  ✅ Market types (spreads, totals, h2h/moneyline)"
    echo "  ✅ Spread ranges (-25 to +25 typical)"
    echo "  ✅ Total ranges (180-280 for NBA)"
    echo "  ✅ H2H price ranges (1.2-4.0 typical)"
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