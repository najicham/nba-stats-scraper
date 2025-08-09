#!/bin/bash
# NBA Schedule JSON Analyzer - Error Game Lookup
# Purpose: Find specific error game codes in schedule JSON and analyze what fields indicate they should be skipped
# Usage: ./analyze_schedule.sh [command] [year]

set -e

PROJECT="nba-props-platform"
GCS_SCHEDULE_PATH="gs://nba-scraped-data"

# The specific error game codes we want to analyze
ERROR_GAME_CODES=(
    "20220218/BARIAH"
    "20220218/PAYBAR" 
    "20220218/WORIAH"
    "20230217/JKMJAS"
    "20230217/JKMPAU"
    "20230217/PAUDRN"
)

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
    echo -e "${CYAN}🏀 NBA SCHEDULE ERROR GAME ANALYZER${NC}"
    echo -e "${CYAN}================================================${NC}"
    echo -e "Time: $(date)"
    echo ""
}

# Function to find schedule files
find_schedule_files() {
    local year=${1:-2022}
    echo -e "${BLUE}🔍 Looking for NBA schedule files for $year...${NC}"
    
    local schedule_patterns=(
        "$GCS_SCHEDULE_PATH/nba-com/schedule/$year*"
        "$GCS_SCHEDULE_PATH/nba-com/schedules/$year*"
        "$GCS_SCHEDULE_PATH/nba/schedule/$year*"
        "$GCS_SCHEDULE_PATH/schedule/$year*"
        "$GCS_SCHEDULE_PATH/**/*schedule*$year*"
        "$GCS_SCHEDULE_PATH/**/*$year*schedule*"
    )
    
    for pattern in "${schedule_patterns[@]}"; do
        local files=$(gcloud storage ls "$pattern" 2>/dev/null || echo "")
        if [ -n "$files" ]; then
            echo "$files"
            return 0
        fi
    done
    
    return 1
}

# Function to convert game code to searchable formats
convert_game_code() {
    local game_code="$1"
    local date_part=$(echo "$game_code" | cut -d'/' -f1)
    local team_part=$(echo "$game_code" | cut -d'/' -f2)
    
    # Convert date formats: 20220218 -> 2022-02-18, 2022/02/18, etc.
    local formatted_date="${date_part:0:4}-${date_part:4:2}-${date_part:6:2}"
    local slash_date="${date_part:0:4}/${date_part:4:2}/${date_part:6:2}"
    
    echo "$formatted_date|$slash_date|$date_part|$team_part"
}

# Function to search for a specific error game in schedule JSON
find_error_game_in_schedule() {
    local game_code="$1"
    local schedule_file="$2"
    local temp_file="/tmp/schedule_search_$$.json"
    
    echo -e "${YELLOW}🔍 Searching for $game_code in $(basename "$schedule_file")...${NC}"
    
    # Download the file
    if ! gcloud storage cp "$schedule_file" "$temp_file" 2>/dev/null; then
        echo -e "  ${RED}❌ Failed to download${NC}"
        return 1
    fi
    
    # Check if it's valid JSON
    if ! jq empty "$temp_file" 2>/dev/null; then
        echo -e "  ${RED}❌ Invalid JSON${NC}"
        rm -f "$temp_file"
        return 1
    fi
    
    # Convert game code to searchable formats
    local search_formats=$(convert_game_code "$game_code")
    local formatted_date=$(echo "$search_formats" | cut -d'|' -f1)
    local slash_date=$(echo "$search_formats" | cut -d'|' -f2)
    local raw_date=$(echo "$search_formats" | cut -d'|' -f3)
    local team_part=$(echo "$search_formats" | cut -d'|' -f4)
    
    echo -e "  Looking for date: $formatted_date (or $slash_date, $raw_date)"
    echo -e "  Looking for teams: $team_part"
    
    # Try different JSON paths to find games
    local game_paths=(
        ".games[]?"
        ".schedule[]?"
        ".data.games[]?"
        ".leagueSchedule.games[]?"
        ".response[]?"
        ".dates[].games[]?"
    )
    
    local found_game=""
    
    for path in "${game_paths[@]}"; do
        # Search for games on this date
        local games_on_date=$(jq -r --arg date1 "$formatted_date" --arg date2 "$slash_date" --arg date3 "$raw_date" "
            $path | select(
                (.game_date // .gameDate // .date // .game_date_est // .dateTimeEst // .startTimeUTC) as \$game_date |
                (\$game_date | contains(\$date1)) or 
                (\$game_date | contains(\$date2)) or 
                (\$game_date | contains(\$date3))
            )
        " "$temp_file" 2>/dev/null)
        
        if [ -n "$games_on_date" ] && [ "$games_on_date" != "null" ]; then
            echo -e "  ${GREEN}✅ Found games on $formatted_date using path: $path${NC}"
            
            # Show all games found on this date
            echo -e "  ${PURPLE}📅 All games on $formatted_date:${NC}"
            echo "$games_on_date" | jq -r '{
                game_id: (.game_id // .gameId // .id // "unknown"),
                date: (.game_date // .gameDate // .date // .game_date_est),
                game_type: (.game_type // .gameType // .type // "unknown"),
                season_type: (.season_type // .seasonType // "unknown"),
                season_stage: (.season_stage // .seasonStage // "unknown"), 
                game_status: (.game_status // .gameStatus // .status // "unknown"),
                period: (.period // "unknown"),
                home_team: (.home_team.abbreviation // .homeTeam.triCode // .home.abbreviation // .home // "unknown"),
                away_team: (.away_team.abbreviation // .awayTeam.triCode // .away.abbreviation // .away // "unknown"),
                arena: (.arena // .venue.name // "unknown")
            }' | sed 's/^/    /'
            
            # Look for the specific team combination
            local specific_game=$(echo "$games_on_date" | jq -r --arg teams "$team_part" '
                select(
                    ((.home_team.abbreviation // .homeTeam.triCode // .home.abbreviation // .home) + 
                     (.away_team.abbreviation // .awayTeam.triCode // .away.abbreviation // .away)) == $teams or
                    ((.away_team.abbreviation // .awayTeam.triCode // .away.abbreviation // .away) + 
                     (.home_team.abbreviation // .homeTeam.triCode // .home.abbreviation // .home)) == $teams
                )
            ' 2>/dev/null)
            
            if [ -n "$specific_game" ] && [ "$specific_game" != "null" ]; then
                echo -e "  ${GREEN}🎯 FOUND EXACT MATCH for $game_code!${NC}"
                echo -e "  ${CYAN}📊 Full game details:${NC}"
                echo "$specific_game" | jq '.' | sed 's/^/    /'
            else
                echo -e "  ${YELLOW}⚠️  Found games on date but no exact team match for $team_part${NC}"
            fi
            
            found_game="$games_on_date"
            break
        fi
    done
    
    if [ -z "$found_game" ]; then
        echo -e "  ${RED}❌ No games found for $formatted_date${NC}"
    fi
    
    rm -f "$temp_file"
    echo ""
}

# Function to analyze all error games
cmd_analyze_errors() {
    local year=${1:-2022}
    print_header
    
    echo -e "${BLUE}🎯 Analyzing specific error game codes:${NC}"
    for game_code in "${ERROR_GAME_CODES[@]}"; do
        echo -e "  • $game_code"
    done
    echo ""
    
    # Get schedule files for the relevant years
    local years=(2022 2023)
    for check_year in "${years[@]}"; do
        echo -e "${CYAN}📁 Year $check_year Schedule Files:${NC}"
        local schedule_files=$(find_schedule_files "$check_year")
        
        if [ -n "$schedule_files" ]; then
            echo "$schedule_files" | head -3 | sed 's/^/  /'
            echo ""
            
            # Pick the first schedule file to analyze
            local first_file=$(echo "$schedule_files" | head -1)
            
            echo -e "${PURPLE}🔎 Analyzing error games in $check_year...${NC}"
            for game_code in "${ERROR_GAME_CODES[@]}"; do
                local game_year=$(echo "$game_code" | cut -c1-4)
                if [ "$game_year" = "$check_year" ]; then
                    find_error_game_in_schedule "$game_code" "$first_file"
                fi
            done
        else
            echo -e "  ${YELLOW}No schedule files found for $check_year${NC}"
        fi
    done
}

# Function to show schedule file structure
cmd_structure() {
    local year=${1:-2022}
    print_header
    
    echo -e "${BLUE}📄 Analyzing schedule file structure for $year...${NC}"
    
    local schedule_files=$(find_schedule_files "$year")
    if [ -n "$schedule_files" ]; then
        local first_file=$(echo "$schedule_files" | head -1)
        local temp_file="/tmp/structure_$$.json"
        
        echo -e "Analyzing: $(basename "$first_file")"
        
        if gcloud storage cp "$first_file" "$temp_file" 2>/dev/null; then
            echo -e "\n${CYAN}📊 Top-level JSON structure:${NC}"
            jq -r 'keys[]?' "$temp_file" 2>/dev/null | head -10 | sed 's/^/  /'
            
            echo -e "\n${CYAN}🎮 Sample game structure:${NC}"
            jq -r '.games[0]? // .schedule[0]? // .data.games[0]? | keys[]?' "$temp_file" 2>/dev/null | head -15 | sed 's/^/  /'
            
            echo -e "\n${CYAN}🏀 Sample game data:${NC}"
            jq -r '.games[0]? // .schedule[0]? // .data.games[0]?' "$temp_file" 2>/dev/null | head -20 | sed 's/^/  /'
            
            rm -f "$temp_file"
        fi
    else
        echo -e "${YELLOW}No schedule files found for $year${NC}"
    fi
}

show_usage() {
    echo "Usage: $0 [command] [year]"
    echo ""
    echo "Commands:"
    echo "  errors [year]     - Analyze specific error game codes (default: search all years)"
    echo "  structure [year]  - Show schedule JSON structure (default: 2022)"
    echo ""
    echo "Examples:"
    echo "  $0 errors         - Find error games 20220218/BARIAH, 20230217/JKMJAS, etc. in schedule"
    echo "  $0 structure 2022 - Show 2022 schedule JSON structure"
    echo ""
    echo "Error games being analyzed:"
    for game_code in "${ERROR_GAME_CODES[@]}"; do
        echo "  • $game_code"
    done
    echo ""
    echo "Goal: Find what JSON fields indicate these games should be skipped"
}

# Main command handling
case "${1:-errors}" in
    "errors")
        cmd_analyze_errors "$2"
        ;;
    "structure")
        cmd_structure "$2"
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