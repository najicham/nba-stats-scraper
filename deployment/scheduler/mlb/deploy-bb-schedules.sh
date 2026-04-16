#!/bin/bash
set -e

# MLB Best Bets Scheduler Deploy Script
# Manages the 3 Cloud Scheduler jobs that drive the MLB best bets pipeline:
#   1. mlb-best-bets-generate   — HTTP POST to /best-bets at 12:55 PM ET (creates picks)
#   2. mlb-pitcher-export-morning — Pub/Sub export at 10:45 AM ET (post-grading refresh)
#   3. mlb-pitcher-export-pregame — Pub/Sub export at 1:00 PM ET (pregame publish)
#
# Session 534: mlb-pitcher-export-* jobs updated to include "best-bets" in export_types.
#
# Usage:
#   ./deploy-bb-schedules.sh           # Create/update all 3 jobs
#   ./deploy-bb-schedules.sh --dry-run # Echo commands without executing

PROJECT="nba-props-platform"
LOCATION="us-west2"
SA="756957797294-compute@developer.gserviceaccount.com"
MLB_WORKER_URL="https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app"
PHASE6_TOPIC="projects/${PROJECT}/topics/nba-phase6-export-trigger"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo -e "${YELLOW}[DRY RUN] Commands will be echoed but not executed.${NC}"
fi

run() {
    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}[DRY RUN]${NC} $*"
    else
        echo -e "${GREEN}[RUN]${NC} $*"
        "$@"
    fi
}

echo ""
echo "MLB Best Bets Scheduler Deploy"
echo "Project:  $PROJECT"
echo "Location: $LOCATION"
echo "SA:       $SA"
echo ""

# ---------------------------------------------------------------------------
# 1. mlb-best-bets-generate — HTTP job with OIDC auth
#    Creates signal_best_bets_picks rows. Must run BEFORE mlb-pitcher-export-pregame.
# ---------------------------------------------------------------------------
echo "--- 1/3: mlb-best-bets-generate (HTTP) ---"

# Check if job exists; create or update accordingly
if gcloud scheduler jobs describe mlb-best-bets-generate \
       --project="$PROJECT" --location="$LOCATION" &>/dev/null; then
    echo "  Job exists — updating."
    run gcloud scheduler jobs update http mlb-best-bets-generate \
        --project="$PROJECT" \
        --location="$LOCATION" \
        --schedule="55 12 * 3-10 *" \
        --time-zone="America/New_York" \
        --description="Generate MLB best bets picks. Hits /best-bets on MLB worker to write signal_best_bets_picks before pregame publisher runs at 1 PM ET." \
        --uri="${MLB_WORKER_URL}/best-bets" \
        --http-method=POST \
        --message-body='{"game_date": "TODAY"}' \
        --headers="Content-Type=application/json" \
        --oidc-service-account-email="$SA" \
        --attempt-deadline=180s
else
    echo "  Job does not exist — creating."
    run gcloud scheduler jobs create http mlb-best-bets-generate \
        --project="$PROJECT" \
        --location="$LOCATION" \
        --schedule="55 12 * 3-10 *" \
        --time-zone="America/New_York" \
        --description="Generate MLB best bets picks. Hits /best-bets on MLB worker to write signal_best_bets_picks before pregame publisher runs at 1 PM ET." \
        --uri="${MLB_WORKER_URL}/best-bets" \
        --http-method=POST \
        --message-body='{"game_date": "TODAY"}' \
        --headers="Content-Type=application/json" \
        --oidc-service-account-email="$SA" \
        --attempt-deadline=180s
fi

echo ""

# ---------------------------------------------------------------------------
# 2. mlb-pitcher-export-morning — Pub/Sub job (10:45 AM ET)
#    Post-grading pitcher track record refresh. Session 534: added "best-bets".
# ---------------------------------------------------------------------------
echo "--- 2/3: mlb-pitcher-export-morning (Pub/Sub update) ---"
echo "  NOTE: Updating payload to include 'best-bets' in export_types (Session 534)."

run gcloud scheduler jobs update pubsub mlb-pitcher-export-morning \
    --project="$PROJECT" \
    --location="$LOCATION" \
    --schedule="45 10 * 3-10 *" \
    --time-zone="America/New_York" \
    --topic="$PHASE6_TOPIC" \
    --message-body='{"sport":"mlb","export_types":["pitchers","best-bets"],"target_date":"today"}'

echo ""

# ---------------------------------------------------------------------------
# 3. mlb-pitcher-export-pregame — Pub/Sub job (1:00 PM ET)
#    Pregame pitcher + best-bets publish. Session 534: added "best-bets".
# ---------------------------------------------------------------------------
echo "--- 3/3: mlb-pitcher-export-pregame (Pub/Sub update) ---"
echo "  NOTE: Updating payload to include 'best-bets' in export_types (Session 534)."

run gcloud scheduler jobs update pubsub mlb-pitcher-export-pregame \
    --project="$PROJECT" \
    --location="$LOCATION" \
    --schedule="0 13 * 3-10 *" \
    --time-zone="America/New_York" \
    --topic="$PHASE6_TOPIC" \
    --message-body='{"sport":"mlb","export_types":["pitchers","best-bets"],"target_date":"today"}'

echo ""
echo -e "${GREEN}Done.${NC}"
echo ""
echo "Verify with:"
echo "  gcloud scheduler jobs list --project=$PROJECT --location=$LOCATION | grep mlb-"
echo ""
echo "Manual trigger (test best-bets generation):"
echo "  gcloud scheduler jobs run mlb-best-bets-generate --project=$PROJECT --location=$LOCATION"
