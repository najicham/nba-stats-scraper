#!/bin/bash
# File: bin/monitoring/validate_gcs_working.sh  
# Purpose: Working validator for actual NBA gamebook file structure

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
    echo -e "${CYAN}🔍 NBA GAMEBOOK DATA VALIDATOR (WORKING)${NC}"
    echo -e "${CYAN}================================================${NC}"
    echo -e "Time: $(date)"
    echo ""
}

# Get recent JSON files based on actual structure
get_recent_json_files() {
    local count=${1:-5}
    
    # Get the most recent date folders (where current downloads are happening)
    # Since logs show January 2023, let's check recent months
    local date_patterns=("2023-01" "2022-12" "2023-02")
    local recent_files=()
    
    for pattern in "${date_patterns[@]}"; do
        # Get date folders matching this pattern
        local date_folders=$(gcloud storage ls "$BUCKET/$JSON_PATH/" 2>/dev/null | grep "$pattern" | tail -3)
        
        while IFS= read -r date_folder; do
            if [[ -n "$date_folder" ]]; then
                # Get game folders in this date folder
                local game_folders=$(gcloud storage ls "$date_folder" 2>/dev/null | head -3)
                
                while IFS= read -r game_folder; do
                    if [[ -n "$game_folder" ]]; then
                        # Get the most recent JSON file in this game folder
                        local json_file=$(gcloud storage ls "$game_folder" 2>/dev/null | grep "\.json$" | tail -1)
                        
                        if [[ -n "$json_file" ]]; then
                            recent_files+=("$json_file")
                        fi
                    fi
                done <<< "$game_folders"
            fi
        done <<< "$date_folders"
        
        # Stop if we have enough files
        [[ ${#recent_files[@]} -ge $count ]] && break
    done
    
    # Return the most recent files
    printf '%s\n' "${recent_files[@]}" | tail -$count
}

# Validate a JSON file
validate_json_file() {
    local file_path="$1"
    local temp_file="/tmp/nba_validate_$(date +%s).json"
    
    # Extract game info from path
    local game_code=$(echo "$file_path" | grep -o 'game_[0-9]*_[A-Z]*' | sed 's/game_//' | sed 's/_/\//')
    
    # Download file
    if ! gcloud storage cp "$file_path" "$temp_file" >/dev/null 2>&1; then
        echo -e "    ${RED}❌ Download failed${NC}"
        return 1
    fi
    
    # Validate JSON structure
    if ! jq empty "$temp_file" 2>/dev/null; then
        echo -e "    ${RED}❌ Invalid JSON format${NC}"
        rm -f "$temp_file"
        return 1
    fi
    
    # Extract data
    local total_players=$(jq -r '.players | length' "$temp_file" 2>/dev/null || echo "0")
    local active_players=$(jq -r '[.players[] | select(.status == "ACTIVE")] | length' "$temp_file" 2>/dev/null || echo "0")
    local dnp_players=$(jq -r '[.players[] | select(.status == "DNP")] | length' "$temp_file" 2>/dev/null || echo "0")
    local inactive_players=$(jq -r '[.players[] | select(.status == "INACTIVE")] | length' "$temp_file" 2>/dev/null || echo "0")
    
    # Game info
    local arena=$(jq -r '.game_info.arena // "Unknown"' "$temp_file" 2>/dev/null)
    local attendance=$(jq -r '.game_info.attendance // "Unknown"' "$temp_file" 2>/dev/null)
    
    # Sample players
    local sample_active=$(jq -r '[.players[] | select(.status == "ACTIVE")] | .[0] | "\(.player_name): \(.pts // "N/A") pts, \(.min // "N/A") min"' "$temp_file" 2>/dev/null)
    local sample_dnp=$(jq -r '[.players[] | select(.status == "DNP")] | .[0] | "\(.player_name): \(.dnp_reason // "No reason")"' "$temp_file" 2>/dev/null)
    
    # Data quality assessment
    local quality_score=0
    local quality_notes=()
    
    # Player count checks
    if [[ $total_players -ge 35 && $total_players -le 50 ]]; then
        quality_score=$((quality_score + 25))
    else
        quality_notes+=("Unusual player count: $total_players")
    fi
    
    # Active player checks
    if [[ $active_players -ge 15 && $active_players -le 25 ]]; then
        quality_score=$((quality_score + 25))
    else
        quality_notes+=("Unusual active count: $active_players")
    fi
    
    # Arena check
    if [[ "$arena" != "Unknown" && "$arena" != "null" ]]; then
        quality_score=$((quality_score + 25))
    else
        quality_notes+=("Missing arena info")
    fi
    
    # File size check
    local file_size=$(stat -f%z "$temp_file" 2>/dev/null || stat -c%s "$temp_file" 2>/dev/null || echo "0")
    if [[ $file_size -gt 5000 ]]; then
        quality_score=$((quality_score + 25))
    else
        quality_notes+=("Small file size: ${file_size}B")
    fi
    
    # Display results
    local quality_color=$GREEN
    [[ $quality_score -lt 75 ]] && quality_color=$YELLOW
    [[ $quality_score -lt 50 ]] && quality_color=$RED
    
    echo -e "    ${GREEN}✅ Valid JSON${NC} - Game: $game_code"
    echo -e "    📊 Players: ${PURPLE}$total_players${NC} total (${GREEN}$active_players${NC} active, ${YELLOW}$dnp_players${NC} DNP, ${RED}$inactive_players${NC} inactive)"
    echo -e "    🏟️  Arena: $arena | 🎫 Attendance: $attendance"
    echo -e "    💾 Size: ${file_size}B | 📈 Quality: ${quality_color}$quality_score/100${NC}"
    
    # Show samples if available
    if [[ "$sample_active" != "null" && -n "$sample_active" ]]; then
        echo -e "    🏀 Sample active: $sample_active"
    fi
    
    if [[ "$sample_dnp" != "null" && -n "$sample_dnp" ]]; then
        echo -e "    🚫 Sample DNP: $sample_dnp"
    fi
    
    # Show quality issues
    if [[ ${#quality_notes[@]} -gt 0 ]]; then
        echo -e "    ⚠️  Notes: ${quality_notes[*]}"
    fi
    
    rm -f "$temp_file"
    return 0
}

# Main validation command
cmd_validate() {
    local count=${1:-5}
    
    print_header
    echo -e "${BLUE}🔍 Validating $count recent JSON files:${NC}"
    echo ""
    
    # Get recent files
    local recent_files
    recent_files=$(get_recent_json_files $count)
    
    if [[ -z "$recent_files" ]]; then
        echo -e "${YELLOW}No recent JSON files found${NC}"
        echo -e "Checking if current downloads are in progress..."
        
        # Show recent date folders as debug info
        echo -e "\nRecent date folders:"
        gcloud storage ls "$BUCKET/$JSON_PATH/" 2>/dev/null | tail -5 | sed 's/^/  /'
        return 1
    fi
    
    local file_count=0
    local valid_count=0
    
    while IFS= read -r file_path; do
        if [[ -n "$file_path" ]]; then
            file_count=$((file_count + 1))
            
            echo -e "${BLUE}[$file_count/$count]${NC} $(basename "$(dirname "$file_path")"):"
            
            if validate_json_file "$file_path"; then
                valid_count=$((valid_count + 1))
            fi
            echo ""
        fi
    done <<< "$recent_files"
    
    # Summary
    echo -e "${CYAN}📋 Validation Summary:${NC}"
    echo -e "  Files validated: $file_count"
    echo -e "  Valid files: ${GREEN}$valid_count${NC}"
    [[ $file_count -gt 0 ]] && echo -e "  Success rate: $(( valid_count * 100 / file_count ))%"
}

# Quick count command
cmd_count() {
    print_header
    echo -e "${BLUE}📊 Recent Activity Count:${NC}"
    echo ""
    
    # Count files in recent date folders
    local recent_dates=("2023-01-07" "2023-01-06" "2023-01-05" "2022-12-31" "2022-12-30")
    
    for date in "${recent_dates[@]}"; do
        local date_folder="$BUCKET/$JSON_PATH/$date/"
        local game_count=$(gcloud storage ls "$date_folder" 2>/dev/null | wc -l || echo "0")
        local json_count=0
        
        if [[ $game_count -gt 0 ]]; then
            # Count JSON files in this date's game folders
            local game_folders=$(gcloud storage ls "$date_folder" 2>/dev/null)
            while IFS= read -r game_folder; do
                if [[ -n "$game_folder" ]]; then
                    local jsons_in_folder=$(gcloud storage ls "$game_folder" 2>/dev/null | grep "\.json$" | wc -l || echo "0")
                    json_count=$((json_count + jsons_in_folder))
                fi
            done <<< "$game_folders"
        fi
        
        echo -e "  ${date}: ${GREEN}$game_count${NC} games, ${GREEN}$json_count${NC} JSON files"
    done
}

show_usage() {
    echo "Usage: $0 [command] [count]"
    echo ""
    echo "Commands:"
    echo "  validate [N]       - Validate N recent JSON files (default: 5)"
    echo "  count              - Show file counts for recent dates"
    echo ""
    echo "Examples:"
    echo "  $0 validate 3      - Validate 3 recent files"
    echo "  $0 count           - Show recent activity"
}

# Main command handling
case "${1:-validate}" in
    "validate")
        cmd_validate "${2:-5}"
        ;;
    "count")
        cmd_count
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