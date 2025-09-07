#!/bin/bash
# File: bin/monitoring/diagnose_gcs_structure.sh
# Purpose: Diagnose actual GCS structure for NBA gamebook data

set -e

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
    echo -e "${CYAN}🔍 GCS STRUCTURE DIAGNOSTIC${NC}"
    echo -e "${CYAN}================================================${NC}"
    echo -e "Time: $(date)"
    echo -e "Analyzing: $BUCKET/$JSON_PATH"
    echo ""
}

# Check if bucket and path exist
check_basic_access() {
    echo -e "${BLUE}🔐 Basic Access Check:${NC}"
    
    if gcloud storage ls "$BUCKET/" >/dev/null 2>&1; then
        echo -e "  ✅ Bucket accessible: $BUCKET"
    else
        echo -e "  ❌ Cannot access bucket: $BUCKET"
        return 1
    fi
    
    if gcloud storage ls "$BUCKET/$JSON_PATH/" >/dev/null 2>&1; then
        echo -e "  ✅ Path accessible: $JSON_PATH"
    else
        echo -e "  ❌ Cannot access path: $JSON_PATH"
        echo -e "  ${YELLOW}Checking if path exists...${NC}"
        
        # Check what's actually in the bucket
        echo -e "  Available paths in bucket:"
        gcloud storage ls "$BUCKET/" 2>/dev/null | head -10 | sed 's/^/    /'
        return 1
    fi
    
    echo ""
}

# Explore the directory structure
explore_structure() {
    echo -e "${BLUE}📁 Directory Structure:${NC}"
    
    # Get top-level directories in the gamebooks path
    echo -e "  Top-level directories:"
    local top_dirs=$(gcloud storage ls "$BUCKET/$JSON_PATH/" 2>/dev/null | head -20)
    
    if [[ -z "$top_dirs" ]]; then
        echo -e "    ${YELLOW}No directories found${NC}"
        return 1
    fi
    
    echo "$top_dirs" | sed 's/^/    /' | head -10
    
    if [[ $(echo "$top_dirs" | wc -l) -gt 10 ]]; then
        echo -e "    ${YELLOW}... and $(( $(echo "$top_dirs" | wc -l) - 10 )) more${NC}"
    fi
    
    echo ""
    
    # Pick the first directory and explore deeper
    local first_dir=$(echo "$top_dirs" | head -1)
    if [[ -n "$first_dir" ]]; then
        echo -e "  Exploring first directory: $(basename "$first_dir")"
        local sub_dirs=$(gcloud storage ls "$first_dir" 2>/dev/null | head -10)
        
        if [[ -n "$sub_dirs" ]]; then
            echo "$sub_dirs" | sed 's/^/    /'
            
            # Try to find JSON files in the first subdirectory
            local first_sub=$(echo "$sub_dirs" | head -1)
            if [[ -n "$first_sub" ]]; then
                echo ""
                echo -e "  Files in $(basename "$first_sub"):"
                gcloud storage ls "$first_sub" 2>/dev/null | head -5 | sed 's/^/    /'
            fi
        else
            echo -e "    ${YELLOW}No subdirectories found${NC}"
        fi
    fi
    
    echo ""
}

# Look for JSON files specifically
find_json_files() {
    echo -e "${BLUE}📄 JSON File Discovery:${NC}"
    
    echo -e "  Searching for JSON files (this may take 30-60 seconds)..."
    
    # Search for JSON files with a reasonable timeout
    local json_files=$(timeout 60 gcloud storage ls --recursive "$BUCKET/$JSON_PATH/" 2>/dev/null | grep "\.json$" | head -10 || echo "")
    
    if [[ -n "$json_files" ]]; then
        echo -e "  ${GREEN}Found JSON files:${NC}"
        echo "$json_files" | sed 's/^/    /'
        
        local json_count=$(echo "$json_files" | wc -l)
        echo -e "  ${GREEN}Showing first 10 of potentially many more${NC}"
        
        # Try to download and test one file
        local test_file=$(echo "$json_files" | head -1)
        if [[ -n "$test_file" ]]; then
            echo ""
            echo -e "  Testing download of: $(basename "$test_file")"
            
            local temp_file="/tmp/gcs_test_$(date +%s).json"
            if gcloud storage cp "$test_file" "$temp_file" >/dev/null 2>&1; then
                echo -e "    ✅ Download successful"
                
                if jq empty "$temp_file" 2>/dev/null; then
                    echo -e "    ✅ Valid JSON"
                    
                    # Quick structure check
                    local has_players=$(jq -r 'has("players")' "$temp_file" 2>/dev/null)
                    local has_game_info=$(jq -r 'has("game_info")' "$temp_file" 2>/dev/null)
                    local player_count=$(jq -r '.players | length' "$temp_file" 2>/dev/null)
                    
                    echo -e "    📊 Structure: players=$has_players, game_info=$has_game_info"
                    echo -e "    👥 Player count: $player_count"
                else
                    echo -e "    ❌ Invalid JSON"
                fi
                
                rm -f "$temp_file"
            else
                echo -e "    ❌ Download failed"
            fi
        fi
    else
        echo -e "  ${YELLOW}No JSON files found (within 60 second timeout)${NC}"
    fi
    
    echo ""
}

# Check for recent activity
check_recent_activity() {
    echo -e "${BLUE}⏰ Recent Activity Check:${NC}"
    
    # Look for very recent date patterns
    local recent_patterns=(
        $(date +%Y-%m-%d)                          # Today
        $(date -d "1 day ago" +%Y-%m-%d 2>/dev/null || date -v-1d +%Y-%m-%d 2>/dev/null)  # Yesterday
        $(date -d "2 days ago" +%Y-%m-%d 2>/dev/null || date -v-2d +%Y-%m-%d 2>/dev/null)  # 2 days ago
    )
    
    for pattern in "${recent_patterns[@]}"; do
        if [[ -n "$pattern" ]]; then
            echo -e "  Checking for $pattern..."
            
            local pattern_path="$BUCKET/$JSON_PATH/$pattern/"
            if gcloud storage ls "$pattern_path" >/dev/null 2>&1; then
                local count=$(gcloud storage ls "$pattern_path" 2>/dev/null | wc -l)
                echo -e "    ${GREEN}✅ Found $count items for $pattern${NC}"
                
                # Show a few items
                gcloud storage ls "$pattern_path" 2>/dev/null | head -3 | sed 's/^/      /'
            else
                echo -e "    ${YELLOW}No data for $pattern${NC}"
            fi
        fi
    done
    
    echo ""
    
    # Check for the date patterns mentioned in the original script
    echo -e "  Checking historical patterns from original script:"
    local historical_patterns=("2023-01-07" "2023-01-06" "2023-01-05" "2022-12-31" "2022-12-30")
    
    for pattern in "${historical_patterns[@]}"; do
        local pattern_path="$BUCKET/$JSON_PATH/$pattern/"
        if gcloud storage ls "$pattern_path" >/dev/null 2>&1; then
            local count=$(gcloud storage ls "$pattern_path" 2>/dev/null | wc -l)
            echo -e "    ${GREEN}✅ Found $count items for $pattern${NC}"
        else
            echo -e "    ${YELLOW}No data for $pattern${NC}"
        fi
    done
}

# Get file count estimate
estimate_file_counts() {
    echo -e "${BLUE}📊 File Count Estimates:${NC}"
    
    # Quick count of directories (should be faster than counting all files)
    echo -e "  Counting date directories..."
    local dir_count=$(gcloud storage ls "$BUCKET/$JSON_PATH/" 2>/dev/null | wc -l)
    echo -e "    Date directories: $dir_count"
    
    # Sample a few directories to estimate files per directory
    local sample_dirs=$(gcloud storage ls "$BUCKET/$JSON_PATH/" 2>/dev/null | head -3)
    local total_sample_files=0
    local sample_count=0
    
    while IFS= read -r dir; do
        if [[ -n "$dir" ]]; then
            local files_in_dir=$(gcloud storage ls --recursive "$dir" 2>/dev/null | grep "\.json$" | wc -l)
            total_sample_files=$((total_sample_files + files_in_dir))
            sample_count=$((sample_count + 1))
            echo -e "    $(basename "$dir"): $files_in_dir JSON files"
        fi
    done <<< "$sample_dirs"
    
    if [[ $sample_count -gt 0 ]]; then
        local avg_files_per_dir=$((total_sample_files / sample_count))
        local estimated_total=$((dir_count * avg_files_per_dir))
        echo -e "    ${CYAN}Estimated total JSON files: ~$estimated_total${NC}"
        echo -e "    ${CYAN}(Based on $sample_count sample directories)${NC}"
    fi
    
    echo ""
}

# Main diagnostic function
run_full_diagnostic() {
    print_header
    
    check_basic_access || return 1
    explore_structure
    find_json_files
    check_recent_activity
    estimate_file_counts
    
    echo -e "${GREEN}🎯 Diagnostic Complete!${NC}"
    echo ""
    echo -e "${CYAN}Next Steps:${NC}"
    echo -e "  1. If JSON files were found, the structure is working"
    echo -e "  2. Note the date pattern format for file discovery"
    echo -e "  3. Use the successful file path format to fix the validator"
    echo ""
}

# Quick check function
quick_check() {
    echo -e "${BLUE}🚀 Quick GCS Check:${NC}"
    echo ""
    
    # Basic access
    if gcloud storage ls "$BUCKET/$JSON_PATH/" >/dev/null 2>&1; then
        echo -e "✅ Path accessible"
    else
        echo -e "❌ Path not accessible"
        return 1
    fi
    
    # Quick file search
    local sample_file=$(timeout 30 gcloud storage ls --recursive "$BUCKET/$JSON_PATH/" 2>/dev/null | grep "\.json$" | head -1)
    
    if [[ -n "$sample_file" ]]; then
        echo -e "✅ JSON files found"
        echo -e "Sample: $(basename "$(dirname "$sample_file")")/$(basename "$sample_file")"
        
        # Quick download test
        local temp_file="/tmp/quick_test_$(date +%s).json"
        if gcloud storage cp "$sample_file" "$temp_file" >/dev/null 2>&1; then
            echo -e "✅ Download works"
            
            if jq empty "$temp_file" 2>/dev/null; then
                echo -e "✅ Valid JSON"
                local player_count=$(jq -r '.players | length' "$temp_file" 2>/dev/null)
                echo -e "📊 Players: $player_count"
            else
                echo -e "❌ Invalid JSON"
            fi
            rm -f "$temp_file"
        else
            echo -e "❌ Download failed"
        fi
    else
        echo -e "❌ No JSON files found (30s timeout)"
    fi
}

show_usage() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  full          - Complete diagnostic (default)"
    echo "  quick         - Quick connectivity check"
    echo ""
    echo "Examples:"
    echo "  $0            - Run full diagnostic"
    echo "  $0 quick      - Quick check"
}

# Main command handling
case "${1:-full}" in
    "full"|"")
        run_full_diagnostic
        ;;
    "quick")
        quick_check
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