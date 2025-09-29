#!/bin/bash
# FILE: bin/shared/deploy_wrapper_common.sh
# Shared functions for deployment wrapper scripts

# Function to start deployment timing
start_deployment_timer() {
    export DEPLOY_WRAPPER_START_TIME=$(date +%s)
    export DEPLOY_WRAPPER_START_DISPLAY=$(TZ=America/Los_Angeles date '+%Y-%m-%d %I:%M:%S %p %Z')
}

# Function to print colored section header
print_section_header() {
    local header_text="$1"
    echo -e "\033[1;33m${header_text}:\033[0m"
}

# Function to print final timing summary
print_deployment_summary() {
    local end_time=$(date +%s)
    local duration=$((end_time - DEPLOY_WRAPPER_START_TIME))
    local end_display=$(TZ=America/Los_Angeles date '+%Y-%m-%d %I:%M:%S %p %Z')
    
    # Format duration nicely
    local duration_display
    if [ $duration -lt 60 ]; then
        duration_display="${duration}s"
    elif [ $duration -lt 3600 ]; then
        local minutes=$((duration / 60))
        local seconds=$((duration % 60))
        duration_display="${minutes}m ${seconds}s"
    else
        local hours=$((duration / 3600))
        local minutes=$(((duration % 3600) / 60))
        local seconds=$((duration % 60))
        duration_display="${hours}h ${minutes}m ${seconds}s"
    fi
    
    echo ""
    echo -e "\033[1;31m🎯 TOTAL DEPLOYMENT TIME\033[0m"
    echo -e "\033[1;31m========================\033[0m"
    echo "Started:  $DEPLOY_WRAPPER_START_DISPLAY"
    echo "Finished: $end_display"
    echo "Duration: $duration_display"
    echo ""
}