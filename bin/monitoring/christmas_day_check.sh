#!/bin/bash
set -euo pipefail
# christmas_day_check.sh - Quick pipeline health check for Christmas Day
#
# Run this to get a snapshot of pipeline status
# Usage: ./bin/monitoring/christmas_day_check.sh

REGION="us-west2"

echo "🎄 Christmas Day Pipeline Check"
echo "================================"
echo "Time: $(TZ=America/New_York date '+%Y-%m-%d %H:%M:%S %Z')"
echo ""

# ─────────────────────────────────────────────────────────────
# 1. Service Health & Commit Verification
# ─────────────────────────────────────────────────────────────
echo "📡 SERVICE STATUS"
echo "─────────────────"

SERVICES=(
    "nba-phase1-scrapers"
    "nba-phase2-raw-processors"
    "nba-phase3-analytics-processors"
    "nba-phase4-precompute-processors"
)

for svc in "${SERVICES[@]}"; do
    COMMIT=$(gcloud run services describe $svc --region=$REGION --format="value(metadata.labels.commit-sha)" 2>/dev/null)
    REVISION=$(gcloud run services describe $svc --region=$REGION --format="value(status.latestReadyRevisionName)" 2>/dev/null)
    echo "  $svc: $REVISION (commit: ${COMMIT:-unknown})"
done
echo ""

# ─────────────────────────────────────────────────────────────
# 2. Recent Errors (last 2 hours)
# ─────────────────────────────────────────────────────────────
echo "🚨 RECENT ERRORS (last 2 hours)"
echo "────────────────────────────────"

for svc in "${SERVICES[@]}"; do
    ERROR_COUNT=$(gcloud logging read "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"$svc\" AND severity>=ERROR" --limit=100 --freshness=2h --format="value(timestamp)" 2>/dev/null | wc -l)
    if [ "$ERROR_COUNT" -gt 0 ]; then
        echo "  ⚠️  $svc: $ERROR_COUNT errors"
    else
        echo "  ✅ $svc: No errors"
    fi
done
echo ""

# ─────────────────────────────────────────────────────────────
# 3. Christmas Day Schedule
# ─────────────────────────────────────────────────────────────
echo "🏀 CHRISTMAS DAY GAMES"
echo "──────────────────────"
bq query --use_legacy_sql=false --format=pretty "
SELECT
    DATETIME(TIMESTAMP(game_date_est), 'America/New_York') as tip_off_et,
    away_team_tricode || ' @ ' || home_team_tricode as matchup,
    game_status_text
FROM nba_raw.nbac_schedule
WHERE game_date = '2025-12-25'
ORDER BY game_date_est
" 2>/dev/null
echo ""

# ─────────────────────────────────────────────────────────────
# 4. Data Freshness
# ─────────────────────────────────────────────────────────────
echo "📊 DATA FRESHNESS"
echo "─────────────────"

# Check betting lines
echo "  Betting Lines (odds):"
bq query --use_legacy_sql=false --format=csv "
SELECT
    'odds_api_game_lines' as source,
    MAX(created_at) as last_scraped,
    COUNT(*) as rows_today
FROM nba_raw.odds_api_game_lines
WHERE DATE(created_at) = CURRENT_DATE()
" 2>/dev/null | tail -1

# Check schedule freshness
echo "  Schedule:"
bq query --use_legacy_sql=false --format=csv "
SELECT
    'nbac_schedule' as source,
    MAX(created_at) as last_update,
    COUNT(*) as total_games
FROM nba_raw.nbac_schedule
WHERE game_date >= CURRENT_DATE()
" 2>/dev/null | tail -1

# Check player context (Phase 3)
echo "  Player Context (Phase 3):"
bq query --use_legacy_sql=false --format=csv "
SELECT
    'upcoming_player_game_context' as source,
    MAX(game_date) as latest_game_date,
    COUNT(DISTINCT player_lookup) as players
FROM nba_analytics.upcoming_player_game_context
WHERE game_date >= CURRENT_DATE()
" 2>/dev/null | tail -1

echo ""

# ─────────────────────────────────────────────────────────────
# 5. Recent Workflow Executions
# ─────────────────────────────────────────────────────────────
echo "⚡ RECENT WORKFLOW ACTIVITY (last 4 hours)"
echo "───────────────────────────────────────────"
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase1-scrapers" AND ("Workflow Complete" OR "Executing Workflow")' --limit=10 --freshness=4h --format="table(timestamp.date('%H:%M'),textPayload)" 2>/dev/null | head -15
echo ""

# ─────────────────────────────────────────────────────────────
# 6. Key Times Today
# ─────────────────────────────────────────────────────────────
echo "⏰ KEY TIMES TODAY (ET)"
echo "───────────────────────"
echo "  ~6:00 AM  - betting_lines workflow starts"
echo "  12:00 PM  - CLE @ NYK tips off"
echo "  ~3:00 PM  - early_game_window_1 (collect noon game)"
echo "  2:30 PM   - SAS @ OKC tips off"
echo "  5:00 PM   - DAL @ GSW tips off"
echo "  ~6:00 PM  - early_game_window_2"
echo "  8:00 PM   - HOU @ LAL tips off"
echo "  ~9:00 PM  - early_game_window_3"
echo "  10:30 PM  - MIN @ DEN tips off"
echo ""

echo "🎄 Pipeline check complete!"
echo ""
echo "Quick commands:"
echo "  View Phase 2 errors:  gcloud logging read 'resource.labels.service_name=\"nba-phase2-raw-processors\" AND severity>=ERROR' --limit=10 --freshness=1h"
echo "  View scraper logs:    gcloud logging read 'resource.labels.service_name=\"nba-phase1-scrapers\"' --limit=20 --freshness=1h"
