#!/bin/bash
# File: bin/monitoring/validate_gcs_data_fixed.sh
# Purpose: Corrected validator - looks for files by game date, not creation date

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
    echo -e "${CYAN}🔍 NBA GAMEBOOK DATA VALIDATOR (FIXED)${NC}"
    echo -e "${CYAN}================================================${NC}"
    echo -e "Time: $(date)"
    echo ""
}

# Get recent files from the most recent date folders (by game date)
get_recent_files_by_game_date() {
    local count=${1:-5}
    
    # Get the most recent date folders (these will be 2022-12-xx, not 2025-08-xx)
    local recent_folders=$(gcloud storage ls "$BUCKET/$JSON_PATH/" 2>/dev/null | tail -3)
    
    local recent_files=()
    
    # Process folders silently (no progress messages mixed with output)
    while IFS= read -r folder; do
        if [[ -n "$folder" ]]; then
            # Get files from this folder
            local folder_files=$(gcloud storage ls "$folder" 2>/dev/null | grep "\.json$" | head -5)
            
            if [[ -n "$folder_files" ]]; then
                while IFS= read -r file; do
                    [[ -n "$file" ]] && recent_files+=("$file")
                done <<< "$folder_files"
            fi
        fi
        
        # Stop if we have enough files
        [[ ${#recent_files[@]} -ge $count ]] && break
    done <<< "$recent_folders"
    
    # Output only the file paths (no progress messages)
    printf '%s\n' "${recent_files[@]}" | tail -$count
}

# Validate a single file
validate_file() {
    local file_path="$1"
    local temp_file="/tmp/validate_$(basename "$file_path" | tr '/' '_')"
    
    # Download file quietly
    if ! gcloud storage cp "$file_path" "$temp_file" >/dev/null 2>&1; then
        echo -e "    ${RED}❌ Download failed${NC}"
        return 1
    fi
    
    # Validate JSON
    if ! jq empty "$temp_file" 2>/dev/null; then
        echo -e "    ${RED}❌ Invalid JSON${NC}"
        rm -f "$temp_file"
        return 1
    fi
    
    # Analyze content
    local total_players=$(jq -r '.players | length' "$temp_file" 2>/dev/null || echo "0")
    local active=$(jq -r '[.players[] | select(.status == "ACTIVE")] | length' "$temp_file" 2>/dev/null || echo "0")
    local dnp=$(jq -r '[.players[] | select(.status == "DNP")] | length' "$temp_file" 2>/dev/null || echo "0")
    local arena=$(jq -r '.game_info.arena // "Unknown"' "$temp_file" 2>/dev/null)
    
    # Sample data
    local sample_player=$(jq -r '[.players[] | select(.status == "ACTIVE")] | .[0] | "\(.player_name): \(.pts // "N/A") pts"' "$temp_file" 2>/dev/null)
    local sample_dnp=$(jq -r '[.players[] | select(.status == "DNP")] | .[0] | "\(.player_name): \(.dnp_reason // "No reason")"' "$temp_file" 2>/dev/null)
    
    # Quality check
    local quality="Good"
    [[ $total_players -lt 35 || $total_players -gt 50 ]] && quality="Poor"
    [[ $active -lt 15 || $active -gt 25 ]] && quality="Poor"
    [[ "$arena" == "Unknown" || "$arena" == "null" ]] && quality="Fair"
    
    local quality_color=$GREEN
    [[ "$quality" == "Fair" ]] && quality_color=$YELLOW
    [[ "$quality" == "Poor" ]] && quality_color=$RED
    
    echo -e "    ${GREEN}✅ Valid JSON${NC}"
    echo -e "    📊 Players: $total_players (${active} active, ${dnp} DNP) - Quality: ${quality_color}${quality}${NC}"
    echo -e "    🏟️  Arena: $arena"
    echo -e "    🏀 Sample: $sample_player"
    [[ "$sample_dnp" != "null" && -n "$sample_dnp" ]] && echo -e "    🚫 DNP: $sample_dnp"
    
    rm -f "$temp_file"
    return 0
}

# Main validation command
cmd_validate() {
    local count=${1:-5}
    
    print_header
    echo -e "${BLUE}🔍 Validating $count recent files (by game date):${NC}"
    echo ""
    
    # Show which folders we're checking
    echo -e "${BLUE}Recent game date folders:${NC}"
    gcloud storage ls "$BUCKET/$JSON_PATH/" 2>/dev/null | tail -3 | sed 's/^/  /'
    echo ""
    
    # Get recent files
    local recent_files
    recent_files=$(get_recent_files_by_game_date $count)
    
    if [[ -z "$recent_files" ]]; then
        echo -e "${YELLOW}No recent JSON files found${NC}"
        return 1
    fi
    
    local file_count=0
    local valid_count=0
    
    while IFS= read -r file_path; do
        if [[ -n "$file_path" ]]; then
            file_count=$((file_count + 1))
            local game_code=$(basename "$file_path" | sed 's/.*game_\([0-9]*_[A-Z]*\).*/\1/' | sed 's/_/\//')
            
            echo -e "${BLUE}[$file_count/$count]${NC} $game_code:"
            
            if validate_file "$file_path"; then
                valid_count=$((valid_count + 1))
            fi
            echo ""
        fi
    done <<< "$recent_files"
    
    echo -e "${CYAN}📋 Summary: ${GREEN}$valid_count${NC}/$file_count files valid ($(( valid_count * 100 / file_count ))%)${NC}"
}

# Quick count of recent folders
cmd_count() {
    print_header
    echo -e "${BLUE}📊 Recent File Counts (by game date):${NC}"
    echo ""
    
    # Show last 5 date folders with file counts
    gcloud storage ls "$BUCKET/$JSON_PATH/" 2>/dev/null | tail -5 | while read folder; do
        if [[ -n "$folder" ]]; then
            local date=$(basename "$folder")
            local count=$(gcloud storage ls "$folder" 2>/dev/null | grep "\.json$" | wc -l)
            echo -e "  ${date}: ${GREEN}${count}${NC} files"
        fi
    done
}

show_usage() {
    echo "Usage: $0 [command] [count]"
    echo ""
    echo "Commands:"
    echo "  validate [N]       - Validate N recent files by game date (default: 5)"
    echo "  count              - Show file counts for recent game dates"
    echo ""
    echo "Examples:"
    echo "  $0 validate 3      - Validate 3 recent files"
    echo "  $0 count           - Show recent date folder counts"
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