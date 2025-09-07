#!/bin/bash
# File: bin/monitoring/lib/gcs.sh
# Purpose: Google Cloud Storage operations

# Check a specific date for both events and props
check_date_consistency() {
    local date="$1"
    local events_path="$BUCKET/$BP_EVENTS_PATH/$date/"
    local props_path="$BUCKET/$BP_PROPS_PATH/$date/"
    
    echo -e "  ${BLUE}Checking date:${NC} $date" >&2
    
    # Check events
    local has_events=false
    local events_files=()
    if timeout 30 gcloud storage ls "$events_path" >/dev/null 2>&1; then
        local events_list=$(timeout 20 gcloud storage ls "$events_path" 2>/dev/null | grep "\.json$" | head -3)
        if [[ -n "$events_list" ]]; then
            has_events=true
            while IFS= read -r file; do
                [[ -n "$file" ]] && events_files+=("$file")
            done <<< "$events_list"
        fi
    fi
    
    # Check props
    local has_props=false
    local props_files=()
    if timeout 30 gcloud storage ls "$props_path" >/dev/null 2>&1; then
        local props_list=$(timeout 20 gcloud storage ls "$props_path" 2>/dev/null | grep "\.json$" | head -3)
        if [[ -n "$props_list" ]]; then
            has_props=true
            while IFS= read -r file; do
                [[ -n "$file" ]] && props_files+=("$file")
            done <<< "$props_list"
        fi
    fi
    
    # Report status
    if [[ "$has_events" == true && "$has_props" == true ]]; then
        echo -e "    ${GREEN}✅ Both events and props present${NC}" >&2
        echo -e "    📊 Events: ${#events_files[@]} files | Props: ${#props_files[@]} files" >&2
        
        # Return sample files for validation
        printf '%s\n' "${events_files[@]}" "${props_files[@]}"
        return 0
        
    elif [[ "$has_events" == true && "$has_props" == false ]]; then
        echo -e "    ${YELLOW}⚠️  Events present, props missing${NC}" >&2
        echo -e "    📊 Events: ${#events_files[@]} files | Props: 0 files" >&2
        
        # Still return events files
        printf '%s\n' "${events_files[@]}"
        return 1
        
    elif [[ "$has_events" == false && "$has_props" == true ]]; then
        echo -e "    ${YELLOW}⚠️  Props present, events missing${NC}" >&2
        echo -e "    📊 Events: 0 files | Props: ${#props_files[@]} files" >&2
        
        # Still return props files
        printf '%s\n' "${props_files[@]}"
        return 1
        
    else
        echo -e "    ${RED}❌ Both events and props missing${NC}" >&2
        return 1
    fi
}

# Get recent dates from the BettingPros data
get_recent_dates() {
    local count="${1:-3}"
    
    echo -e "Scanning for recent dates..." >&2
    
    # Get dates from events directory (should be more complete)
    local recent_dates=$(timeout 45 gcloud storage ls "$BUCKET/$BP_EVENTS_PATH/" 2>/dev/null | \
        grep -E "[0-9]{4}-[0-9]{2}-[0-9]{2}" | \
        sort -r | head -$count | xargs -I {} basename {})
    
    if [[ -n "$recent_dates" ]]; then
        echo "$recent_dates"
        return 0
    else
        return 1
    fi
}

# Download a file safely with timeout
download_file_safe() {
    local source_path="$1"
    local dest_path="$2"
    
    if ! timeout 30 gcloud storage cp "$source_path" "$dest_path" >/dev/null 2>&1; then
        return 1
    fi
    
    # Check if file exists and has content
    if [[ ! -f "$dest_path" ]] || [[ $(get_file_size "$dest_path") -eq 0 ]]; then
        rm -f "$dest_path"
        return 1
    fi
    
    return 0
}