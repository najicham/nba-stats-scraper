#!/bin/bash
# deploy_dknetwork_scheduler.sh
#
# Deploy daily Cloud Scheduler job for DraftKings Network betting splits.
# Free replacement for the paywalled VSiN source (dark since 2026-03-28).
# Runs once daily at 2 PM ET — pre-game window when public splits have formed.
#
# NOTE: the scraper URL hardcodes tb_edate=today, so this job MUST fire on the
# target game day (a same-day run). The `date: TODAY` payload only labels output.
#
# Usage:
#   ./bin/deploy/deploy_dknetwork_scheduler.sh
#   ./bin/deploy/deploy_dknetwork_scheduler.sh --dry-run
#
# Season-open checklist BEFORE trusting the data (see 2026-07-02-2 handoff):
#   1. Run manually on a real NBA game day and confirm game_count > 0.
#   2. Verify NBA tricodes parse correctly (matchup format is ASSUMED
#      "LAL Lakers @ BOS Celtics"; only MLB format was validated). Fix
#      resolve_team() in scrapers/external/dknetwork_betting_splits.py if wrong.
#   3. If 0 games / HTTP errors from Cloud Run, GCP egress IPs may be blocked →
#      set proxy_enabled=True in the scraper and redeploy nba-scrapers.

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
SCRAPERS_URL="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape"
SA_EMAIL="756957797294-compute@developer.gserviceaccount.com"
TIMEZONE="America/New_York"
JOB_NAME="dknetwork-betting-splits-daily"

DRY_RUN="false"
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN="true"
    echo "[DRY RUN] No resources will be created or modified."
fi

echo "========================================"
echo "DraftKings Network Betting Splits Scheduler"
echo "========================================"
echo "Project:  $PROJECT_ID"
echo "Region:   $REGION"
echo "Schedule: 0 14 * * * (2 PM ET daily)"
echo "Target:   $SCRAPERS_URL"
echo ""

BODY='{"scraper": "dknetwork_betting_splits", "date": "TODAY"}'

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
    --schedule="0 14 * * *" \
    --time-zone="$TIMEZONE" \
    --uri="$SCRAPERS_URL" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body="$BODY" \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --description="DraftKings Network NBA betting splits (2 PM ET daily) — free VSiN replacement" \
    --oidc-service-account-email="$SA_EMAIL" \
    --oidc-token-audience="$SCRAPERS_URL" \
    --attempt-deadline=300s

echo ""
echo "✅ Created: $JOB_NAME"
echo ""
echo "Verify:"
echo "  gcloud scheduler jobs list --location=$REGION --project=$PROJECT_ID | grep dknetwork"
echo ""
echo "Manual smoke test (run on a real NBA game day):"
echo "  gcloud scheduler jobs run $JOB_NAME --location=$REGION --project=$PROJECT_ID"
