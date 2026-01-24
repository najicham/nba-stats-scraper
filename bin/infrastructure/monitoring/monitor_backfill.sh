#!/bin/bash
set -euo pipefail
# File: bin/monitoring/monitor_backfill.sh
# Purpose: Comprehensive monitoring for NBA gamebook backfill process
# Usage: ./monitor_backfill.sh [--continuous] [--interval=60]

# NBA Gamebook Backfill Monitor

PROJECT="nba-props-platform"
REGION="us-west2"
JOB_NAME="nba-gamebook-backfill"
BUCKET="gs://nba-scraped-data"
CONTINUOUS=false
INTERVAL=60

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --continuous)
      CONTINUOUS=true
      shift
      ;;
    --interval=*)
      INTERVAL="${1#*=}"
      shift
      ;;
    *)
      echo "Unknown option $1"
      exit 1
      ;;
  esac
done

check_job_status() {
    echo "🔍 $(date): Checking Cloud Run Job Status..."
    
    # Get job executions
    local executions=$(gcloud run jobs executions list \
        --job=$JOB_NAME \
        --region=$REGION \
        --format="table(metadata.name,status.conditions[0].type,status.completionTime,metadata.creationTimestamp)" \
        --limit=3 2>/dev/null)
    
    if [[ $? -eq 0 && -n "$executions" ]]; then
        echo "$executions"
        
        # Get most recent execution name
        local latest_execution=$(gcloud run jobs executions list \
            --job=$JOB_NAME \
            --region=$REGION \
            --format="value(metadata.name)" \
            --limit=1 2>/dev/null)
        
        if [[ -n "$latest_execution" ]]; then
            echo "📊 Latest Execution: $latest_execution"
            
            # Check if running
            local status=$(gcloud run jobs executions describe $latest_execution \
                --region=$REGION \
                --format="value(status.conditions[0].type)" 2>/dev/null)
            
            echo "Status: $status"
            
            if [[ "$status" == "Running" ]]; then
                echo "✅ Job is currently running"
                return 0
            elif [[ "$status" == "Complete" ]]; then
                echo "✅ Job completed successfully"
                return 1
            else
                echo "⚠️  Job status: $status"
                return 2
            fi
        fi
    else
        echo "❌ No job executions found"
        return 3
    fi
}

check_logs() {
    echo "📄 Recent Job Logs (last 10 lines):"
    gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME" \
        --limit=10 \
        --format="table(timestamp,severity,textPayload)" \
        --project=$PROJECT 2>/dev/null || echo "❌ No logs found"
    echo
}

check_gcs_progress() {
    echo "📁 GCS Progress Check:"
    
    # Count recent gamebook files
    local today=$(date +%Y-%m-%d)
    local yesterday=$(date -d "yesterday" +%Y-%m-%d)
    
    echo "Files created today ($today):"
    local today_count=$(gsutil ls -r "$BUCKET/nba-com/gamebooks-data/$today/" 2>/dev/null | grep "\.json$" | wc -l)
    echo "  JSON files: $today_count"
    
    echo "Files created yesterday ($yesterday):"
    local yesterday_count=$(gsutil ls -r "$BUCKET/nba-com/gamebooks-data/$yesterday/" 2>/dev/null | grep "\.json$" | wc -l)
    echo "  JSON files: $yesterday_count"
    
    # Check for recent activity (last hour)
    echo "Recent file activity (last hour):"
    gsutil ls -l -r "$BUCKET/nba-com/gamebooks-data/" 2>/dev/null | \
        awk -v cutoff="$(date -d '1 hour ago' +%s)" '
        /\.json$/ {
            # Parse timestamp
            split($2, date_parts, "-")
            split($3, time_parts, ":")
            timestamp = mktime(date_parts[1] " " substr(date_parts[2],1,2) " " substr(date_parts[2],4,5) " " time_parts[1] " " time_parts[2] " " time_parts[3])
            if (timestamp > cutoff) {
                print "  " $4
            }
        }' | head -10
    echo
}

check_error_patterns() {
    echo "🚨 Error Pattern Check:"
    
    # Check for common error patterns in logs
    local error_logs=$(gcloud logging read \
        "resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME AND severity>=ERROR" \
        --limit=5 \
        --format="value(textPayload)" \
        --project=$PROJECT 2>/dev/null)
    
    if [[ -n "$error_logs" ]]; then
        echo "Recent errors found:"
        echo "$error_logs"
    else
        echo "✅ No recent errors found"
    fi
    echo
}

estimate_completion() {
    echo "⏱️  Progress Estimation:"
    
    # Count total JSON files
    local total_files=$(gsutil ls -r "$BUCKET/nba-com/gamebooks-data/" 2>/dev/null | grep "\.json$" | wc -l)
    local target_files=5581
    
    echo "Current progress: $total_files / $target_files files"
    
    if [[ $total_files -gt 0 ]]; then
        local progress_percent=$((total_files * 100 / target_files))
        local remaining=$((target_files - total_files))
        echo "Progress: ${progress_percent}%"
        echo "Remaining: $remaining files"
        
        # Estimate completion time (assuming 4 seconds per file)
        local remaining_seconds=$((remaining * 4))
        local remaining_hours=$((remaining_seconds / 3600))
        local remaining_minutes=$(((remaining_seconds % 3600) / 60))
        
        if [[ $remaining_hours -gt 0 ]]; then
            echo "Estimated time remaining: ${remaining_hours}h ${remaining_minutes}m"
        else
            echo "Estimated time remaining: ${remaining_minutes}m"
        fi
    fi
    echo
}

validate_recent_files() {
    echo "✅ Recent File Validation:"
    
    # Get 3 most recent files and validate them
    local recent_files=$(gsutil ls -r "$BUCKET/nba-com/gamebooks-data/" 2>/dev/null | \
        grep "\.json$" | tail -3)
    
    if [[ -n "$recent_files" ]]; then
        echo "Checking last 3 files:"
        echo "$recent_files" | while IFS= read -r file; do
            # Extract game code from path
            local game_code=$(echo "$file" | sed -n 's/.*game_\([0-9]*_[A-Z]*\).*/\1/p' | sed 's/_/\//')
            if [[ -n "$game_code" ]]; then
                echo "  📄 $game_code - $(gsutil ls -l "$file" 2>/dev/null | awk '{print $1}')"
            fi
        done
    else
        echo "❌ No recent files found"
    fi
    echo
}

run_single_check() {
    echo "===================="
    echo "NBA GAMEBOOK BACKFILL MONITOR"
    echo "Time: $(date)"
    echo "===================="
    
    check_job_status
    job_status=$?
    
    check_gcs_progress
    estimate_completion
    check_error_patterns
    validate_recent_files
    check_logs
    
    echo "===================="
    
    return $job_status
}

# Main execution
if [[ "$CONTINUOUS" == true ]]; then
    echo "Starting continuous monitoring (interval: ${INTERVAL}s)"
    echo "Press Ctrl+C to stop"
    
    while true; do
        run_single_check
        job_status=$?
        
        if [[ $job_status -eq 1 ]]; then
            echo "🎉 Job completed successfully!"
            break
        elif [[ $job_status -eq 3 ]]; then
            echo "⚠️  No job found - may need to start the job"
        fi
        
        echo "Waiting ${INTERVAL} seconds..."
        sleep $INTERVAL
        clear
    done
else
    run_single_check
fi