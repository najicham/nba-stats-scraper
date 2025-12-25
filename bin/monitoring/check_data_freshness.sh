#!/bin/bash
# ==============================================================================
# Data Freshness Monitor
# ==============================================================================
# Checks key tables for data staleness and alerts on issues.
#
# This script helps prevent issues like Session 165's gamebook staleness
# where data went 4 days stale before being noticed.
#
# Run this daily (e.g., via cron or Cloud Scheduler) to catch issues early.
#
# Usage:
#   ./bin/monitoring/check_data_freshness.sh
#   ./bin/monitoring/check_data_freshness.sh --alert  # Send alerts on issues
#
# Exit codes:
#   0 - All data is fresh
#   1 - Some data is stale (warning)
#   2 - Critical staleness detected
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Colors
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Thresholds (in days)
WARN_THRESHOLD=2
CRITICAL_THRESHOLD=4

echo "=============================================="
echo "📊 DATA FRESHNESS CHECK"
echo "=============================================="
echo "Timestamp: $(TZ=America/New_York date '+%Y-%m-%d %H:%M:%S %Z')"
echo ""

# Track overall status
OVERALL_STATUS=0

check_table_freshness() {
    local table=$1
    local date_column=$2
    local description=$3
    local expected_lag_days=${4:-1}  # How many days behind is acceptable (default 1)

    # Query for latest date
    result=$(bq query --use_legacy_sql=false --format=json \
        "SELECT MAX(${date_column}) as latest_date FROM ${table} WHERE ${date_column} >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)" 2>/dev/null | jq -r '.[0].latest_date // "NULL"')

    if [[ "$result" == "NULL" || "$result" == "null" || -z "$result" ]]; then
        echo -e "${RED}❌ ${description}${NC}"
        echo "   Table: $table"
        echo "   Status: NO DATA in last 30 days"
        echo ""
        OVERALL_STATUS=2
        return
    fi

    # Calculate days since latest
    today=$(date +%Y-%m-%d)
    latest_epoch=$(date -d "$result" +%s 2>/dev/null || echo 0)
    today_epoch=$(date -d "$today" +%s)
    days_old=$(( (today_epoch - latest_epoch) / 86400 ))
    effective_lag=$((days_old - expected_lag_days))

    if [[ $effective_lag -ge $CRITICAL_THRESHOLD ]]; then
        echo -e "${RED}🚨 ${description}${NC}"
        echo "   Table: $table"
        echo "   Latest: $result ($days_old days ago)"
        echo "   Status: CRITICAL - ${effective_lag} days stale (expected lag: ${expected_lag_days})"
        echo ""
        OVERALL_STATUS=2
    elif [[ $effective_lag -ge $WARN_THRESHOLD ]]; then
        echo -e "${YELLOW}⚠️  ${description}${NC}"
        echo "   Table: $table"
        echo "   Latest: $result ($days_old days ago)"
        echo "   Status: WARNING - ${effective_lag} days stale"
        echo ""
        [[ $OVERALL_STATUS -lt 1 ]] && OVERALL_STATUS=1
    else
        echo -e "${GREEN}✅ ${description}${NC}"
        echo "   Table: $table"
        echo "   Latest: $result ($days_old days ago)"
        echo ""
    fi
}

echo "=== Phase 2 (Raw) Tables ==="
echo ""

check_table_freshness \
    "nba_raw.bdl_player_boxscores" \
    "game_date" \
    "BDL Player Boxscores" \
    1

check_table_freshness \
    "nba_raw.nbac_gamebook_player_stats" \
    "game_date" \
    "NBA.com Gamebook Player Stats" \
    1

check_table_freshness \
    "nba_raw.nbac_schedule" \
    "game_date" \
    "NBA.com Schedule" \
    0

check_table_freshness \
    "nba_raw.nbac_injury_report" \
    "report_date" \
    "NBA.com Injury Report" \
    0

check_table_freshness \
    "nba_raw.bettingpros_player_points_props" \
    "game_date" \
    "BettingPros Player Props" \
    1

echo "=== Phase 3 (Analytics) Tables ==="
echo ""

check_table_freshness \
    "nba_analytics.player_game_summary" \
    "game_date" \
    "Player Game Summary" \
    1

check_table_freshness \
    "nba_analytics.upcoming_player_game_context" \
    "game_date" \
    "Upcoming Player Game Context" \
    1

check_table_freshness \
    "nba_analytics.team_defense_game_summary" \
    "game_date" \
    "Team Defense Game Summary" \
    1

echo "=============================================="
echo "SUMMARY"
echo "=============================================="

if [[ $OVERALL_STATUS -eq 0 ]]; then
    echo -e "${GREEN}✅ All data is fresh${NC}"
elif [[ $OVERALL_STATUS -eq 1 ]]; then
    echo -e "${YELLOW}⚠️  Some data is stale (warnings)${NC}"
else
    echo -e "${RED}🚨 CRITICAL: Data staleness detected${NC}"
    echo ""
    echo "Recommended actions:"
    echo "1. Check scraper logs: gcloud logging read 'resource.labels.service_name=\"nba-phase1-scrapers\"' --limit=50 --freshness=24h"
    echo "2. Check Phase 2 logs: gcloud logging read 'resource.labels.service_name=\"nba-phase2-raw-processors\"' --limit=50 --freshness=24h"
    echo "3. Consider running backfill for missing dates"
fi

echo ""
echo "Run completed at $(TZ=America/New_York date '+%Y-%m-%d %H:%M:%S %Z')"

exit $OVERALL_STATUS
