#!/bin/bash
#
# Setup Evening Analytics Schedulers
#
# Creates Cloud Scheduler jobs to run Phase 3 analytics in the evening,
# catching games as they complete throughout the night.
#
# This fills the gap between:
# - Boxscore scraping (every 3 min during games)
# - Morning analytics (6 AM next day)
#
# Jobs created:
# 1. evening-analytics-6pm-et (Sat/Sun only) - Weekend matinees
# 2. evening-analytics-10pm-et (daily) - Early evening games
# 3. evening-analytics-1am-et (daily) - West Coast games
# 4. morning-analytics-catchup-9am-et (daily) - Catch anything missed
#
# Usage:
#   ./bin/orchestrators/setup_evening_analytics_schedulers.sh [--dry-run]
#
# Created: 2026-02-02 (Session 72)
#

set -e

# Configuration
PROJECT_ID="nba-props-platform"
REGION="us-west2"
TIMEZONE="America/New_York"
SERVICE_URL="https://nba-phase3-analytics-processors-756957797294.us-west2.run.app"
SERVICE_ACCOUNT="756957797294-compute@developer.gserviceaccount.com"

# Parse arguments
DRY_RUN=false
if [[ "$1" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "=== DRY RUN MODE ==="
fi

echo "=============================================="
echo "Setting up Evening Analytics Schedulers"
echo "=============================================="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Timezone: $TIMEZONE"
echo "Service URL: $SERVICE_URL"
echo ""

# Function to create or update a scheduler job
create_or_update_job() {
    local JOB_NAME=$1
    local SCHEDULE=$2
    local MESSAGE_BODY=$3
    local DESCRIPTION=$4

    echo "----------------------------------------------"
    echo "Job: $JOB_NAME"
    echo "Schedule: $SCHEDULE ($TIMEZONE)"
    echo "Description: $DESCRIPTION"
    echo ""

    if $DRY_RUN; then
        echo "[DRY RUN] Would create job with:"
        echo "  URI: $SERVICE_URL/process-date-range"
        echo "  Body: $MESSAGE_BODY"
        echo ""
        return
    fi

    # Check if job exists
    if gcloud scheduler jobs describe "$JOB_NAME" --location="$REGION" &>/dev/null; then
        echo "Job exists, updating..."
        gcloud scheduler jobs update http "$JOB_NAME" \
            --location="$REGION" \
            --schedule="$SCHEDULE" \
            --time-zone="$TIMEZONE" \
            --uri="$SERVICE_URL/process-date-range" \
            --http-method=POST \
            --headers="Content-Type=application/json" \
            --message-body="$MESSAGE_BODY" \
            --oidc-service-account-email="$SERVICE_ACCOUNT" \
            --description="$DESCRIPTION"
    else
        echo "Creating new job..."
        gcloud scheduler jobs create http "$JOB_NAME" \
            --location="$REGION" \
            --schedule="$SCHEDULE" \
            --time-zone="$TIMEZONE" \
            --uri="$SERVICE_URL/process-date-range" \
            --http-method=POST \
            --headers="Content-Type=application/json" \
            --message-body="$MESSAGE_BODY" \
            --oidc-service-account-email="$SERVICE_ACCOUNT" \
            --description="$DESCRIPTION"
    fi

    echo "Done: $JOB_NAME"
    echo ""
}

# Job 1: Weekend afternoon (catches 1 PM, 3:30 PM matinees)
# Runs at 6 PM ET on Saturday and Sunday only
create_or_update_job \
    "evening-analytics-6pm-et" \
    "0 18 * * 0,6" \
    '{"start_date":"TODAY","end_date":"TODAY","processors":["PlayerGameSummaryProcessor"],"backfill_mode":true}' \
    "Weekend afternoon analytics - catches matinee games (Sat/Sun 6 PM ET)"

# Job 2: Evening (catches 7 PM games)
# Runs at 10 PM ET daily
create_or_update_job \
    "evening-analytics-10pm-et" \
    "0 22 * * *" \
    '{"start_date":"TODAY","end_date":"TODAY","processors":["PlayerGameSummaryProcessor"],"backfill_mode":true}' \
    "Evening analytics - catches 7 PM games (Daily 10 PM ET)"

# Job 3: Late night (catches West Coast 10 PM games)
# Runs at 1 AM ET daily (processes YESTERDAY since it's after midnight)
create_or_update_job \
    "evening-analytics-1am-et" \
    "0 1 * * *" \
    '{"start_date":"YESTERDAY","end_date":"YESTERDAY","processors":["PlayerGameSummaryProcessor"],"backfill_mode":true}' \
    "Late night analytics - catches West Coast games (Daily 1 AM ET)"

# Job 4: Morning catchup (safety net)
# Runs at 9 AM ET daily to catch anything that was released late
create_or_update_job \
    "morning-analytics-catchup-9am-et" \
    "0 9 * * *" \
    '{"start_date":"YESTERDAY","end_date":"YESTERDAY","processors":["PlayerGameSummaryProcessor"],"backfill_mode":true}' \
    "Morning catchup analytics - catches late releases (Daily 9 AM ET)"

echo "=============================================="
echo "Setup Complete!"
echo "=============================================="
echo ""
echo "Jobs created/updated:"
echo "  1. evening-analytics-6pm-et     - Sat/Sun 6 PM ET (matinees)"
echo "  2. evening-analytics-10pm-et    - Daily 10 PM ET (7 PM games)"
echo "  3. evening-analytics-1am-et     - Daily 1 AM ET (West Coast)"
echo "  4. morning-analytics-catchup-9am-et - Daily 9 AM ET (safety net)"
echo ""
echo "Verify with:"
echo "  gcloud scheduler jobs list --location=$REGION | grep evening"
echo "  gcloud scheduler jobs list --location=$REGION | grep catchup"
echo ""
echo "To manually trigger a job:"
echo "  gcloud scheduler jobs run evening-analytics-10pm-et --location=$REGION"
echo ""
