#!/bin/bash
# deploy_espn_injuries_scheduler.sh
#
# Deploy hourly Cloud Scheduler job for ESPN NBA injuries snapshots.
# Runs hourly 10 AM - 8 PM ET (year-round; off-season returns empty gracefully).
# Purpose: detect GTD→Out status flips in the pre-game window.
#
# Usage:
#   ./bin/deploy/deploy_espn_injuries_scheduler.sh
#   ./bin/deploy/deploy_espn_injuries_scheduler.sh --dry-run

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
SCRAPERS_URL="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape"
SA_EMAIL="756957797294-compute@developer.gserviceaccount.com"
TIMEZONE="America/New_York"
JOB_NAME="espn-injuries-hourly"

DRY_RUN="false"
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN="true"
    echo "[DRY RUN] No resources will be created or modified."
fi

echo "========================================"
echo "ESPN Injuries Hourly Scheduler"
echo "========================================"
echo "Project:  $PROJECT_ID"
echo "Region:   $REGION"
echo "Schedule: 0 10-20 * * * (10 AM – 8 PM ET, year-round)"
echo "Target:   $SCRAPERS_URL"
echo ""

BODY='{"scraper": "espn_injuries", "date": "TODAY"}'

if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN] Would create/update job: $JOB_NAME"
    echo "  Body: $BODY"
    exit 0
fi

# Delete existing job if present
if gcloud scheduler jobs describe "$JOB_NAME" \
    --project="$PROJECT_ID" --location="$REGION" &>/dev/null; then
    echo "Deleting existing job: $JOB_NAME"
    gcloud scheduler jobs delete "$JOB_NAME" \
        --project="$PROJECT_ID" --location="$REGION" --quiet
fi

gcloud scheduler jobs create http "$JOB_NAME" \
    --schedule="0 10-20 * * *" \
    --time-zone="$TIMEZONE" \
    --uri="$SCRAPERS_URL" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body="$BODY" \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --description="ESPN NBA injuries hourly snapshot (10 AM – 8 PM ET) for GTD→Out detection" \
    --oidc-service-account-email="$SA_EMAIL" \
    --oidc-token-audience="$SCRAPERS_URL" \
    --attempt-deadline=300s

echo ""
echo "✅ Created: $JOB_NAME"
echo ""
echo "Verify:"
echo "  gcloud scheduler jobs list --location=$REGION --project=$PROJECT_ID | grep espn"
echo ""
echo "Manual test:"
echo "  gcloud scheduler jobs run $JOB_NAME --location=$REGION --project=$PROJECT_ID"
