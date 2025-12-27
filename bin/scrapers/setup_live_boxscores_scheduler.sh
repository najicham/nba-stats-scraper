#!/bin/bash
# Setup scheduler jobs for BDL Live Box Scores scraper
#
# These jobs trigger the Phase 1 scraper service every 3 minutes during
# game windows (7 PM - 1 AM ET) to collect live in-game player stats.
#
# Usage: ./bin/scrapers/setup_live_boxscores_scheduler.sh

set -e

PROJECT_ID="nba-props-platform"
REGION="us-west2"
SERVICE_ACCOUNT="scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com"
SCRAPER_URL="https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/scrape"

echo "Setting up BDL Live Box Scores scheduler jobs..."

# Delete existing jobs if they exist (for updates)
gcloud scheduler jobs delete bdl-live-boxscores-evening --location=$REGION --quiet 2>/dev/null || true
gcloud scheduler jobs delete bdl-live-boxscores-late --location=$REGION --quiet 2>/dev/null || true

# Create evening job (7 PM - 11:59 PM ET)
echo "Creating evening scheduler job..."
gcloud scheduler jobs create http bdl-live-boxscores-evening \
    --project=$PROJECT_ID \
    --location=$REGION \
    --schedule="*/3 19-23 * * *" \
    --time-zone="America/New_York" \
    --uri="$SCRAPER_URL" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body='{"scraper": "bdl_live_box_scores", "group": "gcs"}' \
    --oidc-service-account-email=$SERVICE_ACCOUNT \
    --oidc-token-audience="$SCRAPER_URL" \
    --attempt-deadline=120s \
    --description="BDL live box scores scraper during evening games (7-11:59 PM ET)"

# Create late-night job (12 AM - 1:59 AM ET)
echo "Creating late-night scheduler job..."
gcloud scheduler jobs create http bdl-live-boxscores-late \
    --project=$PROJECT_ID \
    --location=$REGION \
    --schedule="*/3 0-1 * * *" \
    --time-zone="America/New_York" \
    --uri="$SCRAPER_URL" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body='{"scraper": "bdl_live_box_scores", "group": "gcs"}' \
    --oidc-service-account-email=$SERVICE_ACCOUNT \
    --oidc-token-audience="$SCRAPER_URL" \
    --attempt-deadline=120s \
    --description="BDL live box scores scraper during late-night games (12-1:59 AM ET)"

echo ""
echo "Scheduler jobs created successfully!"
echo ""
echo "Verify with:"
echo "  gcloud scheduler jobs list --location=$REGION | grep bdl-live"
echo ""
echo "Test manually with:"
echo "  gcloud scheduler jobs run bdl-live-boxscores-evening --location=$REGION"
