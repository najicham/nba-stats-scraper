#!/bin/bash
# FILE: bin/scrapers/validation/validate_nbac_referee_assignments.sh
# Purpose: Validate NBA referee assignments data quality and completeness
# Usage: ./bin/scrapers/validation/validate_nbac_referee_assignments.sh [command] [options]

set -e

# Configuration
GCS_BUCKET="nba-scraped-data"
GCS_PATH="nba-com/referee-assignments"
TEMP_DIR="/tmp/referee_validation"
MAX_DOWNLOAD_FILES=50  # Limit for performance

# Validation settings
MIN_OFFICIALS_PER_GAME=3  # NBA games have 3 officials
MAX_OFFICIALS_PER_GAME=4  # Usually 3, sometimes 4
MIN_NBA_GAMES_PER_DATE=0  # Can be 0 (off-season)
MAX_NBA_GAMES_PER_DATE=16 # Most games in one day

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

# Validation results
TOTAL_FILES=0
VALID_FILES=0
INVALID_FILES=0
WARNINGS=0
declare -a VALIDATION_ISSUES=()
declare -a CRITICAL_ISSUES=()

print_header() {
    echo -e "${CYAN}================================================${NC}"
    echo -e "${CYAN}🏀 NBA REFEREE ASSIGNMENTS VALIDATOR${NC}"
    echo -e "${CYAN}================================================${NC}"
    echo -e "Time: $(date)"
    echo ""
}

# Ensure temp directory exists
mkdir -p "$TEMP_DIR"

# Download a specific file from GCS
download_file() {
    local gcs_path="$1"
    local local_file="$2"
    
    if gsutil cp "$gcs_path" "$local_file" 2>/dev/null; then
        return 0
    else
        return 1
    fi
}

# Validate JSON structure
validate_json_structure() {
    local file="$1"
    local issues=()
    
    # Check if valid JSON
    if ! jq empty "$file" 2>/dev/null; then
        issues+=("Invalid JSON format")
        return 1
    fi
    
    # Check required top-level keys
    local metadata=$(jq -r '.metadata // empty' "$file")
    local referee_assignments=$(jq -r '.refereeAssignments // empty' "$file")
    
    if [[ -z "$metadata" ]]; then
        issues+=("Missing 'metadata' key")
    fi
    
    if [[ -z "$referee_assignments" ]]; then
        issues+=("Missing 'refereeAssignments' key")
    fi
    
    # Check metadata structure
    if [[ -n "$metadata" ]]; then
        local date=$(jq -r '.metadata.date // empty' "$file")
        local season=$(jq -r '.metadata.season // empty' "$file")
        local fetched_utc=$(jq -r '.metadata.fetchedUtc // empty' "$file")
        
        if [[ -z "$date" ]]; then
            issues+=("Missing metadata.date")
        elif [[ ! "$date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
            issues+=("Invalid date format: $date")
        fi
        
        if [[ -z "$season" ]]; then
            issues+=("Missing metadata.season")
        elif [[ ! "$season" =~ ^[0-9]{4}-[0-9]{2}$ ]]; then
            issues+=("Invalid season format: $season")
        fi
        
        if [[ -z "$fetched_utc" ]]; then
            issues+=("Missing metadata.fetchedUtc")
        fi
    fi
    
    # Check NBA referee assignments structure
    if [[ -n "$referee_assignments" ]]; then
        local nba_data=$(jq -r '.refereeAssignments.nba // empty' "$file")
        
        if [[ -n "$nba_data" ]]; then
            local table=$(jq -r '.refereeAssignments.nba.Table // empty' "$file")
            
            if [[ -z "$table" ]]; then
                issues+=("Missing refereeAssignments.nba.Table")
            else
                # Check if rows exist and is array
                local rows=$(jq -r '.refereeAssignments.nba.Table.rows // empty' "$file")
                if [[ -z "$rows" ]]; then
                    issues+=("Missing refereeAssignments.nba.Table.rows")
                elif [[ $(jq -r 'type' <<< "$rows") != "array" ]]; then
                    issues+=("refereeAssignments.nba.Table.rows is not an array")
                fi
            fi
        fi
    fi
    
    # Print issues if any
    if [[ ${#issues[@]} -gt 0 ]]; then
        for issue in "${issues[@]}"; do
            echo -e "    ${RED}✗${NC} $issue"
            VALIDATION_ISSUES+=("JSON Structure: $issue")
        done
        return 1
    fi
    
    return 0
}

# Validate referee assignments data
validate_referee_data() {
    local file="$1"
    local date_str="$2"
    local issues=()
    local warnings=()
    
    # Get NBA games data
    local nba_games=$(jq -r '.refereeAssignments.nba.Table.rows // []' "$file")
    local game_count=$(jq -r '. | length' <<< "$nba_games")
    
    # Check game count bounds
    if [[ $game_count -gt $MAX_NBA_GAMES_PER_DATE ]]; then
        issues+=("Suspicious game count: $game_count (max expected: $MAX_NBA_GAMES_PER_DATE)")
    fi
    
    # Validate each game if we have games
    if [[ $game_count -gt 0 ]]; then
        local game_index=0
        while [[ $game_index -lt $game_count ]]; do
            local game=$(jq -r ".[$game_index]" <<< "$nba_games")
            
            # Check required game fields
            local game_id=$(jq -r '.game_id // empty' <<< "$game")
            local home_team=$(jq -r '.home_team // empty' <<< "$game")
            local away_team=$(jq -r '.away_team // empty' <<< "$game")
            local official1=$(jq -r '.official1 // empty' <<< "$game")
            
            if [[ -z "$game_id" ]]; then
                issues+=("Game $game_index: Missing game_id")
            fi
            
            if [[ -z "$home_team" ]]; then
                issues+=("Game $game_index: Missing home_team")
            fi
            
            if [[ -z "$away_team" ]]; then
                issues+=("Game $game_index: Missing away_team")
            fi
            
            if [[ -z "$official1" ]]; then
                issues+=("Game $game_index: Missing primary official")
            fi
            
            # Count officials for this game
            local official_count=0
            for i in {1..4}; do
                local official=$(jq -r ".official$i // empty" <<< "$game")
                if [[ -n "$official" && "$official" != "null" ]]; then
                    official_count=$((official_count + 1))
                fi
            done
            
            if [[ $official_count -lt $MIN_OFFICIALS_PER_GAME ]]; then
                issues+=("Game $game_index: Only $official_count officials (expected at least $MIN_OFFICIALS_PER_GAME)")
            elif [[ $official_count -gt $MAX_OFFICIALS_PER_GAME ]]; then
                warnings+=("Game $game_index: $official_count officials (unusual, expected $MIN_OFFICIALS_PER_GAME-$MAX_OFFICIALS_PER_GAME)")
            fi
            
            # Validate team codes (3-letter NBA team codes)
            if [[ -n "$home_team" && ${#home_team} -ne 3 ]]; then
                issues+=("Game $game_index: Invalid home team code: $home_team")
            fi
            
            if [[ -n "$away_team" && ${#away_team} -ne 3 ]]; then
                issues+=("Game $game_index: Invalid away team code: $away_team")
            fi
            
            game_index=$((game_index + 1))
        done
    fi
    
    # Check metadata consistency
    local metadata_game_count=$(jq -r '.metadata.gameCount.nba // 0' "$file")
    if [[ $metadata_game_count -ne $game_count ]]; then
        issues+=("Game count mismatch: metadata says $metadata_game_count, found $game_count")
    fi
    
    # Date consistency check
    local metadata_date=$(jq -r '.metadata.date // empty' "$file")
    if [[ -n "$metadata_date" && "$metadata_date" != "$date_str" ]]; then
        issues+=("Date mismatch: expected $date_str, metadata has $metadata_date")
    fi
    
    # Print warnings
    if [[ ${#warnings[@]} -gt 0 ]]; then
        for warning in "${warnings[@]}"; do
            echo -e "    ${YELLOW}⚠${NC} $warning"
            WARNINGS=$((WARNINGS + 1))
        done
    fi
    
    # Print issues if any
    if [[ ${#issues[@]} -gt 0 ]]; then
        for issue in "${issues[@]}"; do
            echo -e "    ${RED}✗${NC} $issue"
            VALIDATION_ISSUES+=("Referee Data: $issue")
        done
        return 1
    fi
    
    return 0
}

# Validate a single file
validate_single_file() {
    local gcs_file="$1"
    local filename=$(basename "$gcs_file")
    local local_file="$TEMP_DIR/$filename"
    
    echo -e "${BLUE}Validating:${NC} $filename"
    
    # Download file
    if ! download_file "$gcs_file" "$local_file"; then
        echo -e "    ${RED}✗${NC} Failed to download"
        INVALID_FILES=$((INVALID_FILES + 1))
        CRITICAL_ISSUES+=("Download failed: $filename")
        return 1
    fi
    
    # Extract date from filename/path for validation
    local date_str=""
    if [[ "$gcs_file" =~ ([0-9]{4})/([0-9]{2})/([0-9]{2}) ]]; then
        date_str="${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]}"
    fi
    
    # Validate JSON structure
    local structure_valid=true
    if ! validate_json_structure "$local_file"; then
        structure_valid=false
    fi
    
    # Validate referee data (only if structure is valid)
    local data_valid=true
    if [[ "$structure_valid" == "true" ]]; then
        if ! validate_referee_data "$local_file" "$date_str"; then
            data_valid=false
        fi
    fi
    
    # Overall result
    if [[ "$structure_valid" == "true" && "$data_valid" == "true" ]]; then
        echo -e "    ${GREEN}✓${NC} Valid"
        VALID_FILES=$((VALID_FILES + 1))
    else
        echo -e "    ${RED}✗${NC} Invalid"
        INVALID_FILES=$((INVALID_FILES + 1))
    fi
    
    # Clean up
    rm -f "$local_file"
    
    TOTAL_FILES=$((TOTAL_FILES + 1))
}

# Get recent files for validation
get_recent_files() {
    local limit=${1:-10}
    
    echo -e "${BLUE}Finding recent files (limit: $limit)...${NC}"
    
    # Get recent files from GCS
    gsutil ls -r "gs://$GCS_BUCKET/$GCS_PATH/" 2>/dev/null | \
        grep "\.json$" | \
        head -n "$limit"
}

# Get files for a specific date
get_files_for_date() {
    local date="$1"
    
    echo -e "${BLUE}Finding files for $date...${NC}"
    
    # Get actual JSON files, not wildcard paths
    gsutil ls "gs://$GCS_BUCKET/$GCS_PATH/$date/*.json" 2>/dev/null || true
}

# Get random sample of files
get_sample_files() {
    local sample_size=${1:-20}
    
    echo -e "${BLUE}Getting random sample (size: $sample_size)...${NC}"
    
    # Get all date folders, shuffle them, and find JSON files
    local all_folders=$(gsutil ls "gs://$GCS_BUCKET/$GCS_PATH/" 2>/dev/null | grep "/" | shuf | head -n "$sample_size")
    
    local files=()
    for folder in $all_folders; do
        local json_files=$(gsutil ls "$folder*.json" 2>/dev/null | head -1)  # Just get one file per folder
        if [[ -n "$json_files" ]]; then
            files+=($json_files)
            if [[ ${#files[@]} -ge $sample_size ]]; then
                break
            fi
        fi
    done
    
    printf '%s\n' "${files[@]}"
}

# Print validation summary
print_validation_summary() {
    echo ""
    echo -e "${CYAN}================================================${NC}"
    echo -e "${CYAN}VALIDATION SUMMARY${NC}"
    echo -e "${CYAN}================================================${NC}"
    
    echo -e "Total files validated: ${BLUE}$TOTAL_FILES${NC}"
    echo -e "Valid files: ${GREEN}$VALID_FILES${NC}"
    echo -e "Invalid files: ${RED}$INVALID_FILES${NC}"
    echo -e "Warnings: ${YELLOW}$WARNINGS${NC}"
    
    if [[ $TOTAL_FILES -gt 0 ]]; then
        local success_rate=$((VALID_FILES * 100 / TOTAL_FILES))
        echo -e "Success rate: ${GREEN}$success_rate%${NC}"
    fi
    
    # Show critical issues
    if [[ ${#CRITICAL_ISSUES[@]} -gt 0 ]]; then
        echo ""
        echo -e "${RED}CRITICAL ISSUES:${NC}"
        for issue in "${CRITICAL_ISSUES[@]}"; do
            echo -e "  ${RED}•${NC} $issue"
        done
    fi
    
    # Show validation issues (first 10)
    if [[ ${#VALIDATION_ISSUES[@]} -gt 0 ]]; then
        echo ""
        echo -e "${YELLOW}VALIDATION ISSUES (first 10):${NC}"
        local count=0
        for issue in "${VALIDATION_ISSUES[@]}"; do
            echo -e "  ${YELLOW}•${NC} $issue"
            count=$((count + 1))
            if [[ $count -ge 10 ]]; then
                if [[ ${#VALIDATION_ISSUES[@]} -gt 10 ]]; then
                    echo -e "  ${YELLOW}•${NC} ... and $((${#VALIDATION_ISSUES[@]} - 10)) more issues"
                fi
                break
            fi
        done
    fi
    
    # Overall status
    echo ""
    if [[ $INVALID_FILES -eq 0 && ${#CRITICAL_ISSUES[@]} -eq 0 ]]; then
        echo -e "${GREEN}✅ VALIDATION PASSED${NC}"
    elif [[ $INVALID_FILES -lt $TOTAL_FILES && ${#CRITICAL_ISSUES[@]} -eq 0 ]]; then
        echo -e "${YELLOW}⚠️  VALIDATION PASSED WITH WARNINGS${NC}"
    else
        echo -e "${RED}❌ VALIDATION FAILED${NC}"
    fi
}

# Coverage analysis
cmd_coverage() {
    print_header
    echo -e "${BLUE}📊 COVERAGE ANALYSIS${NC}"
    echo ""
    
    # Count files by year
    for year in 2021 2022 2023 2024; do
        local year_count=$(gsutil ls -r "gs://$GCS_BUCKET/$GCS_PATH/$year/" 2>/dev/null | grep -c "\.json$" || echo "0")
        echo -e "Year $year: ${GREEN}$year_count${NC} files"
    done
    
    echo ""
    
    # Total count
    local total_count=$(gsutil ls -r "gs://$GCS_BUCKET/$GCS_PATH/" 2>/dev/null | grep -c "\.json$" || echo "0")
    echo -e "Total files: ${GREEN}$total_count${NC}"
    
    # Recent activity (last 7 days)
    local recent_count=$(gsutil ls -r "gs://$GCS_BUCKET/$GCS_PATH/" 2>/dev/null | grep "\.json$" | xargs -I {} gsutil stat {} 2>/dev/null | grep "Creation time" | awk '{print $3}' | sort | tail -n 100 | wc -l || echo "0")
    echo -e "Recent files (estimate): ${CYAN}$recent_count${NC}"
}

# Test command - validate recent files
cmd_test() {
    print_header
    echo -e "${BLUE}🔍 Testing with recent files${NC}"
    echo ""
    
    local files=$(get_recent_files $MAX_DOWNLOAD_FILES)
    
    if [[ -z "$files" ]]; then
        echo -e "${YELLOW}No files found to validate${NC}"
        return 0
    fi
    
    echo "Files to validate:"
    echo "$files" | while read -r file; do
        echo "  $(basename "$file")"
    done
    echo ""
    
    echo "$files" | while read -r file; do
        [[ -n "$file" ]] && validate_single_file "$file"
    done
    
    print_validation_summary
}

# Recent command - validate very recent files
cmd_recent() {
    print_header
    echo -e "${BLUE}🔍 Validating recent files${NC}"
    echo ""
    
    local files=$(get_recent_files 5)
    
    if [[ -z "$files" ]]; then
        echo -e "${YELLOW}No recent files found${NC}"
        return 0
    fi
    
    echo "$files" | while read -r file; do
        [[ -n "$file" ]] && validate_single_file "$file"
    done
    
    print_validation_summary
}

# Date command - validate specific date
cmd_date() {
    local date="$1"
    
    if [[ -z "$date" ]]; then
        echo -e "${RED}Error: Date required${NC}"
        echo "Usage: $0 date YYYY-MM-DD"
        exit 1
    fi
    
    # Validate date format
    if [[ ! "$date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
        echo -e "${RED}Error: Invalid date format. Use YYYY-MM-DD${NC}"
        exit 1
    fi
    
    print_header
    echo -e "${BLUE}🔍 Validating files for $date${NC}"
    echo ""
    
    local files=$(get_files_for_date "$date")
    
    if [[ -z "$files" ]]; then
        echo -e "${YELLOW}No files found for $date${NC}"
        return 0
    fi
    
    echo "$files" | while read -r file; do
        [[ -n "$file" ]] && validate_single_file "$file"
    done
    
    print_validation_summary
}

# Sample command - validate random sample
cmd_sample() {
    local sample_size=${1:-20}
    
    print_header
    echo -e "${BLUE}🔍 Validating random sample (size: $sample_size)${NC}"
    echo ""
    
    local files=$(get_sample_files "$sample_size")
    
    if [[ -z "$files" ]]; then
        echo -e "${YELLOW}No files found to sample${NC}"
        return 0
    fi
    
    echo "$files" | while read -r file; do
        [[ -n "$file" ]] && validate_single_file "$file"
    done
    
    print_validation_summary
}

# Usage help
show_usage() {
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  test           - Validate recent files (default, up to $MAX_DOWNLOAD_FILES files)"
    echo "  recent         - Validate very recent files (5 files)"
    echo "  date DATE      - Validate files for specific date (YYYY-MM-DD)"
    echo "  sample [N]     - Validate random sample (default: 20 files)"
    echo "  coverage       - Show coverage analysis by year"
    echo ""
    echo "Examples:"
    echo "  $0 test                     # Validate recent files"
    echo "  $0 recent                   # Validate last 5 files"
    echo "  $0 date 2023-12-25         # Validate Christmas day"
    echo "  $0 sample 50               # Validate 50 random files"
    echo "  $0 coverage                # Show coverage stats"
    echo ""
    echo "Validation checks:"
    echo "  • JSON structure and required fields"
    echo "  • Referee assignment data quality"
    echo "  • Game count validation"
    echo "  • Date consistency"
    echo "  • Official assignment completeness"
}

# Clean up on exit
cleanup() {
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

# Main command router
case "${1:-test}" in
    "test"|"")
        cmd_test
        ;;
    "recent")
        cmd_recent
        ;;
    "date")
        cmd_date "$2"
        ;;
    "sample")
        cmd_sample "$2"
        ;;
    "coverage")
        cmd_coverage
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