#!/bin/bash
# File: bin/monitoring/validate_gcs_enhanced.sh  
# Purpose: Enhanced validator for NBA gamebook files with better discovery and analysis

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
    echo -e "${CYAN}🔍 NBA GAMEBOOK DATA VALIDATOR (ENHANCED)${NC}"
    echo -e "${CYAN}================================================${NC}"
    echo -e "Time: $(date)"
    echo -e "Bucket: $BUCKET/$JSON_PATH"
    echo ""
}

# Smart file discovery based on actual structure (more robust)
get_recent_files_smart() {
    local count=${1:-10}
    local file_type=${2:-"json"}
    
    echo -e "${BLUE}🔍 Smart file discovery...${NC}"
    
    # First, check if we can list the main directory
    if ! gcloud storage ls "$BUCKET/$JSON_PATH/" >/dev/null 2>&1; then
        echo -e "${RED}Cannot access $BUCKET/$JSON_PATH/${NC}"
        return 1
    fi
    
    # Get recent date directories (last 30 days worth of patterns)
    local date_dirs=()
    for i in $(seq 0 30); do
        local date_pattern=$(date -d "$i days ago" +%Y-%m-%d 2>/dev/null || date -v-${i}d +%Y-%m-%d 2>/dev/null)
        if [[ -n "$date_pattern" ]]; then
            date_dirs+=("$date_pattern")
        fi
    done
    
    # Also add the specific patterns from the original working script
    date_dirs+=("2023-01-07" "2023-01-06" "2023-01-05" "2022-12-31" "2022-12-30" "2023-01-08")
    
    local files=()
    
    for date_dir in "${date_dirs[@]}"; do
        local date_path="$BUCKET/$JSON_PATH/$date_dir/"
        
        if gcloud storage ls "$date_path" >/dev/null 2>&1; then
            # Get JSON files from this date
            local date_files=$(gcloud storage ls --recursive "$date_path" 2>/dev/null | grep "\.$file_type$" | head -5)
            
            while IFS= read -r file; do
                [[ -n "$file" ]] && files+=("$file")
            done <<< "$date_files"
            
            # Stop if we have enough files
            [[ ${#files[@]} -ge $count ]] && break
        fi
    done
    
    # If still no files, try a broader recursive search with timeout
    if [[ ${#files[@]} -eq 0 ]]; then
        echo -e "${YELLOW}No files in date directories, trying recursive search...${NC}"
        local recursive_files=$(timeout 60 gcloud storage ls --recursive "$BUCKET/$JSON_PATH/" 2>/dev/null | grep "\.$file_type$" | head -$count || echo "")
        
        while IFS= read -r file; do
            [[ -n "$file" ]] && files+=("$file")
        done <<< "$recursive_files"
    fi
    
    printf '%s\n' "${files[@]}" | head -$count
}

# Quick discovery using known working patterns
get_recent_files_quick() {
    local count=${1:-5}
    
    # Use the exact patterns from the working original script
    local known_dates=("2023-01-07" "2023-01-06" "2023-01-05" "2022-12-31" "2022-12-30")
    
    # Also try very recent dates
    for i in $(seq 0 7); do
        local recent_date=$(date -d "$i days ago" +%Y-%m-%d 2>/dev/null || date -v-${i}d +%Y-%m-%d 2>/dev/null)
        [[ -n "$recent_date" ]] && known_dates=("$recent_date" "${known_dates[@]}")
    done
    
    local files=()
    
    for date_folder in "${known_dates[@]}"; do
        local date_path="$BUCKET/$JSON_PATH/$date_folder/"
        
        # Check if this date folder exists
        if gcloud storage ls "$date_path" >/dev/null 2>&1; then
            echo -e "  ${GREEN}Found data for $date_folder${NC}"
            
            # Get game folders in this date
            local game_folders=$(gcloud storage ls "$date_path" 2>/dev/null | head -3)
            
            while IFS= read -r game_folder; do
                if [[ -n "$game_folder" ]]; then
                    # Get JSON files in this game folder
                    local json_files=$(gcloud storage ls "$game_folder" 2>/dev/null | grep "\.json$" | head -2)
                    
                    while IFS= read -r json_file; do
                        [[ -n "$json_file" ]] && files+=("$json_file")
                    done <<< "$json_files"
                fi
            done <<< "$game_folders"
            
            # Stop if we have enough files
            [[ ${#files[@]} -ge $count ]] && break
        fi
    done
    
    # If no files found in known dates, fall back to smart discovery
    if [[ ${#files[@]} -eq 0 ]]; then
        echo -e "${YELLOW}No files in known dates, using smart discovery...${NC}"
        get_recent_files_smart $count
    else
        printf '%s\n' "${files[@]}" | head -$count
    fi
}

# Enhanced JSON validation with comprehensive analysis
validate_json_enhanced() {
    local file_path="$1"
    local temp_file="/tmp/nba_validate_$(date +%s)_$$.json"
    
    # Extract game info from path more reliably
    local file_basename=$(basename "$file_path")
    local parent_dir=$(basename "$(dirname "$file_path")")
    local grandparent_dir=$(basename "$(dirname "$(dirname "$file_path")")")
    
    # Try to extract date and game info
    local date_info=""
    local game_info=""
    
    if [[ "$grandparent_dir" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
        date_info="$grandparent_dir"
        game_info="$parent_dir"
    elif [[ "$parent_dir" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
        date_info="$parent_dir"
        game_info="$file_basename"
    else
        # Fallback: try to extract from full path
        local path_parts=$(echo "$file_path" | grep -o '[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}' | tail -1)
        date_info="$path_parts"
        game_info="$parent_dir"
    fi
    
    echo -e "  ${BLUE}File:${NC} $date_info/$game_info/$(basename "$file_path")"
    
    # Download with better error handling
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
    
    # Comprehensive data extraction using jq
    local analysis=$(jq -r '
        {
            total_players: (.players | length),
            active: ([.players[] | select(.status == "ACTIVE")] | length),
            dnp: ([.players[] | select(.status == "DNP")] | length),
            inactive: ([.players[] | select(.status == "INACTIVE")] | length),
            players_with_stats: ([.players[] | select(.pts != null or .min != null)] | length),
            arena: (.game_info.arena // "Unknown"),
            attendance: (.game_info.attendance // "Unknown"),
            date: (.game_info.date // "Unknown"),
            home_team: (.game_info.home_team // "Unknown"),
            away_team: (.game_info.away_team // "Unknown"),
            sample_active: ([.players[] | select(.status == "ACTIVE" and .pts != null)] | .[0] | "\(.player_name): \(.pts)pts \(.min)min"),
            sample_dnp: ([.players[] | select(.status == "DNP")] | .[0] | "\(.player_name): \(.dnp_reason // "No reason")")
        }
    ' "$temp_file" 2>/dev/null)
    
    if [[ -z "$analysis" ]]; then
        echo -e "    ${RED}❌ Failed to analyze JSON structure${NC}"
        rm -f "$temp_file"
        return 1
    fi
    
    # Extract values from analysis
    local total_players=$(echo "$analysis" | jq -r '.total_players')
    local active=$(echo "$analysis" | jq -r '.active')
    local dnp=$(echo "$analysis" | jq -r '.dnp')
    local inactive=$(echo "$analysis" | jq -r '.inactive')
    local players_with_stats=$(echo "$analysis" | jq -r '.players_with_stats')
    local arena=$(echo "$analysis" | jq -r '.arena')
    local attendance=$(echo "$analysis" | jq -r '.attendance')
    local home_team=$(echo "$analysis" | jq -r '.home_team')
    local away_team=$(echo "$analysis" | jq -r '.away_team')
    local sample_active=$(echo "$analysis" | jq -r '.sample_active')
    local sample_dnp=$(echo "$analysis" | jq -r '.sample_dnp')
    
    # File size and structure analysis
    local file_size=$(stat -f%z "$temp_file" 2>/dev/null || stat -c%s "$temp_file" 2>/dev/null || echo "0")
    local structure_check=$(jq -r 'keys[]' "$temp_file" 2>/dev/null | tr '\n' ',' | sed 's/,$//')
    
    # Enhanced quality scoring
    local quality_score=0
    local quality_notes=()
    
    # Player count validation (NBA games typically have 35-50 total players)
    if [[ $total_players -ge 35 && $total_players -le 50 ]]; then
        quality_score=$((quality_score + 20))
    else
        quality_notes+=("Player count: $total_players (expected 35-50)")
    fi
    
    # Active player validation (typically 15-25 active)
    if [[ $active -ge 15 && $active -le 25 ]]; then
        quality_score=$((quality_score + 20))
    else
        quality_notes+=("Active players: $active (expected 15-25)")
    fi
    
    # Stats availability check
    if [[ $players_with_stats -gt $((active / 2)) ]]; then
        quality_score=$((quality_score + 20))
    else
        quality_notes+=("Limited stats: $players_with_stats/$active players")
    fi
    
    # Game info completeness
    if [[ "$arena" != "Unknown" && "$arena" != "null" && -n "$arena" ]]; then
        quality_score=$((quality_score + 15))
    else
        quality_notes+=("Missing arena")
    fi
    
    if [[ "$home_team" != "Unknown" && "$away_team" != "Unknown" ]]; then
        quality_score=$((quality_score + 15))
    else
        quality_notes+=("Missing team info")
    fi
    
    # File size validation (should be substantial)
    if [[ $file_size -gt 10000 ]]; then
        quality_score=$((quality_score + 10))
    else
        quality_notes+=("Small file: ${file_size}B")
    fi
    
    # Display results with color coding
    local quality_color=$GREEN
    [[ $quality_score -lt 75 ]] && quality_color=$YELLOW
    [[ $quality_score -lt 50 ]] && quality_color=$RED
    
    echo -e "    ${GREEN}✅ Valid JSON${NC}"
    echo -e "    🏟️  ${home_team} vs ${away_team} at ${arena}"
    echo -e "    📊 Players: ${PURPLE}$total_players${NC} (${GREEN}$active${NC} active, ${YELLOW}$dnp${NC} DNP, ${RED}$inactive${NC} inactive)"
    echo -e "    📈 Stats: ${players_with_stats}/$active players have stats"
    echo -e "    💾 Size: ${file_size}B | 🏆 Quality: ${quality_color}$quality_score/100${NC}"
    echo -e "    🔍 Structure: $structure_check"
    
    # Show sample data
    if [[ "$sample_active" != "null" && -n "$sample_active" ]]; then
        echo -e "    🏀 Sample: $sample_active"
    fi
    
    if [[ "$sample_dnp" != "null" && -n "$sample_dnp" ]]; then
        echo -e "    🚫 DNP: $sample_dnp"
    fi
    
    # Show quality notes if any
    if [[ ${#quality_notes[@]} -gt 0 ]]; then
        echo -e "    ⚠️  Issues: ${quality_notes[*]}"
    fi
    
    rm -f "$temp_file"
    return 0
}

# Batch analysis for performance insights
cmd_batch_analysis() {
    local count=${1:-20}
    
    print_header
    echo -e "${BLUE}📊 Batch Analysis ($count files):${NC}"
    echo ""
    
    local files
    files=$(get_recent_files_smart $count)
    
    if [[ -z "$files" ]]; then
        echo -e "${YELLOW}No files found for analysis${NC}"
        return 1
    fi
    
    # Create temporary analysis file
    local batch_temp="/tmp/nba_batch_analysis_$(date +%s).json"
    local summary_temp="/tmp/nba_summary_$(date +%s).json"
    
    echo "[]" > "$batch_temp"
    
    local file_count=0
    local valid_count=0
    
    while IFS= read -r file_path; do
        if [[ -n "$file_path" ]]; then
            file_count=$((file_count + 1))
            echo -e "${CYAN}[$file_count/$count]${NC} Analyzing..."
            
            local temp_file="/tmp/nba_batch_$(date +%s)_${file_count}.json"
            
            if gcloud storage cp "$file_path" "$temp_file" >/dev/null 2>&1; then
                if jq empty "$temp_file" 2>/dev/null; then
                    valid_count=$((valid_count + 1))
                    
                    # Add to batch analysis
                    local file_analysis=$(jq --arg path "$file_path" '
                        {
                            path: $path,
                            total_players: (.players | length),
                            active: ([.players[] | select(.status == "ACTIVE")] | length),
                            dnp: ([.players[] | select(.status == "DNP")] | length),
                            arena: (.game_info.arena // "Unknown"),
                            home_team: (.game_info.home_team // "Unknown"),
                            away_team: (.game_info.away_team // "Unknown")
                        }
                    ' "$temp_file" 2>/dev/null)
                    
                    if [[ -n "$file_analysis" ]]; then
                        jq --argjson new "$file_analysis" '. += [$new]' "$batch_temp" > "${batch_temp}.tmp" && mv "${batch_temp}.tmp" "$batch_temp"
                    fi
                fi
                rm -f "$temp_file"
            fi
        fi
    done <<< "$files"
    
    # Generate summary statistics
    if [[ $valid_count -gt 0 ]]; then
        echo ""
        echo -e "${BLUE}📈 Summary Statistics:${NC}"
        
        local stats=$(jq -r '
            {
                total_files: length,
                avg_players: ([.[].total_players] | add / length | floor),
                avg_active: ([.[].active] | add / length | floor),
                avg_dnp: ([.[].dnp] | add / length | floor),
                teams: [.[].home_team, .[].away_team] | unique | length,
                arenas: [.[].arena] | unique | length
            }
        ' "$batch_temp" 2>/dev/null)
        
        echo "$stats" | jq -r '
            "  📁 Files analyzed: \(.total_files)",
            "  👥 Avg players per game: \(.avg_players)",
            "  🏃 Avg active per game: \(.avg_active)",
            "  🚫 Avg DNP per game: \(.avg_dnp)",
            "  🏀 Unique teams found: \(.teams)",
            "  🏟️  Unique arenas found: \(.arenas)"
        '
        
        # Show team distribution
        echo ""
        echo -e "${BLUE}🏀 Team Distribution:${NC}"
        jq -r '[.[].home_team, .[].away_team] | group_by(.) | map({team: .[0], games: length}) | sort_by(.games) | reverse | .[:10][] | "  \(.team): \(.games) games"' "$batch_temp" 2>/dev/null
    fi
    
    echo ""
    echo -e "${CYAN}📋 Batch Summary:${NC}"
    echo -e "  Files processed: $file_count"
    echo -e "  Valid JSON files: ${GREEN}$valid_count${NC}"
    [[ $file_count -gt 0 ]] && echo -e "  Success rate: $(( valid_count * 100 / file_count ))%"
    
    # Clean up
    rm -f "$batch_temp" "$summary_temp"
}

# Progress tracking with better performance
cmd_progress_tracking() {
    print_header
    echo -e "${BLUE}📊 Backfill Progress Tracking:${NC}"
    echo ""
    
    # Expected total files (from your mention of 5,583 games)
    local expected_total=5583
    
    # Instead of counting all files (which is slow), estimate based on date directories
    echo -e "Analyzing progress (using smart sampling approach)..."
    
    # Count date directories first (fast)
    local date_dir_count=$(gcloud storage ls "$BUCKET/$JSON_PATH/" 2>/dev/null | wc -l)
    echo -e "  📅 Date directories found: $date_dir_count"
    
    # Sample a few recent directories to estimate files per directory
    local sample_dirs=$(gcloud storage ls "$BUCKET/$JSON_PATH/" 2>/dev/null | tail -5)
    local total_sample_json=0
    local total_sample_pdf=0
    local sample_count=0
    
    echo -e "  📊 Sampling recent directories for estimation..."
    
    while IFS= read -r dir; do
        if [[ -n "$dir" ]]; then
            local dir_name=$(basename "$dir")
            local json_count=$(timeout 30 gcloud storage ls --recursive "$dir" 2>/dev/null | grep "\.json$" | wc -l || echo "0")
            local pdf_count=$(timeout 30 gcloud storage ls --recursive "$dir" 2>/dev/null | grep "\.pdf$" | wc -l || echo "0")
            
            total_sample_json=$((total_sample_json + json_count))
            total_sample_pdf=$((total_sample_pdf + pdf_count))
            sample_count=$((sample_count + 1))
            
            echo -e "    $dir_name: ${GREEN}$json_count${NC} JSON, ${GREEN}$pdf_count${NC} PDF"
        fi
    done <<< "$sample_dirs"
    
    if [[ $sample_count -gt 0 ]]; then
        local avg_json_per_dir=$((total_sample_json / sample_count))
        local avg_pdf_per_dir=$((total_sample_pdf / sample_count))
        
        local estimated_total_json=$((date_dir_count * avg_json_per_dir))
        local estimated_total_pdf=$((date_dir_count * avg_pdf_per_dir))
        
        local json_progress=$(( estimated_total_json * 100 / expected_total ))
        local pdf_progress=$(( estimated_total_pdf * 100 / expected_total ))
        
        echo ""
        echo -e "  📄 Estimated JSON files: ${GREEN}~$estimated_total_json${NC} / $expected_total (${GREEN}~$json_progress%${NC})"
        echo -e "  📋 Estimated PDF files: ${GREEN}~$estimated_total_pdf${NC} / $expected_total (${GREEN}~$pdf_progress%${NC})"
        echo -e "  📏 Based on $sample_count sample directories, $avg_json_per_dir avg JSON/dir"
    else
        echo -e "  ${YELLOW}Could not sample directories for estimation${NC}"
    fi
    
    # If user wants exact count, offer it as an option
    echo ""
    echo -e "${YELLOW}For exact counts (may take 2-3 minutes):${NC}"
    echo -e "  Use: $0 progress exact"
}

# Main validation command with options
cmd_validate() {
    local count=${1:-5}
    local mode=${2:-"quick"}
    
    print_header
    echo -e "${BLUE}🔍 Validating $count recent files (mode: $mode):${NC}"
    echo ""
    
    local files
    if [[ "$mode" == "smart" ]]; then
        files=$(get_recent_files_smart $count)
    else
        files=$(get_recent_files_quick $count)
    fi
    
    if [[ -z "$files" ]]; then
        echo -e "${YELLOW}No files found for validation${NC}"
        return 1
    fi
    
    local file_count=0
    local valid_count=0
    
    while IFS= read -r file_path; do
        if [[ -n "$file_path" ]]; then
            file_count=$((file_count + 1))
            
            echo -e "${CYAN}[$file_count/$count]${NC}"
            
            if validate_json_enhanced "$file_path"; then
                valid_count=$((valid_count + 1))
            fi
            echo ""
        fi
    done <<< "$files"
    
    # Summary
    echo -e "${CYAN}📋 Validation Summary:${NC}"
    echo -e "  Files processed: $file_count"
    echo -e "  Valid files: ${GREEN}$valid_count${NC}"
    [[ $file_count -gt 0 ]] && echo -e "  Success rate: $(( valid_count * 100 / file_count ))%"
}

show_usage() {
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  validate [N] [mode]    - Validate N recent files (quick|smart mode)"
    echo "  batch [N]              - Batch analysis with statistics"
    echo "  progress [exact]       - Track backfill progress (fast estimate or exact count)"
    echo ""
    echo "Examples:"
    echo "  $0 validate 5 quick    - Quick validation of 5 recent files"
    echo "  $0 validate 10 smart   - Smart discovery and validation"
    echo "  $0 batch 20            - Batch analysis of 20 files"
    echo "  $0 progress            - Fast progress estimate"
    echo "  $0 progress exact      - Exact file count (slow)"
}

# Main command handling
case "${1:-validate}" in
    "validate")
        cmd_validate "${2:-5}" "${3:-quick}"
        ;;
    "batch")
        cmd_batch_analysis "${2:-20}"
        ;;
    "progress")
        if [[ "${2}" == "exact" ]]; then
            # Original slow but accurate method
            print_header
            echo -e "${BLUE}📊 Exact Progress Tracking (slow):${NC}"
            echo ""
            echo -e "Counting all files (this will take 2-3 minutes)..."
            
            local total_json=$(gcloud storage ls --recursive "$BUCKET/$JSON_PATH/" 2>/dev/null | grep "\.json$" | wc -l | tr -d ' ')
            local total_pdf=$(gcloud storage ls --recursive "$BUCKET/$JSON_PATH/" 2>/dev/null | grep "\.pdf$" | wc -l | tr -d ' ')
            local expected_total=5583
            
            local json_progress=$(( total_json * 100 / expected_total ))
            local pdf_progress=$(( total_pdf * 100 / expected_total ))
            
            echo -e "  📄 JSON files: ${GREEN}$total_json${NC} / $expected_total (${GREEN}$json_progress%${NC})"
            echo -e "  📋 PDF files: ${GREEN}$total_pdf${NC} / $expected_total (${GREEN}$pdf_progress%${NC})"
        else
            cmd_progress_tracking
        fi
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