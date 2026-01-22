#!/bin/bash
# ============================================================================
# Deploy Scraper Catch-Up Cloud Scheduler Jobs
# ============================================================================
# Creates Cloud Scheduler jobs for extended retry windows to catch late data.
#
# Usage:
#   ./bin/deploy/deploy_catchup_schedulers.sh [--dry-run]
#
# Created: January 22, 2026
# ============================================================================

set -e

PROJECT_ID="${GCP_PROJECT:-nba-props-platform}"
REGION="${GCP_REGION:-us-west2}"
TIMEZONE="America/New_York"

# Discover Cloud Run service URLs dynamically
echo "Discovering Cloud Run service URLs..."

get_service_url() {
    local SERVICE_NAME=$1
    local URL=$(gcloud run services describe "$SERVICE_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --format='value(status.url)' 2>/dev/null)

    if [[ -z "$URL" ]]; then
        echo "ERROR: Could not find Cloud Run service: $SERVICE_NAME" >&2
        exit 1
    fi
    echo "$URL"
}

# Get the base URL for the phase1 scrapers service
PHASE1_BASE_URL=$(get_service_url "nba-phase1-scrapers")
echo "Found phase1 scrapers at: $PHASE1_BASE_URL"

# Catch-up controller endpoint
# The controller finds missing dates and invokes scrapers for each
CATCHUP_CONTROLLER_URL="${PHASE1_BASE_URL}/catchup"
echo "Catch-up controller at: $CATCHUP_CONTROLLER_URL"

# Parse args
DRY_RUN=false
if [[ "$1" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "🔍 DRY RUN MODE - No changes will be made"
fi

echo "=============================================="
echo "Deploying Scraper Catch-Up Scheduler Jobs"
echo "=============================================="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Timezone: $TIMEZONE"
echo ""

# Function to create or update a scheduler job for catch-up controller
create_catchup_job() {
    local JOB_NAME=$1
    local SCHEDULE=$2
    local SCRAPER_NAME=$3
    local DESCRIPTION=$4
    local LOOKBACK_DAYS=${5:-3}

    echo "📅 Creating job: $JOB_NAME"
    echo "   Schedule: $SCHEDULE ($TIMEZONE)"
    echo "   Scraper: $SCRAPER_NAME"
    echo "   Lookback: $LOOKBACK_DAYS days"

    if [[ "$DRY_RUN" == "true" ]]; then
        echo "   [DRY RUN] Would create job"
        return
    fi

    # Delete existing job if exists (ignore error if doesn't exist)
    gcloud scheduler jobs delete "$JOB_NAME" \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --quiet 2>/dev/null || true

    # Create new job
    # The catch-up controller finds missing dates and invokes the scraper for each
    gcloud scheduler jobs create http "$JOB_NAME" \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --schedule="$SCHEDULE" \
        --time-zone="$TIMEZONE" \
        --uri="$CATCHUP_CONTROLLER_URL" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body="{\"scraper_name\": \"$SCRAPER_NAME\", \"lookback_days\": $LOOKBACK_DAYS, \"workflow\": \"$JOB_NAME\"}" \
        --oidc-service-account-email="scheduler-invoker@${PROJECT_ID}.iam.gserviceaccount.com" \
        --description="$DESCRIPTION" \
        --attempt-deadline="1800s"

    echo "   ✅ Created successfully"
}

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "BDL Box Scores Catch-Up Jobs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# BDL Catch-Up: 10 AM ET
create_catchup_job \
    "bdl-catchup-midday" \
    "0 10 * * *" \
    "bdl_box_scores" \
    "BDL catch-up - 10 AM ET - Retry games missing BDL data from last 3 days" \
    3

# BDL Catch-Up: 2 PM ET
create_catchup_job \
    "bdl-catchup-afternoon" \
    "0 14 * * *" \
    "bdl_box_scores" \
    "BDL catch-up - 2 PM ET - Retry games missing BDL data from last 3 days" \
    3

# BDL Catch-Up: 6 PM ET
create_catchup_job \
    "bdl-catchup-evening" \
    "0 18 * * *" \
    "bdl_box_scores" \
    "BDL catch-up - 6 PM ET - Final daily retry for missing BDL data" \
    3

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "NBAC Gamebook PDF Catch-Up Jobs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# NBAC Gamebook: 8 AM ET
create_catchup_job \
    "gamebook-catchup-morning" \
    "0 8 * * *" \
    "nbac_gamebook_pdf" \
    "NBAC Gamebook catch-up - 8 AM ET - Retry games missing gamebook PDFs" \
    1

# NBAC Gamebook: 11 AM ET
create_catchup_job \
    "gamebook-catchup-late-morning" \
    "0 11 * * *" \
    "nbac_gamebook_pdf" \
    "NBAC Gamebook catch-up - 11 AM ET - Second retry for missing PDFs" \
    1

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Odds API Player Props Catch-Up Jobs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Odds API Props: 12 PM ET
create_catchup_job \
    "odds-catchup-noon" \
    "0 12 * * *" \
    "oddsa_player_props" \
    "Odds API catch-up - 12 PM ET - Retry for missing player props" \
    1

# Odds API Props: 3 PM ET
create_catchup_job \
    "odds-catchup-afternoon" \
    "0 15 * * *" \
    "oddsa_player_props" \
    "Odds API catch-up - 3 PM ET - Second retry for missing props" \
    1

# Odds API Props: 7 PM ET (before evening games)
create_catchup_job \
    "odds-catchup-evening" \
    "0 19 * * *" \
    "oddsa_player_props" \
    "Odds API catch-up - 7 PM ET - Final retry before games start" \
    1

echo ""
echo "=============================================="
echo "Summary"
echo "=============================================="
echo ""
echo "Created catch-up scheduler jobs:"
echo ""
echo "BDL Box Scores (3-day lookback):"
echo "  • bdl-catchup-midday      10:00 AM ET"
echo "  • bdl-catchup-afternoon   2:00 PM ET"
echo "  • bdl-catchup-evening     6:00 PM ET"
echo ""
echo "NBAC Gamebook PDF (1-day lookback):"
echo "  • gamebook-catchup-morning       8:00 AM ET"
echo "  • gamebook-catchup-late-morning  11:00 AM ET"
echo ""
echo "Odds API Player Props (1-day lookback):"
echo "  • odds-catchup-noon        12:00 PM ET"
echo "  • odds-catchup-afternoon   3:00 PM ET"
echo "  • odds-catchup-evening     7:00 PM ET"
echo ""

if [[ "$DRY_RUN" == "true" ]]; then
    echo "🔍 This was a DRY RUN - no jobs were created"
    echo "   Run without --dry-run to deploy"
else
    echo "✅ All scheduler jobs deployed successfully!"
    echo ""
    echo "Verify with:"
    echo "  gcloud scheduler jobs list --location=$REGION --project=$PROJECT_ID"
fi
