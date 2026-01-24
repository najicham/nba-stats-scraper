#!/bin/bash
set -euo pipefail
# File: bin/utilities/list_deployable_jobs.sh
# List all available deployment jobs across processor types

echo "NBA Props Platform - Available Jobs"
echo "==================================="
echo ""

# Function to extract job details from config
get_job_details() {
    local config_file="$1"
    local job_name description memory cpu timeout
    
    if [[ -f "$config_file" ]]; then
        job_name=$(grep "^JOB_NAME=" "$config_file" | cut -d'=' -f2- | tr -d '"')
        description=$(grep "^JOB_DESCRIPTION=" "$config_file" | cut -d'=' -f2- | tr -d '"')
        memory=$(grep "^MEMORY=" "$config_file" | cut -d'=' -f2- | tr -d '"')
        cpu=$(grep "^CPU=" "$config_file" | cut -d'=' -f2- | tr -d '"')
        timeout=$(grep "^TASK_TIMEOUT=" "$config_file" | cut -d'=' -f2- | tr -d '"')
        
        printf "  %-25s %s\n" "$job_name" "$description"
        printf "  %-25s Resources: %s, %s, %s\n" "" "$memory" "$cpu" "$timeout"
        echo ""
    fi
}

# Reference Processors
echo "🔍 Reference Processors"
echo "======================="
echo "Deploy with: ./bin/reference/deploy/deploy_reference_processor_backfill.sh <job-name>"
echo ""

reference_found=false
while read -r config; do
    reference_found=true
    dir_name=$(dirname "$config" | sed 's|backfill_jobs/reference/||')
    echo "Job: $dir_name"
    get_job_details "$config"
done < <(find backfill_jobs/reference/ -name "job-config.env" 2>/dev/null | sort)

if [[ "$reference_found" == false ]]; then
    echo "  No reference jobs configured"
    echo ""
fi

# Analytics Processors
echo "🧮 Analytics Processors"
echo "======================="
echo "Deploy with: ./bin/analytics/deploy/deploy_analytics_processor_backfill.sh <job-name>"
echo ""

analytics_found=false
while read -r config; do
    analytics_found=true
    dir_name=$(dirname "$config" | sed 's|backfill_jobs/analytics/||')
    echo "Job: $dir_name"
    get_job_details "$config"
done < <(find backfill_jobs/analytics/ -name "job-config.env" 2>/dev/null | sort)

if [[ "$analytics_found" == false ]]; then
    echo "  No analytics jobs configured"
    echo ""
fi

# Raw Processors
echo "📊 Raw Processors"
echo "================="
echo "Deploy with: ./bin/raw/deploy/deploy_processor_backfill_job.sh <job-name>"
echo ""

raw_found=false
while read -r config; do
    raw_found=true
    dir_name=$(dirname "$config" | sed 's|backfill_jobs/raw/||')
    echo "Job: $dir_name"
    get_job_details "$config"
done < <(find backfill_jobs/raw/ -name "job-config.env" 2>/dev/null | sort)

if [[ "$raw_found" == false ]]; then
    echo "  No raw jobs configured"
    echo ""
fi

echo "Deployment Utilities:"
echo "--------------------"
echo "  Check status: ./bin/utilities/deployment_status.sh"
echo "  List jobs: ./bin/utilities/list_deployable_jobs.sh"
echo ""

echo "Quick Shortcuts (from bin/shortcuts/):"
echo "--------------------------------------"
if [[ -d "bin/shortcuts" ]]; then
    ls -la bin/shortcuts/ | grep deploy | while read -r line; do
        shortcut=$(echo "$line" | awk '{print $9}')
        target=$(echo "$line" | awk '{print $11}')
        echo "  $shortcut -> $target"
    done
else
    echo "  No shortcuts directory found"
fi