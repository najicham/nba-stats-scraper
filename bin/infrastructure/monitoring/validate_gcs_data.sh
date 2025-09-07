#!/bin/bash
# File: bin/monitoring/validate_gcs_data.sh
# Purpose: Validate NBA gamebook data quality from GCS storage
# Usage: ./validate_gcs_data.sh [command] [options]

set -e

PROJECT="nba-props-platform"
BUCKET="gs://nba-scraped-data"
JSON_PATH="nba-com/gamebooks-data"
PDF_PATH="nba-com/gamebooks-pdf"

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
    echo -e "${CYAN}🔍 NBA GAMEBOOK DATA VALIDATOR${NC}"
    echo -e "${CYAN}================================================${NC}"
    echo -e "Time: $(date)"
    echo -e "Bucket: $BUCKET"
    echo ""
}

# Get recent JSON files from GCS
get_recent_files() {
    local limit=${1:-10}
    local hours_back=${2:-1}
    
    echo -e "${BLUE}📁 Recent JSON Files (last $hours_back hour(s)):${NC}"
    
    # Get files modified in the last N hours
    local cutoff_time=$(date -u -d "$hours_back hours ago" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date -u -v-${hours_back}H '+%Y-%m-%dT%H:%M:%SZ')
    
    gcloud storage ls --recursive "$BUCKET/$JSON_PATH/" \
        --format="table(name,timeCreated,size)" \
        --limit=1000 2>/dev/null | \
        grep "\.json$" | \
        awk -v cutoff="$cutoff_time" '$2 > cutoff' | \
        head -$limit
}

# Download and validate a single JSON file
validate_single_file() {
    local file_path="$1"
    local temp_file="/tmp/nba_validation_$(basename "$file_path")"
    
    # Download file
    if ! gcloud storage cp "$file_path" "$temp_file" 2>/dev/null; then
        echo -e "  ${RED}❌ Failed to download${NC}"
        return 1
    fi
    
    # Validate JSON structure
    if ! jq empty "$temp_file" 2>/dev/null; then
        echo -e "  ${RED}❌ Invalid JSON${NC}"
        rm -f "$temp_file"
        return 1
    fi
    
    # Extract game code from filename
    local game_code=$(basename "$file_path" | sed 's/.*game_\([0-9]*_[A-Z]*\).*/\1/' | sed 's/_/\//')
    
    echo -e "  ${GREEN}✅ Valid JSON${NC} - Game: $game_code"
    
    # Analyze content with jq
    local file_size=$(stat -f%z "$temp_file" 2>/dev/null || stat -c%s "$temp_file" 2>/dev/null)
    local total_players=$(jq -r '.players | length' "$temp_file" 2>/dev/null || echo "0")
    local active_players=$(jq -r '[.players[] | select(.status == "ACTIVE")] | length' "$temp_file" 2>/dev/null || echo "0")
    local dnp_players=$(jq -r '[.players[] | select(.status == "DNP")] | length' "$temp_file" 2>/dev/null || echo "0")
    local inactive_players=$(jq -r '[.players[] | select(.status == "INACTIVE")] | length' "$temp_file" 2>/dev/null || echo "0")
    
    # Game metadata
    local arena=$(jq -r '.game_info.arena // "Unknown"' "$temp_file" 2>/dev/null)
    local attendance=$(jq -r '.game_info.attendance // "Unknown"' "$temp_file" 2>/dev/null)
    
    echo -e "    📊 Size: ${file_size} bytes"
    echo -e "    👥 Players: ${PURPLE}${total_players}${NC} total (${GREEN}${active_players}${NC} active, ${YELLOW}${dnp_players}${NC} DNP, ${RED}${inactive_players}${NC} inactive)"
    echo -e "    🏟️  Arena: $arena"
    echo -e "    🎫 Attendance: $attendance"
    
    # Sample active player
    local sample_active=$(jq -r '[.players[] | select(.status == "ACTIVE")] | .[0] | "\(.player_name): \(.pts // "N/A") pts, \(.min // "N/A") min"' "$temp_file" 2>/dev/null)
    if [[ "$sample_active" != "null" && -n "$sample_active" ]]; then
        echo -e "    🏀 Sample: $sample_active"
    fi
    
    # Sample DNP reason
    local sample_dnp=$(jq -r '[.players[] | select(.status == "DNP")] | .[0] | "\(.player_name): \(.dnp_reason // "No reason")"' "$temp_file" 2>/dev/null)
    if [[ "$sample_dnp" != "null" && -n "$sample_dnp" ]]; then
        echo -e "    🚫 DNP: $sample_dnp"
    fi
    
    # Data quality score
    local quality_score=0
    [[ $total_players -ge 35 && $total_players -le 50 ]] && quality_score=$((quality_score + 25))
    [[ $active_players -ge 15 && $active_players -le 25 ]] && quality_score=$((quality_score + 25))
    [[ "$arena" != "Unknown" && "$arena" != "null" ]] && quality_score=$((quality_score + 25))
    [[ $file_size -gt 5000 ]] && quality_score=$((quality_score + 25))
    
    local quality_color=$GREEN
    [[ $quality_score -lt 75 ]] && quality_color=$YELLOW
    [[ $quality_score -lt 50 ]] && quality_color=$RED
    
    echo -e "    📈 Quality: ${quality_color}${quality_score}/100${NC}"
    
    rm -f "$temp_file"
    return 0
}

# Validate multiple recent files
cmd_validate_recent() {
    local count=${1:-5}
    local hours=${2:-1}
    
    print_header
    echo -e "${BLUE}🔍 Validating $count most recent files (last $hours hour(s)):${NC}"
    echo ""
    
    # Get recent files
    local recent_files=$(gcloud storage ls --recursive "$BUCKET/$JSON_PATH/" 2>/dev/null | \
        grep "\.json$" | \
        sort -r | \
        head -$count)
    
    if [[ -z "$recent_files" ]]; then
        echo -e "${YELLOW}No JSON files found${NC}"
        return 1
    fi
    
    local file_count=0
    local valid_count=0
    
    while IFS= read -r file_path; do
        if [[ -n "$file_path" ]]; then
            file_count=$((file_count + 1))
            echo -e "${BLUE}[$file_count/$count]${NC} $(basename "$file_path"):"
            
            if validate_single_file "$file_path"; then
                valid_count=$((valid_count + 1))
            fi
            echo ""
        fi
    done <<< "$recent_files"
    
    # Summary
    echo -e "${CYAN}📋 Validation Summary:${NC}"
    echo -e "  Files checked: $file_count"
    echo -e "  Valid files: ${GREEN}$valid_count${NC}"
    echo -e "  Success rate: $(( valid_count * 100 / file_count ))%"
}

# Count files by date
cmd_file_counts() {
    print_header
    echo -e "${BLUE}📊 File Counts by Date:${NC}"
    echo ""
    
    # Get file counts for recent dates
    gcloud storage ls --recursive "$BUCKET/$JSON_PATH/" 2>/dev/null | \
        grep "\.json$" | \
        sed 's/.*gamebooks-data\/\([0-9-]*\)\/.*/\1/' | \
        sort | uniq -c | tail -10 | \
        while read count date; do
            echo -e "  ${date}: ${GREEN}${count}${NC} files"
        done
    
    echo ""
    echo -e "${BLUE}📈 Total Counts:${NC}"
    
    local total_json=$(gcloud storage ls --recursive "$BUCKET/$JSON_PATH/" 2>/dev/null | grep "\.json$" | wc -l)
    local total_pdf=$(gcloud storage ls --recursive "$BUCKET/$PDF_PATH/" 2>/dev/null | grep "\.pdf$" | wc -l)
    
    echo -e "  JSON files: ${GREEN}$total_json${NC}"
    echo -e "  PDF files: ${GREEN}$total_pdf${NC}"
    echo -e "  Target: ${CYAN}5,583${NC}"
    echo -e "  Progress: $(( total_json * 100 / 5583 ))%"
}

# Sample data analysis
cmd_sample_analysis() {
    local sample_size=${1:-10}
    
    print_header
    echo -e "${BLUE}🔬 Sample Data Analysis ($sample_size files):${NC}"
    echo ""
    
    # Get random sample of files
    local sample_files=$(gcloud storage ls --recursive "$BUCKET/$JSON_PATH/" 2>/dev/null | \
        grep "\.json$" | \
        shuf | \
        head -$sample_size)
    
    if [[ -z "$sample_files" ]]; then
        echo -e "${YELLOW}No files found for sampling${NC}"
        return 1
    fi
    
    local total_players=0
    local total_active=0
    local total_dnp=0
    local total_inactive=0
    local valid_files=0
    local arenas=()
    
    while IFS= read -r file_path; do
        if [[ -n "$file_path" ]]; then
            local temp_file="/tmp/sample_$(basename "$file_path")"
            
            if gcloud storage cp "$file_path" "$temp_file" 2>/dev/null && jq empty "$temp_file" 2>/dev/null; then
                valid_files=$((valid_files + 1))
                
                local players=$(jq -r '.players | length' "$temp_file" 2>/dev/null || echo "0")
                local active=$(jq -r '[.players[] | select(.status == "ACTIVE")] | length' "$temp_file" 2>/dev/null || echo "0")
                local dnp=$(jq -r '[.players[] | select(.status == "DNP")] | length' "$temp_file" 2>/dev/null || echo "0")
                local inactive=$(jq -r '[.players[] | select(.status == "INACTIVE")] | length' "$temp_file" 2>/dev/null || echo "0")
                local arena=$(jq -r '.game_info.arena // "Unknown"' "$temp_file" 2>/dev/null)
                
                total_players=$((total_players + players))
                total_active=$((total_active + active))
                total_dnp=$((total_dnp + dnp))
                total_inactive=$((total_inactive + inactive))
                
                [[ "$arena" != "Unknown" && "$arena" != "null" ]] && arenas+=("$arena")
            fi
            
            rm -f "$temp_file"
        fi
    done <<< "$sample_files"
    
    if [[ $valid_files -gt 0 ]]; then
        echo -e "${GREEN}📊 Sample Statistics:${NC}"
        echo -e "  Valid files: $valid_files"
        echo -e "  Avg players per game: $(( total_players / valid_files ))"
        echo -e "  Avg active per game: $(( total_active / valid_files ))"
        echo -e "  Avg DNP per game: $(( total_dnp / valid_files ))"
        echo -e "  Avg inactive per game: $(( total_inactive / valid_files ))"
        echo -e "  Unique arenas: ${#arenas[@]}"
    else
        echo -e "${RED}❌ No valid files found in sample${NC}"
    fi
}

# Show data structure of a recent file
cmd_inspect_structure() {
    print_header
    echo -e "${BLUE}🔍 Data Structure Inspection:${NC}"
    echo ""
    
    # Get most recent file
    local recent_file=$(gcloud storage ls --recursive "$BUCKET/$JSON_PATH/" 2>/dev/null | \
        grep "\.json$" | \
        sort -r | \
        head -1)
    
    if [[ -z "$recent_file" ]]; then
        echo -e "${YELLOW}No JSON files found${NC}"
        return 1
    fi
    
    local temp_file="/tmp/structure_inspection.json"
    
    echo -e "📄 File: $(basename "$recent_file")"
    
    if gcloud storage cp "$recent_file" "$temp_file" 2>/dev/null; then
        echo -e "${GREEN}🏗️  JSON Structure:${NC}"
        jq -r 'keys | .[]' "$temp_file" 2>/dev/null | sed 's/^/  /'
        
        echo ""
        echo -e "${GREEN}👥 Player Structure (first player):${NC}"
        jq -r '.players[0] | keys | .[]' "$temp_file" 2>/dev/null | sed 's/^/  /' || echo "  No players found"
        
        echo ""
        echo -e "${GREEN}🏟️  Game Info Structure:${NC}"
        jq -r '.game_info | keys | .[]' "$temp_file" 2>/dev/null | sed 's/^/  /' || echo "  No game_info found"
        
        rm -f "$temp_file"
    else
        echo -e "${RED}❌ Failed to download file${NC}"
    fi
}

show_usage() {
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  recent [N] [H]     - Validate N most recent files from last H hours (default: 5, 1)"
    echo "  counts             - Show file counts by date and totals"
    echo "  sample [N]         - Analyze random sample of N files (default: 10)"
    echo "  structure          - Inspect JSON structure of recent file"
    echo ""
    echo "Examples:"
    echo "  $0 recent 10 2     - Validate 10 files from last 2 hours"
    echo "  $0 sample 20       - Analyze 20 random files"
    echo "  $0 counts          - Show file counts and progress"
    echo "  $0 structure       - Inspect data structure"
}

# Main command handling
case "${1:-recent}" in
    "recent")
        cmd_validate_recent "${2:-5}" "${3:-1}"
        ;;
    "counts")
        cmd_file_counts
        ;;
    "sample")
        cmd_sample_analysis "${2:-10}"
        ;;
    "structure")
        cmd_inspect_structure
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