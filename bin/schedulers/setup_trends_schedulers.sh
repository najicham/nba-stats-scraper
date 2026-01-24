#!/bin/bash
# setup_trends_schedulers.sh
#
# Deploy Cloud Scheduler jobs for Trends v2 exporters.
# These jobs trigger exports of trend analytics to power the Trends v2 page.
#
# Usage:
#   ./bin/schedulers/setup_trends_schedulers.sh              # Create all scheduler jobs
#   ./bin/schedulers/setup_trends_schedulers.sh --dry-run    # Show what would be created
#   ./bin/schedulers/setup_trends_schedulers.sh --delete     # Delete existing jobs
#
# Prerequisites:
# - gcloud CLI authenticated
# - GCP project set to nba-props-platform
# - Phase 6 export infrastructure deployed (Pub/Sub topic, Cloud Function)
#
# Trends v2 Exporters:
# - hot-cold: Who's Hot/Cold (hit rate + streak analysis)
# - bounce-back: Bounce-Back Watch (players due for regression)
# - what-matters: What Matters Most (factors that impact betting success)
# - team-tendencies: Team Tendencies (defensive matchups, pace)
# - quick-hits: Quick Hits (bite-sized insights)
# - deep-dive: Deep Dive Promo (monthly featured content)

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-central1"
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
            echo "Usage: $0 [--dry-run] [--delete]"
            exit 1
            ;;
    esac
done

echo "============================================"
echo "Trends v2 Scheduler Deployment"
echo "============================================"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Pub/Sub Topic: $TOPIC"
echo "Dry Run: $DRY_RUN"
echo "Delete: $DELETE"
echo ""

# ─────────────────────────────────────────────────────────
# Function: Verify Pub/Sub topic exists
# ─────────────────────────────────────────────────────────
verify_topic() {
    echo "Verifying Pub/Sub topic: $TOPIC"

    if $DRY_RUN; then
        echo "[DRY RUN] Would verify topic exists: $TOPIC"
        return
    fi

    if ! gcloud pubsub topics describe $TOPIC --project=$PROJECT_ID >/dev/null 2>&1; then
        echo "ERROR: Topic $TOPIC does not exist!"
        echo ""
        echo "Please deploy Phase 6 export infrastructure first:"
        echo "  ./bin/deploy/deploy_phase6_scheduler.sh"
        echo ""
        exit 1
    else
        echo "✓ Topic exists: $TOPIC"
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
    echo "  Description: $DESCRIPTION"

    if $DRY_RUN; then
        echo "  [DRY RUN] Would create scheduler job"
        echo "  Message: $MESSAGE"
        return
    fi

    # Delete existing job if it exists
    if gcloud scheduler jobs describe $JOB_NAME --location=$REGION --project=$PROJECT_ID >/dev/null 2>&1; then
        echo "  Deleting existing job..."
        gcloud scheduler jobs delete $JOB_NAME \
            --location=$REGION \
            --project=$PROJECT_ID \
            --quiet
    fi

    echo "  Creating job..."
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
    echo "Deleting Trends v2 scheduler jobs..."
    echo ""
    delete_job "trends-daily"
    delete_job "trends-weekly-mon"
    delete_job "trends-weekly-wed"
    delete_job "trends-monthly"
    echo ""
    echo "Done! All Trends v2 scheduler jobs deleted."
    exit 0
fi

# ─────────────────────────────────────────────────────────
# CREATE MODE
# ─────────────────────────────────────────────────────────
echo "Creating Trends v2 scheduler jobs..."
echo ""

# Verify topic exists before creating jobs
verify_topic

# ─────────────────────────────────────────────────────────
# Job 1: Daily Trends (6 AM ET)
# ─────────────────────────────────────────────────────────
# Exporters: hot-cold, bounce-back
# Schedule: Daily at 6 AM ET (11:00 UTC)
# Purpose: Refresh player hot/cold streaks and bounce-back candidates
# Cron: 0 6 * * * = Every day at 6:00 AM
create_job "trends-daily" \
    "0 6 * * *" \
    '{"export_types": ["trends-hot-cold", "trends-bounce-back"], "target_date": "today", "update_latest": true}' \
    "Trends v2: Daily hot-cold and bounce-back exports (6 AM ET)"

# ─────────────────────────────────────────────────────────
# Job 2: Weekly Monday Trends (6 AM ET)
# ─────────────────────────────────────────────────────────
# Exporters: what-matters, team-tendencies
# Schedule: Every Monday at 6 AM ET (11:00 UTC)
# Purpose: Refresh weekly analysis of betting factors and team defense
# Cron: 0 6 * * 1 = Every Monday at 6:00 AM
create_job "trends-weekly-mon" \
    "0 6 * * 1" \
    '{"export_types": ["trends-what-matters", "trends-team"], "target_date": "today"}' \
    "Trends v2: Weekly what-matters and team-tendencies (Mondays 6 AM ET)"

# ─────────────────────────────────────────────────────────
# Job 3: Weekly Wednesday Trends (8 AM ET)
# ─────────────────────────────────────────────────────────
# Exporters: quick-hits
# Schedule: Every Wednesday at 8 AM ET (13:00 UTC)
# Purpose: Refresh mid-week quick hits and bite-sized insights
# Cron: 0 8 * * 3 = Every Wednesday at 8:00 AM
create_job "trends-weekly-wed" \
    "0 8 * * 3" \
    '{"export_types": ["trends-quick-hits"], "target_date": "today"}' \
    "Trends v2: Weekly quick-hits insights (Wednesdays 8 AM ET)"

# ─────────────────────────────────────────────────────────
# Job 4: Monthly Deep Dive (1st of month, 6 AM ET)
# ─────────────────────────────────────────────────────────
# Exporters: deep-dive
# Schedule: 1st day of each month at 6 AM ET (11:00 UTC)
# Purpose: Refresh monthly featured deep-dive analysis
# Cron: 0 6 1 * * = 1st of every month at 6:00 AM
create_job "trends-monthly" \
    "0 6 1 * *" \
    '{"export_types": ["trends-deep-dive"], "target_date": "today"}' \
    "Trends v2: Monthly deep-dive promo content (1st of month, 6 AM ET)"

echo ""
echo "============================================"
echo "Deployment Complete!"
echo "============================================"
echo ""
echo "Created Trends v2 scheduler jobs:"
echo ""
echo "  1. trends-daily (Daily 6 AM ET)"
echo "     - Who's Hot/Cold (trends-hot-cold)"
echo "     - Bounce-Back Watch (trends-bounce-back)"
echo ""
echo "  2. trends-weekly-mon (Mondays 6 AM ET)"
echo "     - What Matters Most (trends-what-matters)"
echo "     - Team Tendencies (trends-team)"
echo ""
echo "  3. trends-weekly-wed (Wednesdays 8 AM ET)"
echo "     - Quick Hits (trends-quick-hits)"
echo ""
echo "  4. trends-monthly (1st of month, 6 AM ET)"
echo "     - Deep Dive Promo (trends-deep-dive)"
echo ""
echo "============================================"
echo "Next Steps"
echo "============================================"
echo ""
echo "View all scheduler jobs:"
echo "  gcloud scheduler jobs list --location=$REGION --project=$PROJECT_ID"
echo ""
echo "View Trends v2 jobs specifically:"
echo "  gcloud scheduler jobs list --location=$REGION --filter='name:trends-' --project=$PROJECT_ID"
echo ""
echo "Test a job manually:"
echo "  gcloud scheduler jobs run trends-daily --location=$REGION"
echo ""
echo "Monitor exports:"
echo "  gsutil ls gs://nba-props-platform-api/v1/trends/"
echo ""
echo "Check Cloud Function logs:"
echo "  gcloud functions logs read phase6-export-function --region=$REGION --limit=50"
echo ""
echo "Pause a job:"
echo "  gcloud scheduler jobs pause trends-daily --location=$REGION"
echo ""
echo "Resume a job:"
echo "  gcloud scheduler jobs resume trends-daily --location=$REGION"
echo ""
