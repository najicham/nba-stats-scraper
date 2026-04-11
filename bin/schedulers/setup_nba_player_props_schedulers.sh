#!/bin/bash
# Setup NBA Player Props Market Schedulers
# ==========================================
# Codifies Cloud Scheduler jobs for NBA assists and rebounds prop scraping.
# Created in Session 515 as live jobs; codified in Session 525 for reproducibility.
#
# Context:
#   - bp_player_props scraper supports market_type: points(default), assists(151), rebounds(157)
#   - Data clock started 2026-04-06; dedicated models needed before predictions can be made
#   - Runs year-round; returns empty during NBA offseason (July-September) — fine
#
# Usage:
#   bash bin/schedulers/setup_nba_player_props_schedulers.sh          # create/update
#   bash bin/schedulers/setup_nba_player_props_schedulers.sh --dry-run # preview only

set -e

PROJECT_ID="nba-props-platform"
REGION="us-west2"
SCRAPERS_URL="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape"
SA_EMAIL="756957797294-compute@developer.gserviceaccount.com"
TIMEZONE="America/New_York"

DRY_RUN="false"
if [[ "${1}" == "--dry-run" ]]; then
    DRY_RUN="true"
    echo "[DRY RUN] No resources will be created or modified."
fi

create_or_update_job() {
    local name="$1"
    local schedule="$2"
    local body="$3"
    local description="$4"

    echo ">>> ${name}"
    echo "    Schedule: ${schedule} (${TIMEZONE})"
    echo "    Body:     ${body}"

    if [[ "${DRY_RUN}" == "true" ]]; then
        echo "    [DRY RUN] Skipping."
        return
    fi

    if gcloud scheduler jobs describe "${name}" \
        --project="${PROJECT_ID}" --location="${REGION}" &>/dev/null; then
        gcloud scheduler jobs update http "${name}" \
            --schedule="${schedule}" \
            --time-zone="${TIMEZONE}" \
            --location="${REGION}" \
            --project="${PROJECT_ID}" \
            --message-body="${body}" \
            --description="${description}" 2>/dev/null
        echo "    Updated."
    else
        gcloud scheduler jobs create http "${name}" \
            --schedule="${schedule}" \
            --time-zone="${TIMEZONE}" \
            --uri="${SCRAPERS_URL}" \
            --http-method=POST \
            --headers="Content-Type=application/json" \
            --message-body="${body}" \
            --location="${REGION}" \
            --project="${PROJECT_ID}" \
            --description="${description}" \
            --oidc-service-account-email="${SA_EMAIL}" \
            --oidc-token-audience="${SCRAPERS_URL}" \
            --attempt-deadline=300s
        echo "    Created."
    fi
    echo ""
}

echo "========================================"
echo "NBA Player Props Market Schedulers"
echo "========================================"
echo ""

# --- Assists props (market_type=assists → market_id=151) ---

create_or_update_job \
    "nba-assists-props-morning" \
    "0 10 * * *" \
    '{"scraper": "bp_player_props", "market_type": "assists", "date": "TODAY"}' \
    "BettingPros player assists prop lines - morning"

create_or_update_job \
    "nba-assists-props-pregame" \
    "0 16 * * *" \
    '{"scraper": "bp_player_props", "market_type": "assists", "date": "TODAY"}' \
    "BettingPros player assists prop lines - pregame"

# --- Rebounds props (market_type=rebounds → market_id=157) ---

create_or_update_job \
    "nba-rebounds-props-morning" \
    "0 10 * * *" \
    '{"scraper": "bp_player_props", "market_type": "rebounds", "date": "TODAY"}' \
    "BettingPros player rebounds prop lines - morning"

create_or_update_job \
    "nba-rebounds-props-pregame" \
    "0 16 * * *" \
    '{"scraper": "bp_player_props", "market_type": "rebounds", "date": "TODAY"}' \
    "BettingPros player rebounds prop lines - pregame"

echo "========================================"
echo "Done."
echo ""
echo "Verify:"
echo "  gcloud scheduler jobs list --location=${REGION} --project=${PROJECT_ID} | grep -E 'assists|rebounds'"
echo ""
echo "Check data accumulation (after NBA season starts):"
echo "  bq query --nouse_legacy_sql 'SELECT market_type, game_date, COUNT(*) as n FROM \`nba-props-platform.nba_raw.bettingpros_player_points_props\` WHERE market_type IN (\"assists\",\"rebounds\") AND game_date >= CURRENT_DATE()-7 GROUP BY 1,2 ORDER BY 2 DESC'"
