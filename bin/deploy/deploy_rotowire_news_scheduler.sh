#!/bin/bash
# deploy_rotowire_news_scheduler.sh
#
# Deploy Cloud Scheduler jobs for RotoWire NBA news scraping.
# RSS feed returns only ~5 most-recent items, so scraping must be frequent
# to avoid items rotating off between runs.
#
# Schedule: every 10 minutes on game days (10 AM – 10 PM ET, Oct–Apr)
# Also creates a lightweight off-season daily job (noon ET, May–Sep) to
# keep the data clock alive and catch any off-season news.
#
# Usage:
#   ./bin/deploy/deploy_rotowire_news_scheduler.sh
#   ./bin/deploy/deploy_rotowire_news_scheduler.sh --dry-run

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
SCRAPERS_URL="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape"
SA_EMAIL="756957797294-compute@developer.gserviceaccount.com"
TIMEZONE="America/New_York"
JOB_NAME="rotowire-nba-news-frequent"
JOB_NAME_OFFSEASON="rotowire-nba-news-daily"

DRY_RUN="false"
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN="true"
    echo "[DRY RUN] No resources will be created or modified."
fi

echo "========================================"
echo "RotoWire NBA News Schedulers"
echo "========================================"
echo "Project:  $PROJECT_ID"
echo "Region:   $REGION"
echo "Target:   $SCRAPERS_URL"
echo ""
echo "Jobs to create:"
echo "  $JOB_NAME       — every 10 min, 10 AM-10 PM ET, Oct-Apr (game season)"
echo "  $JOB_NAME_OFFSEASON — daily noon ET, May-Sep (off-season)"
echo ""

BODY='{"scraper": "rotowire_nba_news", "date": "TODAY"}'

create_job() {
    local name="$1"
    local schedule="$2"
    local description="$3"

    echo "--- $name ---"
    echo "  Schedule: $schedule ($TIMEZONE)"
    echo "  Body:     $BODY"

    if [[ "$DRY_RUN" == "true" ]]; then
        echo "  [DRY RUN] Would create/update: $name"
        echo ""
        return
    fi

    # Delete existing job if present
    if gcloud scheduler jobs describe "$name" \
        --project="$PROJECT_ID" --location="$REGION" &>/dev/null; then
        echo "  Deleting existing job..."
        gcloud scheduler jobs delete "$name" \
            --project="$PROJECT_ID" --location="$REGION" --quiet
    fi

    gcloud scheduler jobs create http "$name" \
        --schedule="$schedule" \
        --time-zone="$TIMEZONE" \
        --uri="$SCRAPERS_URL" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body="$BODY" \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --description="$description" \
        --oidc-service-account-email="$SA_EMAIL" \
        --oidc-token-audience="$SCRAPERS_URL" \
        --attempt-deadline=60s

    echo "  Created: $name"
    echo ""
}

# Game season: every 10 min, 10 AM - 10 PM ET, October through April
# Cron: */10 10-22 * 10-12,1-4 * (Oct-Dec + Jan-Apr)
# Note: cron month ranges don't wrap Dec→Jan, so use two separate jobs
# or run year-round (off-season scraper returns gracefully with 0 items).
# Simplest: run year-round at 10-min cadence during 10 AM-10 PM window.
create_job \
    "$JOB_NAME" \
    "*/10 10-22 * * *" \
    "RotoWire NBA news scraper — every 10 min, 10 AM-10 PM ET (year-round; off-season returns empty)"

# Off-season daily backup at noon — lower frequency when no games
create_job \
    "$JOB_NAME_OFFSEASON" \
    "0 12 * 5-9 *" \
    "RotoWire NBA news scraper — daily noon ET during off-season (May-Sep)"

echo "========================================"
echo "Done."
echo ""
echo "Verify:"
echo "  gcloud scheduler jobs list --location=$REGION --project=$PROJECT_ID | grep rotowire"
echo ""
echo "Manual test:"
echo "  gcloud scheduler jobs run $JOB_NAME --location=$REGION --project=$PROJECT_ID"
