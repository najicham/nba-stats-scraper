#!/bin/bash
set -euo pipefail
# File: bin/utilities/deployment_status.sh
# Check status of all deployed Cloud Run jobs

PROJECT_ID="${PROJECT_ID:-nba-props-platform}"
REGION="${REGION:-us-west2}"

echo "NBA Props Platform - Deployment Status"
echo "======================================"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Date: $(date)"
echo ""

# Function to get job type from name
get_job_type() {
    local job_name="$1"
    case "$job_name" in
        *-reference-* | *-registry-* | *-player-*) echo "Reference" ;;
        *-analytics-* | *-summary-* | *-analysis-*) echo "Analytics" ;;
        *-raw-* | *-processor-* | *-scraper-*) echo "Raw" ;;
        *) echo "Other" ;;
    esac
}

# Get list of jobs with enhanced information
echo "Deployed Jobs:"
echo "--------------"

# Check if any jobs exist
if ! gcloud run jobs list --project="$PROJECT_ID" --region="$REGION" --format="value(metadata.name)" | head -1 >/dev/null 2>&1; then
    echo "No Cloud Run jobs found."
    echo ""
    echo "Available job configurations:"
    echo ""
    
    echo "Reference Jobs:"
    find backfill_jobs/reference/ -name "job-config.env" 2>/dev/null | sed 's|backfill_jobs/reference/||' | sed 's|/job-config.env||' | sed 's/^/  /' || echo "  None found"
    
    echo ""
    echo "Analytics Jobs:"
    find backfill_jobs/analytics/ -name "job-config.env" 2>/dev/null | sed 's|backfill_jobs/analytics/||' | sed 's|/job-config.env||' | sed 's/^/  /' || echo "  None found"
    
    echo ""
    echo "Raw Jobs:"
    find backfill_jobs/raw/ -name "job-config.env" 2>/dev/null | sed 's|backfill_jobs/raw/||' | sed 's|/job-config.env||' | sed 's/^/  /' || echo "  None found"
    
    echo ""
    echo "To deploy jobs, use:"
    echo "  ./bin/reference/deploy/deploy_reference_processor_backfill.sh <job-name>"
    echo "  ./bin/analytics/deploy/deploy_analytics_processor_backfill.sh <job-name>"
    echo "  ./bin/raw/deploy/deploy_processor_backfill_job.sh <job-name>"
    exit 0
fi

# List jobs with type and status
while read -r job_name; do
    job_type=$(get_job_type "$job_name")
    
    # Get last execution info
    last_execution=$(gcloud run jobs executions list \
        --job="$job_name" \
        --project="$PROJECT_ID" \
        --region="$REGION" \
        --limit=1 \
        --format="value(metadata.name,metadata.creationTimestamp,status.succeeded)" 2>/dev/null | head -1)
    
    if [[ -n "$last_execution" ]]; then
        IFS=$'\t' read -r exec_name exec_time exec_success <<< "$last_execution"
        if [[ "$exec_success" == "True" ]]; then
            status="✅ Last Success: $(date -d "$exec_time" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "$exec_time")"
        elif [[ "$exec_success" == "False" ]]; then
            status="❌ Last Failure: $(date -d "$exec_time" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "$exec_time")"
        else
            status="🟡 Running: $(date -d "$exec_time" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "$exec_time")"
        fi
    else
        status="⚪ Never executed"
    fi
    
    printf "%-12s %-40s %s\n" "[$job_type]" "$job_name" "$status"
    
done < <(gcloud run jobs list --project="$PROJECT_ID" --region="$REGION" --format="value(metadata.name)" | sort)

echo ""
echo "Recent Activity (Last 5 executions):"
echo "-----------------------------------"

gcloud run jobs executions list \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --limit=5 \
    --format="table(
        spec.jobName:label='JOB',
        metadata.name:label='EXECUTION_ID',
        metadata.creationTimestamp:label='STARTED',
        status.completionTimestamp:label='COMPLETED',
        status.succeeded:label='SUCCESS'
    )" 2>/dev/null || echo "No recent executions found"

echo ""
echo "Management Commands:"
echo "-------------------"
echo "  Monitor specific job: gcloud beta run jobs executions logs read <execution-id> --region=$REGION"
echo "  Execute job: gcloud run jobs execute <job-name> --region=$REGION"
echo "  Delete job: gcloud run jobs delete <job-name> --region=$REGION"
echo ""
echo "Quick shortcuts available in bin/shortcuts/:"
ls -la bin/shortcuts/ | grep deploy | awk '{print "  " $9 " -> " $11}'