#!/bin/bash
# File: bin/monitoring/lib/commands.sh
# Purpose: Command implementations for BettingPros validation

cmd_test() {
    print_header
    echo -e "${BLUE}🧪 Basic Test Mode${NC}"
    echo ""
    
    # Test GCS access
    echo -e "1. Testing GCS access..."
    if timeout 30 gcloud storage ls "$BUCKET/$BP_EVENTS_PATH/" >/dev/null 2>&1; then
        echo -e "   ${GREEN}✅ Can access events path${NC}"
    else
        echo -e "   ${RED}❌ Cannot access $BUCKET/$BP_EVENTS_PATH/${NC}"
        return 1
    fi
    
    if timeout 30 gcloud storage ls "$BUCKET/$BP_PROPS_PATH/" >/dev/null 2>&1; then
        echo -e "   ${GREEN}✅ Can access props path${NC}"
    else
        echo -e "   ${RED}❌ Cannot access $BUCKET/$BP_PROPS_PATH/${NC}"
        return 1
    fi
    
    # Find a recent date
    echo -e "2. Finding recent dates..."
    local test_date=$(get_recent_dates 1)
    
    if [[ -n "$test_date" ]]; then
        echo -e "   ${GREEN}✅ Found recent date: $test_date${NC}"
        
        # Check this date
        local sample_files
        if sample_files=$(check_date_consistency "$test_date"); then
            if [[ -n "$sample_files" ]]; then
                echo -e "   ${GREEN}✅ Found sample files${NC}"
                
                # Test one file of each type
                local test_files=($(echo "$sample_files" | head -2))
                echo -e "3. Testing file validation..."
                validate_sample_files "${test_files[@]}"
            else
                echo -e "   ${YELLOW}⚠️ No files found in $test_date${NC}"
            fi
        else
            echo -e "   ${YELLOW}⚠️ Date validation issues for $test_date${NC}"
        fi
    else
        echo -e "   ${RED}❌ No recent dates found${NC}"
    fi
}

cmd_missing() {
    print_header
    echo -e "${BLUE}🔍 Schedule-Aware Missing Data Analysis${NC}"
    echo ""
    
    echo -e "${CYAN}Analyzing ${#KNOWN_MISSING_DATES[@]} known missing dates with schedule data:${NC}"
    echo ""
    
    local confirmed_missing=()
    local found_some=()
    local preseason_dates=()
    local allstar_dates=()
    local unknown_dates=()
    local all_files=()
    
    for date in "${KNOWN_MISSING_DATES[@]}"; do
        echo -e "${CYAN}Checking $date:${NC}"
        
        # First check if data exists
        local date_files
        local data_exists=false
        if date_files=$(check_date_consistency "$date"); then
            if [[ -n "$date_files" ]]; then
                found_some+=("$date")
                data_exists=true
                while IFS= read -r file; do
                    [[ -n "$file" ]] && all_files+=("$file")
                done <<< "$date_files"
            fi
        fi
        
        # Check game type from schedule
        echo -e "  ${BLUE}Checking schedule...${NC}"
        local game_type=$(get_game_type_for_date "$date" 2>/dev/null)
        
        case "$game_type" in
            "preseason")
                preseason_dates+=("$date")
                echo -e "  ${YELLOW}📅 Preseason game (no props expected)${NC}"
                ;;
            "allstar")
                allstar_dates+=("$date")
                echo -e "  ${YELLOW}⭐ All-Star/Special event (no props expected)${NC}"
                ;;
            "regular")
                if [[ "$data_exists" == false ]]; then
                    confirmed_missing+=("$date")
                    echo -e "  ${RED}❌ Regular season - ACTUALLY MISSING${NC}"
                else
                    echo -e "  ${GREEN}✅ Regular season - Found data${NC}"
                fi
                ;;
            "none")
                echo -e "  ${BLUE}📅 No games scheduled${NC}"
                ;;
            "unknown")
                unknown_dates+=("$date")
                if [[ "$data_exists" == false ]]; then
                    confirmed_missing+=("$date")
                    echo -e "  ${YELLOW}❓ Unknown game type - Missing data${NC}"
                else
                    echo -e "  ${YELLOW}❓ Unknown game type - Found data${NC}"
                fi
                ;;
        esac
        echo ""
    done
    
    # Smart Summary
    echo -e "${CYAN}📋 Schedule-Aware Analysis:${NC}"
    echo -e "  Total dates analyzed: ${#KNOWN_MISSING_DATES[@]}"
    echo -e "  ${GREEN}✅ Found data: ${#found_some[@]}${NC}"
    echo -e "  ${RED}❌ Actually missing (regular season): ${#confirmed_missing[@]}${NC}"
    echo -e "  ${YELLOW}📅 Expected missing (preseason): ${#preseason_dates[@]}${NC}"
    echo -e "  ${YELLOW}⭐ Expected missing (All-Star): ${#allstar_dates[@]}${NC}"
    echo -e "  ${BLUE}❓ Unknown schedule: ${#unknown_dates[@]}${NC}"
    
    # Calculate true completion rate
    local regular_season_dates=$((${#found_some[@]} + ${#confirmed_missing[@]}))
    if [[ $regular_season_dates -gt 0 ]]; then
        local completion_rate=$(( ${#found_some[@]} * 100 / regular_season_dates ))
        echo -e "  ${GREEN}📊 Regular season completion: $completion_rate%${NC}"
    fi
    
    echo ""
    
    # Show actual issues (if any)
    if [[ ${#confirmed_missing[@]} -gt 0 ]]; then
        echo -e "${RED}🚨 ACTUAL MISSING DATA (needs attention):${NC}"
        printf '  %s\n' "${confirmed_missing[@]}"
    else
        echo -e "${GREEN}🎉 NO ACTUAL MISSING DATA!${NC}"
        echo -e "   All missing dates are expected (preseason/All-Star games)"
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
                if date_files=$(check_date_consistency "$date"); then
                    while IFS= read -r file; do
                        [[ -n "$file" ]] && all_files+=("$file")
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
        echo "  $0 dates 2021-10-19"
        echo "  $0 dates 2021-10-19 2021-10-20 2021-10-21"
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
        if date_files=$(check_date_consistency "$date"); then
            while IFS= read -r file; do
                [[ -n "$file" ]] && all_files+=("$file")
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

cmd_debug_schedule() {
    local date="${1:-2021-10-03}"
    
    print_header
    echo -e "${BLUE}🐛 Debug Schedule Data${NC}"
    echo ""
    
    echo -e "Debug date: $date"
    local season=$(date_to_season "$date")
    echo -e "Season: $season"
    
    # Test the simple date-based logic first
    local month=$(echo "$date" | cut -d'-' -f2)
    local day=$(echo "$date" | cut -d'-' -f3)
    
    # Strip leading zeros
    month=$((10#$month))
    day=$((10#$day))
    
    echo -e "Month: $month, Day: $day"
    
    if [[ $month -eq 10 && $day -le 18 ]]; then
        echo -e "${GREEN}✅ Date-based logic: PRESEASON${NC}"
    else
        echo -e "${YELLOW}⚠️ Date-based logic: NOT PRESEASON${NC}"
    fi
    
    # Get schedule file
    local schedule_file=$(get_schedule_for_season "$season")
    if [[ -z "$schedule_file" || ! -f "$schedule_file" ]]; then
        echo -e "${RED}❌ No schedule file found for season $season${NC}"
        echo -e "Game type result: $(get_game_type_for_date "$date")"
        return 1
    fi
    
    echo -e "Schedule file: $schedule_file"
    
    # Check file size
    local file_size=$(get_file_size "$schedule_file")
    echo -e "File size: ${file_size}B"
    
    # Check if it's valid JSON
    if jq empty "$schedule_file" 2>/dev/null; then
        echo -e "${GREEN}✅ Valid JSON${NC}"
    else
        echo -e "${RED}❌ Invalid JSON${NC}"
        echo -e "First 500 characters:"
        head -c 500 "$schedule_file"
        echo ""
        return 1
    fi
    
    # Convert date for schedule lookup
    local date_mm_dd_yyyy=""
    if command -v gdate >/dev/null 2>&1; then
        date_mm_dd_yyyy=$(gdate -d "$date" "+%m/%d/%Y" 2>/dev/null)
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        date_mm_dd_yyyy=$(date -j -f "%Y-%m-%d" "$date" "+%m/%d/%Y" 2>/dev/null)
    else
        date_mm_dd_yyyy=$(date -d "$date" "+%m/%d/%Y" 2>/dev/null)
    fi
    
    echo -e "Looking for date: $date_mm_dd_yyyy"
    
    # Search for this date in schedule
    local found_games=$(jq -r --arg target_date "$date_mm_dd_yyyy" '
        .gameDates[] | select(.gameDate | startswith($target_date)) | .games | length
    ' "$schedule_file" 2>/dev/null)
    
    if [[ -n "$found_games" && "$found_games" != "null" ]]; then
        echo -e "Found $found_games games for $date_mm_dd_yyyy"
        
        # Show detailed game info
        echo -e "Game details:"
        jq -r --arg target_date "$date_mm_dd_yyyy" '
            .gameDates[] | select(.gameDate | startswith($target_date)) | .games[] | 
            "  Week: \(.weekNumber // "null") | WeekName: \(.weekName // "null") | Label: \(.gameLabel // "null") | SubLabel: \(.gameSubLabel // "null")"
        ' "$schedule_file" 2>/dev/null | head -5
        
        # Show raw game object for debugging
        echo -e "Raw game data (first game):"
        jq -r --arg target_date "$date_mm_dd_yyyy" '
            .gameDates[] | select(.gameDate | startswith($target_date)) | .games[0]
        ' "$schedule_file" 2>/dev/null
    else
        echo -e "No games found for $date_mm_dd_yyyy"
    fi
    
    # Test final game type detection
    echo -e ""
    echo -e "Final game type result: ${CYAN}$(get_game_type_for_date "$date")${NC}"
}

cmd_seasons() {
    print_header
    echo -e "${BLUE}📅 Season Coverage Analysis${NC}"
    echo ""
    
    echo -e "1. Scanning all available dates..."
    
    # Get all dates from events directory
    local all_dates=$(timeout 60 gcloud storage ls "$BUCKET/$BP_EVENTS_PATH/" 2>/dev/null | \
        grep -E "[0-9]{4}-[0-9]{2}-[0-9]{2}" | \
        xargs -I {} basename {} | sort)
    
    if [[ -z "$all_dates" ]]; then
        echo -e "${RED}❌ No dates found${NC}"
        return 1
    fi
    
    local total_dates=$(echo "$all_dates" | wc -l | tr -d ' ')
    echo -e "   Found $total_dates total dates"
    
    # Group by season
    local seasons_file="/tmp/seasons_analysis_$.txt"
    rm -f "$seasons_file"
    
    echo -e "2. Grouping by NBA season..."
    while IFS= read -r date; do
        if [[ -n "$date" ]]; then
            local season=$(date_to_season "$date")
            echo "$season|$date" >> "$seasons_file"
        fi
    done <<< "$all_dates"
    
    # Analyze each season
    echo -e "3. Season-by-season analysis:"
    echo ""
    
    local seasons=($(cut -d'|' -f1 "$seasons_file" | sort -u))
    
    for season in "${seasons[@]}"; do
        echo -e "${CYAN}🏀 NBA $season Season:${NC}"
        
        # Get dates for this season
        local season_dates=($(grep "^$season|" "$seasons_file" | cut -d'|' -f2 | sort))
        local season_count=${#season_dates[@]}
        
        # Get first and last dates
        local first_date=${season_dates[0]}
        local last_date=${season_dates[$((season_count-1))]}
        
        echo -e "   📊 Total dates: ${GREEN}$season_count${NC}"
        echo -e "   📅 Range: $first_date → $last_date"
        
        # Check events vs props coverage for this season
        local events_count=0
        local props_count=0
        local sample_dates=("${season_dates[@]:0:10}")  # Check first 10 dates
        
        for date in "${sample_dates[@]}"; do
            if timeout 10 gcloud storage ls "$BUCKET/$BP_EVENTS_PATH/$date/" >/dev/null 2>&1; then
                events_count=$((events_count + 1))
            fi
            if timeout 10 gcloud storage ls "$BUCKET/$BP_PROPS_PATH/$date/" >/dev/null 2>&1; then
                props_count=$((props_count + 1))
            fi
        done
        
        local sample_size=${#sample_dates[@]}
        local events_pct=$((events_count * 100 / sample_size))
        local props_pct=$((props_count * 100 / sample_size))
        
        echo -e "   📈 Sample coverage (first $sample_size dates):"
        echo -e "      Events: ${GREEN}$events_pct%${NC} | Props: ${GREEN}$props_pct%${NC}"
        
        # Identify potential issues
        if [[ $props_pct -lt $events_pct ]]; then
            local missing_props=$((events_count - props_count))
            echo -e "      ${YELLOW}⚠️ $missing_props dates have events but missing props${NC}"
        fi
        
        echo ""
    done
    
    # Overall stats
    echo -e "${CYAN}📋 Overall Coverage:${NC}"
    echo -e "   Seasons with data: ${GREEN}${#seasons[@]}${NC}"
    echo -e "   Total dates: ${GREEN}$total_dates${NC}"
    echo -e "   Date range: ${GREEN}$(echo "$all_dates" | head -1)${NC} → ${GREEN}$(echo "$all_dates" | tail -1)${NC}"
    
    # Clean up
    rm -f "$seasons_file"
}

cmd_summary() {
    print_header
    echo -e "${BLUE}📊 Schedule-Aware Data Summary${NC}"
    echo ""
    
    # Quick directory counts
    echo -e "1. Counting directories..."
    local events_dirs=$(timeout 30 gcloud storage ls "$BUCKET/$BP_EVENTS_PATH/" 2>/dev/null | grep -E "[0-9]{4}-[0-9]{2}-[0-9]{2}" | wc -l | tr -d ' ')
    local props_dirs=$(timeout 30 gcloud storage ls "$BUCKET/$BP_PROPS_PATH/" 2>/dev/null | grep -E "[0-9]{4}-[0-9]{2}-[0-9]{2}" | wc -l | tr -d ' ')
    
    echo -e "   Events directories: ${GREEN}$events_dirs${NC}"
    echo -e "   Props directories: ${GREEN}$props_dirs${NC}"
    echo -e "   Difference: $((events_dirs - props_dirs))"
    
    # Smart missing analysis with schedule awareness
    echo -e "2. Schedule-aware analysis..."
    local still_missing=0
    local preseason_missing=0
    local regular_missing=0
    
    for date in "${KNOWN_MISSING_DATES[@]}"; do
        local has_props=false
        if timeout 10 gcloud storage ls "$BUCKET/$BP_PROPS_PATH/$date/" >/dev/null 2>&1; then
            has_props=true
        fi
        
        if [[ "$has_props" == false ]]; then
            still_missing=$((still_missing + 1))
            
            # Check game type
            local game_type=$(get_game_type_for_date "$date" 2>/dev/null)
            if [[ "$game_type" == "preseason" || "$game_type" == "allstar" ]]; then
                preseason_missing=$((preseason_missing + 1))
            else
                regular_missing=$((regular_missing + 1))
            fi
        fi
    done
    
    echo -e "   Known issues: ${#KNOWN_MISSING_DATES[@]} dates"
    echo -e "   Still missing: ${RED}$still_missing${NC}"
    echo -e "   └─ Expected (preseason/All-Star): ${YELLOW}$preseason_missing${NC}"
    echo -e "   └─ Actual missing (regular season): ${RED}$regular_missing${NC}"
    echo -e "   Recovered: ${GREEN}$((${#KNOWN_MISSING_DATES[@]} - still_missing))${NC}"
    
    # Date range
    echo -e "3. Date range..."
    local first_date=$(timeout 20 gcloud storage ls "$BUCKET/$BP_EVENTS_PATH/" 2>/dev/null | grep -E "[0-9]{4}-[0-9]{2}-[0-9]{2}" | sort | head -1 | xargs -I {} basename {})
    local last_date=$(timeout 20 gcloud storage ls "$BUCKET/$BP_EVENTS_PATH/" 2>/dev/null | grep -E "[0-9]{4}-[0-9]{2}-[0-9]{2}" | sort | tail -1 | xargs -I {} basename {})
    
    echo -e "   First date: ${GREEN}$first_date${NC}"
    echo -e "   Last date: ${GREEN}$last_date${NC}"
    
    echo ""
    
    # Smart recommendations
    echo -e "${CYAN}💡 Smart recommendations:${NC}"
    if [[ $regular_missing -eq 0 ]]; then
        echo -e "  ${GREEN}✅ No actual missing data - collection is complete!${NC}"
        echo -e "  • All 'missing' dates are expected (preseason/All-Star)"
        echo -e "  • Run './validate_bp_data.sh recent 5' to validate recent data quality"
    else
        echo -e "  ${RED}• $regular_missing regular season dates need attention${NC}"
        echo -e "  • Run './validate_bp_data.sh missing' for detailed analysis"
    fi
    
    echo -e "  • Run './validate_bp_data.sh test' for basic functionality check"
}