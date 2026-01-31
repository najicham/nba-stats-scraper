#!/bin/bash
#
# Setup Cloud Scheduler Jobs for BDB Monitoring and Retry
#
# This script creates two Cloud Scheduler jobs:
# 1. BDB Critical Monitor - runs every 30 minutes
# 2. BDB Retry Processor - runs every hour
#
# Both jobs trigger Cloud Run services that execute the Python scripts.
#
# Usage:
#   ./bin/monitoring/setup_bdb_scheduler.sh [--dry-run]
#
# Created: Session 53 (2026-01-31)

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
DRY_RUN=false

# Parse arguments
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "DRY RUN MODE - No changes will be made"
fi

# Check if gcloud is authenticated
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
    echo "Error: Not authenticated with gcloud. Run 'gcloud auth login' first."
    exit 1
fi

echo "============================================================"
echo "BDB MONITORING SCHEDULER SETUP"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "============================================================"

# Function to create or update scheduler job
create_scheduler_job() {
    local job_name="$1"
    local schedule="$2"
    local description="$3"
    local script_path="$4"
    local timeout="$5"

    echo ""
    echo "Setting up job: $job_name"
    echo "  Schedule: $schedule"
    echo "  Script: $script_path"

    # Check if job already exists
    if gcloud scheduler jobs describe "$job_name" --location="$REGION" &>/dev/null; then
        echo "  Job already exists, will update"
        if [ "$DRY_RUN" = false ]; then
            gcloud scheduler jobs delete "$job_name" --location="$REGION" --quiet
        fi
    fi

    # Create the job
    # NOTE: We use App Engine Cron for simplicity
    # Alternative: Use Cloud Run Jobs or Pub/Sub triggers
    if [ "$DRY_RUN" = false ]; then
        gcloud scheduler jobs create http "$job_name" \
            --location="$REGION" \
            --schedule="$schedule" \
            --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/bdb-monitor:run" \
            --http-method=POST \
            --description="$description" \
            --time-zone="America/New_York" \
            --attempt-deadline="$timeout" \
            --max-retry-attempts=1

        echo "  ✅ Job created successfully"
    else
        echo "  [DRY-RUN] Would create job"
    fi
}

# Job 1: BDB Critical Monitor (every 30 minutes)
create_scheduler_job \
    "bdb-critical-monitor" \
    "*/30 * * * *" \
    "Monitor BigDataBall data availability and trigger retries" \
    "bin/monitoring/bdb_critical_monitor.py" \
    "300s"

# Job 2: BDB Retry Processor (every hour)
create_scheduler_job \
    "bdb-retry-processor" \
    "0 * * * *" \
    "Process pending BDB games and retry when data available" \
    "bin/monitoring/bdb_retry_processor.py" \
    "600s"

echo ""
echo "============================================================"
echo "SETUP COMPLETE"
echo "============================================================"
echo ""
echo "Next steps:"
echo "1. Verify jobs are created:"
echo "   gcloud scheduler jobs list --location=$REGION | grep bdb"
echo ""
echo "2. Test the monitor manually:"
echo "   gcloud scheduler jobs run bdb-critical-monitor --location=$REGION"
echo ""
echo "3. Check job logs:"
echo "   gcloud logging read 'resource.type=\"cloud_scheduler_job\" AND resource.labels.job_id=~\"bdb.*\"' --limit=20"
echo ""
