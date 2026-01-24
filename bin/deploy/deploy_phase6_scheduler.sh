#!/bin/bash
# deploy_phase6_scheduler.sh
#
# Deploy Phase 6 Publishing scheduler jobs.
# These jobs trigger daily exports of prediction data to GCS.
#
# Usage:
#   ./bin/deploy/deploy_phase6_scheduler.sh          # Create all scheduler jobs
#   ./bin/deploy/deploy_phase6_scheduler.sh --dry-run  # Show what would be created
#   ./bin/deploy/deploy_phase6_scheduler.sh --delete   # Delete existing jobs
#
# Prerequisites:
# - gcloud CLI authenticated
# - GCP project set to nba-props-platform
#
# See config/phase6_publishing.yaml for job definitions

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
TOPIC="nba-phase6-export-trigger"
DRY_RUN=false
DELETE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --delete)
            DELETE=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "============================================"
echo "Phase 6 Publishing Scheduler Deployment"
echo "============================================"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Dry Run: $DRY_RUN"
echo "Delete: $DELETE"
echo ""

# ─────────────────────────────────────────────────────────
# Function: Create Pub/Sub topic if it doesn't exist
# ─────────────────────────────────────────────────────────
create_topic() {
    echo "Checking Pub/Sub topic: $TOPIC"

    if $DRY_RUN; then
        echo "[DRY RUN] Would create topic: $TOPIC"
        return
    fi

    if ! gcloud pubsub topics describe $TOPIC --project=$PROJECT_ID >/dev/null 2>&1; then
        echo "Creating topic: $TOPIC"
        gcloud pubsub topics create $TOPIC --project=$PROJECT_ID
    else
        echo "Topic already exists: $TOPIC"
    fi
}

# ─────────────────────────────────────────────────────────
# Function: Create or update a scheduler job
# ─────────────────────────────────────────────────────────
create_job() {
    local JOB_NAME=$1
    local SCHEDULE=$2
    local MESSAGE=$3
    local DESCRIPTION=$4

    echo ""
    echo "Job: $JOB_NAME"
    echo "  Schedule: $SCHEDULE"
    echo "  Message: $MESSAGE"
    echo "  Description: $DESCRIPTION"

    if $DRY_RUN; then
        echo "[DRY RUN] Would create scheduler job: $JOB_NAME"
        return
    fi

    # Delete existing job if it exists
    if gcloud scheduler jobs describe $JOB_NAME --location=$REGION --project=$PROJECT_ID >/dev/null 2>&1; then
        echo "  Deleting existing job: $JOB_NAME"
        gcloud scheduler jobs delete $JOB_NAME \
            --location=$REGION \
            --project=$PROJECT_ID \
            --quiet
    fi

    echo "  Creating job: $JOB_NAME"
    gcloud scheduler jobs create pubsub $JOB_NAME \
        --location=$REGION \
        --project=$PROJECT_ID \
        --schedule="$SCHEDULE" \
        --topic=$TOPIC \
        --message-body="$MESSAGE" \
        --time-zone="America/New_York" \
        --description="$DESCRIPTION"

    echo "  ✓ Created: $JOB_NAME"
}

# ─────────────────────────────────────────────────────────
# Function: Delete a scheduler job
# ─────────────────────────────────────────────────────────
delete_job() {
    local JOB_NAME=$1

    if $DRY_RUN; then
        echo "[DRY RUN] Would delete job: $JOB_NAME"
        return
    fi

    if gcloud scheduler jobs describe $JOB_NAME --location=$REGION --project=$PROJECT_ID >/dev/null 2>&1; then
        echo "Deleting job: $JOB_NAME"
        gcloud scheduler jobs delete $JOB_NAME \
            --location=$REGION \
            --project=$PROJECT_ID \
            --quiet
        echo "  ✓ Deleted: $JOB_NAME"
    else
        echo "Job not found: $JOB_NAME (skipping)"
    fi
}

# ─────────────────────────────────────────────────────────
# DELETE MODE
# ─────────────────────────────────────────────────────────
if $DELETE; then
    echo "Deleting Phase 6 scheduler jobs..."
    delete_job "phase6-daily-results"
    delete_job "phase6-tonight-picks"
    delete_job "phase6-player-profiles"
    delete_job "phase6-hourly-trends"
    echo ""
    echo "Done! All Phase 6 scheduler jobs deleted."
    exit 0
fi

# ─────────────────────────────────────────────────────────
# CREATE MODE
# ─────────────────────────────────────────────────────────
echo "Creating Phase 6 scheduler jobs..."

# Create topic first
create_topic

# Job 1: Daily Results Export
# Runs at 5 AM ET (10:00 UTC) after overnight games complete
create_job "phase6-daily-results" \
    "0 5 * * *" \
    '{"export_types": ["results", "performance", "best-bets", "predictions"], "target_date": "yesterday", "update_latest": true}' \
    "Export yesterday's prediction results to GCS (5 AM ET)"

# Job 2: Tonight's Picks Export
# Runs at 1 PM ET (18:00 UTC) after predictions run
create_job "phase6-tonight-picks" \
    "0 13 * * *" \
    '{"export_types": ["tonight", "tonight-players"], "target_date": "today"}' \
    "Export tonight's players and predictions (1 PM ET)"

# Job 3: Weekly Player Profiles
# Runs Sundays at 6 AM ET
create_job "phase6-player-profiles" \
    "0 6 * * 0" \
    '{"players": true, "min_games": 5}' \
    "Weekly refresh of player profiles (Sundays 6 AM ET)"

# Job 4: Hourly Trends Export
# Runs hourly 6 AM - 2 AM ET (covers game times)
# Includes: who's hot/cold, bounce-back watch, tonight's trend plays
create_job "phase6-hourly-trends" \
    "0 6-23 * * *" \
    '{"export_types": ["trends-hot-cold", "trends-bounce-back", "tonight-trend-plays"], "target_date": "today"}' \
    "Hourly trends refresh for Trends page (6 AM - 11 PM ET)"

echo ""
echo "============================================"
echo "Deployment Complete!"
echo "============================================"
echo ""
echo "Created scheduler jobs:"
echo "  - phase6-daily-results    (5 AM ET daily)"
echo "  - phase6-tonight-picks    (1 PM ET daily)"
echo "  - phase6-player-profiles  (6 AM ET Sundays)"
echo "  - phase6-hourly-trends    (6 AM - 11 PM ET hourly)"
echo ""
echo "To test manually:"
echo "  gcloud scheduler jobs run phase6-daily-results --location=$REGION"
echo ""
echo "To view jobs:"
echo "  gcloud scheduler jobs list --location=$REGION --project=$PROJECT_ID"
echo ""
echo "NOTE: A Cloud Function is needed to receive these messages."
echo "See: orchestration/cloud_functions/phase6_export/main.py"
echo ""
