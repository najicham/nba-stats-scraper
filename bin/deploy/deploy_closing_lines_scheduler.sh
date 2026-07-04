#!/bin/bash
# deploy_closing_lines_scheduler.sh
#
# Deploy the Cloud Scheduler job for the per-game T-30 closing-line sweep
# (2026-07-03, CLV closing-line capture — season-open-BLOCKING item P1.2).
#
# Every 30 minutes during game hours it POSTs /closing-line-sweep on
# nba-scrapers. The endpoint no-ops (cheap BQ schedule check, zero API calls)
# unless a game tips in the next ~15-50 minutes; otherwise it captures one
# oddsa_player_props snapshot per imminent event with snapshot_type='closing'.
# Guarantees every game gets a snapshot at minutes_before_tipoff in [0,45] —
# the canonical closing window the CLV UNDER edge was validated on.
#
# Quota: the /events discovery call is quota-free; props calls add ~1 per
# game per night (~5-12/day) on top of ~50-80/day from betting_lines.
#
# Cadence covers 12:00 PM - 11:45 PM ET (weekend matinees tip as early as
# 12:30 PM ET; latest tips ~10:30 PM ET). Off-season every sweep no-ops.
#
# Usage:
#   ./bin/deploy/deploy_closing_lines_scheduler.sh
#   ./bin/deploy/deploy_closing_lines_scheduler.sh --dry-run
#   ./bin/deploy/deploy_closing_lines_scheduler.sh --paused   # create paused (off-season)

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
SCRAPERS_BASE="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"
SWEEP_URL="${SCRAPERS_BASE}/closing-line-sweep"
SA_EMAIL="756957797294-compute@developer.gserviceaccount.com"
TIMEZONE="America/New_York"
JOB_NAME="nba-closing-lines-sweep"
SCHEDULE="0,30 12-23 * * *"

DRY_RUN="false"
PAUSED="false"
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN="true"; echo "[DRY RUN] No resources will be created or modified." ;;
        --paused)  PAUSED="true" ;;
    esac
done

echo "========================================"
echo "NBA Closing-Line Sweep Scheduler (T-30)"
echo "========================================"
echo "Project:  $PROJECT_ID"
echo "Schedule: $SCHEDULE ($TIMEZONE)"
echo "Target:   $SWEEP_URL"
echo ""

BODY='{}'

if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN] Would create/update job: $JOB_NAME (paused=$PAUSED)"
    exit 0
fi

# Delete existing job if present (idempotent redeploy)
if gcloud scheduler jobs describe "$JOB_NAME" \
    --project="$PROJECT_ID" --location="$REGION" &>/dev/null; then
    echo "Deleting existing job: $JOB_NAME"
    gcloud scheduler jobs delete "$JOB_NAME" \
        --project="$PROJECT_ID" --location="$REGION" --quiet
fi

gcloud scheduler jobs create http "$JOB_NAME" \
    --schedule="$SCHEDULE" \
    --time-zone="$TIMEZONE" \
    --uri="$SWEEP_URL" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body="$BODY" \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --description="Per-game T-30 closing-line odds snapshot (CLV capture; no-op when no imminent games)" \
    --oidc-service-account-email="$SA_EMAIL" \
    --oidc-token-audience="$SCRAPERS_BASE" \
    --attempt-deadline=540s

if [[ "$PAUSED" == "true" ]]; then
    gcloud scheduler jobs pause "$JOB_NAME" \
        --project="$PROJECT_ID" --location="$REGION"
    echo "✅ Created (PAUSED): $JOB_NAME — resume before opening night"
else
    echo "✅ Created: $JOB_NAME"
fi

echo ""
echo "Smoke test (any time; off-season returns imminent_games=0):"
echo "  gcloud scheduler jobs run $JOB_NAME --location=$REGION --project=$PROJECT_ID"
echo ""
echo "Season-open verification (preseason dress rehearsal):"
echo "  SELECT game_id, MIN(minutes_before_tipoff) FROM nba_raw.odds_api_player_points_props"
echo "  WHERE game_date = CURRENT_DATE() AND snapshot_type='closing' GROUP BY 1"
