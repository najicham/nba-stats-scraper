#!/bin/bash
# File: bin/monitoring/lib/validation.sh
# Purpose: JSON validation functions for BettingPros data

# Validate individual props JSON file
validate_props_json() {
    local file_path="$1"
    local temp_file="/tmp/bp_props_validate_$(date +%s)_$$.json"
    
    echo -e "    ${BLUE}Downloading:${NC} $(basename "$file_path")"
    
    # Download file with timeout
    if ! download_file_safe "$file_path" "$temp_file"; then
        echo -e "    ${RED}❌ Download failed${NC}"
        return 1
    fi
    
    local file_size=$(get_file_size "$temp_file")
    
    # Validate JSON
    if ! jq empty "$temp_file" 2>/dev/null; then
        echo -e "    ${RED}❌ Invalid JSON format${NC}"
        rm -f "$temp_file"
        return 1
    fi
    
    # Extract key data points for props
    local analysis=$(jq -r '
        {
            has_date: (has("date")),
            has_sport: (has("sport")),
            has_event_ids: (has("event_ids")),
            has_props: (has("props")),
            date: (.date // "missing"),
            sport: (.sport // "missing"),
            market_type: (.market_type // "missing"),
            event_count: (if .event_ids then (.event_ids | length) else 0 end),
            props_count: (.props_count // 0),
            players_count: (.players_count // 0),
            actual_props_count: (if .props then (.props | length) else 0 end),
            sportsbook_count: (if .props and (.props | length > 0) and .props[0].over and .props[0].over.sportsbooks then (.props[0].over.sportsbooks | length) else 0 end),
            has_betmgm: (if .props and (.props | length > 0) and .props[0].over and .props[0].over.sportsbooks then (.props[0].over.sportsbooks | map(.book_name) | any(. == "BetMGM")) else false end)
        }
    ' "$temp_file" 2>/dev/null)
    
    if [[ -z "$analysis" ]]; then
        echo -e "    ${RED}❌ Failed to analyze props JSON structure${NC}"
        rm -f "$temp_file"
        return 1
    fi
    
    # Extract values
    local has_date=$(echo "$analysis" | jq -r '.has_date')
    local has_sport=$(echo "$analysis" | jq -r '.has_sport')
    local has_event_ids=$(echo "$analysis" | jq -r '.has_event_ids')
    local has_props=$(echo "$analysis" | jq -r '.has_props')
    local date=$(echo "$analysis" | jq -r '.date')
    local sport=$(echo "$analysis" | jq -r '.sport')
    local market_type=$(echo "$analysis" | jq -r '.market_type')
    local event_count=$(echo "$analysis" | jq -r '.event_count')
    local props_count=$(echo "$analysis" | jq -r '.props_count')
    local players_count=$(echo "$analysis" | jq -r '.players_count')
    local actual_props_count=$(echo "$analysis" | jq -r '.actual_props_count')
    local sportsbook_count=$(echo "$analysis" | jq -r '.sportsbook_count')
    local has_betmgm=$(echo "$analysis" | jq -r '.has_betmgm')
    
    # Quality score calculation
    local quality_score=0
    local issues=()
    
    # Required structure (40 points total)
    [[ "$has_date" == "true" ]] && quality_score=$((quality_score + 10)) || issues+=("Missing date")
    [[ "$has_sport" == "true" && "$sport" == "NBA" ]] && quality_score=$((quality_score + 10)) || issues+=("Missing/wrong sport")
    [[ "$has_event_ids" == "true" ]] && quality_score=$((quality_score + 10)) || issues+=("Missing event_ids")
    [[ "$has_props" == "true" ]] && quality_score=$((quality_score + 10)) || issues+=("Missing props array")
    
    # Data consistency (30 points total)
    if [[ $props_count -eq $actual_props_count && $props_count -gt 0 ]]; then
        quality_score=$((quality_score + 15))
    else
        issues+=("Props count mismatch: claimed $props_count, actual $actual_props_count")
    fi
    
    if [[ $players_count -eq $actual_props_count || $players_count -gt 0 ]]; then
        quality_score=$((quality_score + 15))
    else
        issues+=("Player count inconsistency")
    fi
    
    # Data volume validation (20 points total)
    if [[ $props_count -ge 50 ]]; then
        quality_score=$((quality_score + 10))
    elif [[ $props_count -ge 20 ]]; then
        quality_score=$((quality_score + 5))
        issues+=("Low props count: $props_count")
    else
        issues+=("Very low props count: $props_count")
    fi
    
    if [[ $event_count -ge 5 && $event_count -le 15 ]]; then
        quality_score=$((quality_score + 10))
    else
        issues+=("Unusual event count: $event_count")
    fi
    
    # Sportsbook validation (10 points total)
    if [[ "$has_betmgm" == "true" ]]; then
        quality_score=$((quality_score + 5))
    else
        issues+=("Missing BetMGM")
    fi
    
    if [[ $sportsbook_count -ge 3 ]]; then
        quality_score=$((quality_score + 5))
    else
        issues+=("Few sportsbooks: $sportsbook_count")
    fi
    
    # Display results
    local quality_color=$GREEN
    [[ $quality_score -lt 75 ]] && quality_color=$YELLOW
    [[ $quality_score -lt 50 ]] && quality_color=$RED
    
    echo -e "    ${GREEN}✅ Valid Props JSON${NC} - ${file_size}B"
    echo -e "    📅 Date: $date | 🏀 Sport: $sport | 📊 Market: $market_type"
    echo -e "    🎯 Events: $event_count | Props: $props_count ($actual_props_count actual)"
    echo -e "    👥 Players: $players_count | 💰 Sportsbooks: $sportsbook_count"
    echo -e "    📈 Quality: ${quality_color}$quality_score/100${NC}"
    
    if [[ ${#issues[@]} -gt 0 ]]; then
        echo -e "    ⚠️  Issues: ${issues[*]}"
    fi
    
    rm -f "$temp_file"
    return 0
}

# Validate individual events JSON file  
validate_events_json() {
    local file_path="$1"
    local temp_file="/tmp/bp_events_validate_$(date +%s)_$$.json"
    
    echo -e "    ${BLUE}Downloading:${NC} $(basename "$file_path")"
    
    # Download file with timeout
    if ! download_file_safe "$file_path" "$temp_file"; then
        echo -e "    ${RED}❌ Download failed${NC}"
        return 1
    fi
    
    local file_size=$(get_file_size "$temp_file")
    
    # Validate JSON
    if ! jq empty "$temp_file" 2>/dev/null; then
        echo -e "    ${RED}❌ Invalid JSON format${NC}"
        rm -f "$temp_file"
        return 1
    fi
    
    # Basic events validation
    local analysis=$(jq -r '
        {
            has_timestamp: (has("timestamp")),
            has_date: (has("date")),
            event_count: (if type == "array" then length else 1 end),
            file_type: type
        }
    ' "$temp_file" 2>/dev/null)
    
    if [[ -z "$analysis" ]]; then
        echo -e "    ${RED}❌ Failed to analyze events JSON structure${NC}"
        rm -f "$temp_file"
        return 1
    fi
    
    local has_timestamp=$(echo "$analysis" | jq -r '.has_timestamp')
    local has_date=$(echo "$analysis" | jq -r '.has_date')
    local event_count=$(echo "$analysis" | jq -r '.event_count')
    local file_type=$(echo "$analysis" | jq -r '.file_type')
    
    echo -e "    ${GREEN}✅ Valid Events JSON${NC} - ${file_size}B"
    echo -e "    📊 Type: $file_type | Events: $event_count"
    echo -e "    🕐 Has timestamp: $has_timestamp | Has date: $has_date"
    
    rm -f "$temp_file"
    return 0
}

# Validate sample files
validate_sample_files() {
    local files=("$@")
    
    echo -e "${BLUE}📊 Validating ${#files[@]} sample files:${NC}"
    echo ""
    
    local valid_files=0
    local events_files=0
    local props_files=0
    local file_num=0
    
    for file_path in "${files[@]}"; do
        file_num=$((file_num + 1))
        
        echo -e "${CYAN}[$file_num/${#files[@]}]${NC} $(basename "$(dirname "$file_path")")/$(basename "$file_path")"
        
        # Determine file type and validate accordingly
        if [[ "$file_path" == *"/events/"* ]]; then
            events_files=$((events_files + 1))
            if validate_events_json "$file_path"; then
                valid_files=$((valid_files + 1))
            fi
        elif [[ "$file_path" == *"/player-props/"* ]]; then
            props_files=$((props_files + 1))
            if validate_props_json "$file_path"; then
                valid_files=$((valid_files + 1))
            fi
        else
            echo -e "    ${YELLOW}⚠️  Unknown file type${NC}"
        fi
        echo ""
    done
    
    # Summary
    echo -e "${CYAN}📋 Validation Summary:${NC}"
    echo -e "  Files validated: ${#files[@]} (Events: $events_files, Props: $props_files)"
    echo -e "  Valid files: ${GREEN}$valid_files${NC}"
    [[ ${#files[@]} -gt 0 ]] && echo -e "  Success rate: $(( valid_files * 100 / ${#files[@]} ))%"
}