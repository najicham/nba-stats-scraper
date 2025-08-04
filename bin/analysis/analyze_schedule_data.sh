#!/bin/bash
# SAVE TO: ~/code/nba-stats-scraper/bin/analysis/analyze_schedule_data.sh
# NBA Schedule Data Analyzer - Comprehensive analysis of collected schedule data

PROJECT_ID="nba-props-platform"
BUCKET="nba-scraped-data"
SCHEDULE_PATH="nba-com/schedule"
TEMP_DIR="/tmp/nba_schedule_analysis"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Default values
MODE="summary"
SPECIFIC_DATE=""
DOWNLOAD_LATEST=false
DETAILED_ANALYSIS=false

# Help function
show_help() {
    cat << EOF
🏀 NBA Schedule Data Analyzer

USAGE:
    $0 [OPTIONS]

OPTIONS:
    --mode MODE           Analysis mode: summary, detailed, files, latest, date (default: summary)
    --date DATE           Analyze specific date (YYYY-MM-DD format)
    --download            Download latest file for local inspection
    --detailed            Show detailed statistics and validation
    --help                Show this help message

MODES:
    summary      Quick overview of all schedule data
    detailed     Comprehensive analysis with statistics
    files        List all schedule files with metadata
    latest       Analyze the most recent collection
    date         Analyze files from specific date (requires --date)

EXAMPLES:
    $0                                    # Quick summary
    $0 --mode detailed                    # Comprehensive analysis
    $0 --mode files                       # List all files
    $0 --mode latest --download           # Analyze latest + download for inspection
    $0 --mode date --date 2025-08-03      # Analyze files from specific date

REQUIREMENTS:
    - gcloud CLI configured for project: $PROJECT_ID
    - jq installed for JSON processing
    - Access to gs://$BUCKET/

OUTPUT:
    - Analysis results printed to console
    - Downloaded files saved to: $TEMP_DIR/
EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --mode)
            MODE="$2"
            shift 2
            ;;
        --date)
            SPECIFIC_DATE="$2"
            shift 2
            ;;
        --download)
            DOWNLOAD_LATEST=true
            shift
            ;;
        --detailed)
            DETAILED_ANALYSIS=true
            shift
            ;;
        --help)
            show_help
            exit 0
            ;;
        *)
            echo "❌ Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Validate mode
if [[ ! "$MODE" =~ ^(summary|detailed|files|latest|date)$ ]]; then
    echo "❌ Invalid mode: $MODE"
    echo "Valid modes: summary, detailed, files, latest, date"
    exit 1
fi

# Check prerequisites
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

echo -e "${BLUE}🏀 NBA Schedule Data Analyzer${NC}"
echo "=================================="
echo "Project: $PROJECT_ID"
echo "Bucket: gs://$BUCKET/$SCHEDULE_PATH"
echo "Mode: $MODE"
echo "Timestamp: $(date)"
echo ""

# Check prerequisites
if ! command_exists gcloud; then
    echo -e "${RED}❌ gcloud CLI not found${NC}"
    exit 1
fi

if ! command_exists jq; then
    echo -e "${RED}❌ jq not found (required for JSON processing)${NC}"
    echo "Install with: brew install jq (macOS) or apt-get install jq (Linux)"
    exit 1
fi

# Create temp directory
mkdir -p "$TEMP_DIR"

# Function to get all schedule files
get_all_files() {
    echo -e "${CYAN}📋 Discovering schedule files...${NC}"
    gcloud storage ls -r "gs://$BUCKET/$SCHEDULE_PATH/" | grep "\.json$" | sort
}

# Function to get files from specific date
get_files_by_date() {
    local date="$1"
    echo -e "${CYAN}📋 Getting files from $date...${NC}"
    gcloud storage ls "gs://$BUCKET/$SCHEDULE_PATH/$date/" 2>/dev/null | grep "\.json$" | sort
}

# Function to analyze a single file
analyze_file() {
    local file_path="$1"
    local temp_file="$TEMP_DIR/$(basename "$file_path")"
    
    echo -e "${CYAN}📁 Analyzing: $(basename "$file_path")${NC}"
    
    # Download file
    if gcloud storage cp "$file_path" "$temp_file" 2>/dev/null; then
        # Extract key information using jq
        local season=$(jq -r '.season_nba_format // .season // "Unknown"' "$temp_file" 2>/dev/null)
        local game_count=$(jq -r '.game_count // (.games | length) // 0' "$temp_file" 2>/dev/null)
        local timestamp=$(jq -r '.timestamp // "Unknown"' "$temp_file" 2>/dev/null)
        
        # Get date range from games
        local first_game_date=$(jq -r '.games[0].gameDate // "Unknown"' "$temp_file" 2>/dev/null)
        local last_game_date=$(jq -r '.games[-1].gameDate // "Unknown"' "$temp_file" 2>/dev/null)
        
        # Get unique teams
        local team_count=$(jq -r '[.games[].homeTeam.teamName, .games[].awayTeam.teamName] | unique | length' "$temp_file" 2>/dev/null)
        
        # File size
        local file_size=$(du -h "$temp_file" | cut -f1)
        
        echo "  Season: $season"
        echo "  Games: $game_count"
        echo "  Date Range: $first_game_date to $last_game_date"
        echo "  Teams: $team_count unique teams"
        echo "  File Size: $file_size"
        echo "  Timestamp: $timestamp"
        echo ""
        
        # Return key metrics for summary
        echo "$season,$game_count,$team_count,$file_size"
    else
        echo -e "${RED}  ❌ Failed to download file${NC}"
        echo "Unknown,0,0,0KB"
    fi
}

# Function to show file listing
show_files() {
    echo -e "${CYAN}📁 Schedule Files Inventory${NC}"
    echo "=========================="
    
    local all_files
    all_files=$(get_all_files)
    
    if [[ -z "$all_files" ]]; then
        echo -e "${RED}❌ No schedule files found${NC}"
        return 1
    fi
    
    local file_count=$(echo "$all_files" | wc -l)
    echo "Total files: $file_count"
    echo ""
    
    echo "Files by date:"
    echo "$all_files" | while read -r file; do
        # Extract date from path
        local date_part=$(echo "$file" | grep -o '[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}' | head -1)
        local timestamp_part=$(basename "$file" .json)
        echo "  $date_part: $timestamp_part"
    done
    
    echo ""
    echo "Storage locations:"
    echo "$all_files" | sed 's|/[^/]*\.json$||' | sort | uniq -c | while read -r count path; do
        local date_part=$(echo "$path" | grep -o '[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}')
        echo "  $date_part: $count files"
    done
}

# Function to show summary analysis
show_summary() {
    echo -e "${CYAN}📊 Schedule Data Summary${NC}"
    echo "======================="
    
    local all_files
    all_files=$(get_all_files)
    
    if [[ -z "$all_files" ]]; then
        echo -e "${RED}❌ No schedule files found${NC}"
        return 1
    fi
    
    local file_count=$(echo "$all_files" | wc -l)
    echo "Total files: $file_count"
    echo ""
    
    # Analyze up to 10 most recent files for summary
    local recent_files
    recent_files=$(echo "$all_files" | tail -10)
    
    echo -e "${YELLOW}Analyzing recent files...${NC}"
    local total_games=0
    local seasons_found=()
    
    while read -r file; do
        if [[ -n "$file" ]]; then
            local result
            result=$(analyze_file "$file")
            local metrics
            metrics=$(echo "$result" | tail -1)
            
            IFS=',' read -r season games teams size <<< "$metrics"
            if [[ "$games" != "0" && "$season" != "Unknown" ]]; then
                total_games=$((total_games + games))
                seasons_found+=("$season")
            fi
        fi
    done <<< "$recent_files"
    
    echo -e "${GREEN}📈 Summary Statistics${NC}"
    echo "===================="
    echo "Total games analyzed: $total_games"
    echo "Seasons found: $(printf '%s\n' "${seasons_found[@]}" | sort | uniq | tr '\n' ', ' | sed 's/,$//')"
    echo "Unique seasons: $(printf '%s\n' "${seasons_found[@]}" | sort | uniq | wc -l)"
    echo ""
    
    echo -e "${BLUE}💡 Quick Stats${NC}"
    echo "============="
    if [[ ${#seasons_found[@]} -gt 0 ]]; then
        local avg_games=$((total_games / ${#seasons_found[@]}))
        echo "Average games per file: $avg_games"
    fi
    echo "Files analyzed: $(echo "$recent_files" | wc -l)"
}

# Function to analyze latest collection
analyze_latest() {
    echo -e "${CYAN}🕐 Latest Collection Analysis${NC}"
    echo "============================="
    
    local all_files
    all_files=$(get_all_files)
    
    if [[ -z "$all_files" ]]; then
        echo -e "${RED}❌ No schedule files found${NC}"
        return 1
    fi
    
    # Get the most recent date directory
    local latest_date
    latest_date=$(echo "$all_files" | grep -o '[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}' | sort | tail -1)
    
    echo "Latest collection date: $latest_date"
    echo ""
    
    # Get all files from latest date
    local latest_files
    latest_files=$(get_files_by_date "$latest_date")
    
    if [[ -z "$latest_files" ]]; then
        echo -e "${RED}❌ No files found for latest date${NC}"
        return 1
    fi
    
    local file_count=$(echo "$latest_files" | wc -l)
    echo "Files in latest collection: $file_count"
    echo ""
    
    # Analyze each file from latest collection
    local total_games=0
    local file_index=1
    
    while read -r file; do
        if [[ -n "$file" ]]; then
            echo -e "${YELLOW}File $file_index/$file_count:${NC}"
            local result
            result=$(analyze_file "$file")
            local metrics
            metrics=$(echo "$result" | tail -1)
            
            IFS=',' read -r season games teams size <<< "$metrics"
            if [[ "$games" != "0" ]]; then
                total_games=$((total_games + games))
            fi
            
            # Download latest file if requested
            if [[ "$DOWNLOAD_LATEST" == true && $file_index -eq 1 ]]; then
                local temp_file="$TEMP_DIR/latest_schedule.json"
                echo -e "${CYAN}💾 Downloading latest file for inspection...${NC}"
                gcloud storage cp "$file" "$temp_file"
                echo "📁 Downloaded to: $temp_file"
                echo ""
                echo -e "${YELLOW}📋 Sample data structure:${NC}"
                echo "First 3 games:"
                jq '.games[0:3] | .[] | {gameDate, homeTeam: .homeTeam.teamName, awayTeam: .awayTeam.teamName, gameId}' "$temp_file" 2>/dev/null || echo "Could not parse sample data"
                echo ""
            fi
            
            file_index=$((file_index + 1))
        fi
    done <<< "$latest_files"
    
    echo -e "${GREEN}🎯 Latest Collection Summary${NC}"
    echo "============================"
    echo "Total games in latest collection: $total_games"
    echo "Collection date: $latest_date"
    echo "Files collected: $file_count"
    
    if [[ "$DOWNLOAD_LATEST" == true ]]; then
        echo ""
        echo -e "${BLUE}💻 Local Files Available:${NC}"
        ls -la "$TEMP_DIR"/*.json 2>/dev/null || echo "No JSON files downloaded"
    fi
}

# Function for detailed analysis
show_detailed_analysis() {
    echo -e "${CYAN}🔍 Detailed Schedule Analysis${NC}"
    echo "============================="
    
    # First show summary
    show_summary
    
    echo ""
    echo -e "${CYAN}📊 Advanced Statistics${NC}"
    echo "====================="
    
    # Analyze all files for detailed stats
    local all_files
    all_files=$(get_all_files)
    
    if [[ -z "$all_files" ]]; then
        echo -e "${RED}❌ No files to analyze${NC}"
        return 1
    fi
    
    echo "Performing comprehensive analysis..."
    echo ""
    
    # Storage analysis
    echo -e "${YELLOW}💾 Storage Analysis${NC}"
    echo "=================="
    local total_size
    total_size=$(gcloud storage du -s "gs://$BUCKET/$SCHEDULE_PATH/" 2>/dev/null | grep -o '^[0-9]*' || echo "0")
    echo "Total storage used: ${total_size} bytes"
    
    # File distribution by date
    echo ""
    echo -e "${YELLOW}📅 File Distribution${NC}"
    echo "==================="
    echo "$all_files" | grep -o '[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}' | sort | uniq -c | while read -r count date; do
        echo "  $date: $count files"
    done
    
    echo ""
    echo -e "${BLUE}💡 Recommendations${NC}"
    echo "=================="
    echo "• Use latest collection files for current season analysis"
    echo "• Historical data spans multiple seasons - ideal for ML training"
    echo "• Consider organizing data by season for easier access"
    echo "• Game IDs in these files can be used for box score collection"
}

# Main execution
case "$MODE" in
    "summary")
        show_summary
        ;;
    "detailed")
        show_detailed_analysis
        ;;
    "files")
        show_files
        ;;
    "latest")
        analyze_latest
        ;;
    "date")
        if [[ -z "$SPECIFIC_DATE" ]]; then
            echo -e "${RED}❌ Date mode requires --date parameter${NC}"
            echo "Example: $0 --mode date --date 2025-08-03"
            exit 1
        fi
        
        echo -e "${CYAN}📅 Analyzing files from $SPECIFIC_DATE${NC}"
        echo "================================="
        
        local date_files
        date_files=$(get_files_by_date "$SPECIFIC_DATE")
        
        if [[ -z "$date_files" ]]; then
            echo -e "${RED}❌ No files found for date: $SPECIFIC_DATE${NC}"
            exit 1
        fi
        
        local file_count=$(echo "$date_files" | wc -l)
        echo "Files found: $file_count"
        echo ""
        
        while read -r file; do
            if [[ -n "$file" ]]; then
                analyze_file "$file"
            fi
        done <<< "$date_files"
        ;;
esac

echo ""
echo -e "${GREEN}✅ Analysis complete!${NC}"

if [[ -d "$TEMP_DIR" && -n "$(ls -A "$TEMP_DIR" 2>/dev/null)" ]]; then
    echo ""
    echo -e "${BLUE}📁 Temporary files created in: $TEMP_DIR${NC}"
    echo "Use these files for further analysis with jq, or clean up when done."
fi
