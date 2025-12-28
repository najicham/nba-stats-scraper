#!/bin/bash
# =============================================================================
# File: bin/monitoring/check_boxscore_completeness.sh
# Purpose: Check boxscore data completeness and alert on gaps
# Usage: ./bin/monitoring/check_boxscore_completeness.sh [--date YYYY-MM-DD] [--days N]
# =============================================================================
#
# This script checks if all scheduled games have boxscore data in BigQuery.
# Designed to run daily after games complete (e.g., 6 AM ET next day).
#
# Features:
# - Compares schedule vs bdl_player_boxscores
# - Alerts if any team's coverage drops below threshold
# - Outputs missing games for manual backfill
# - Can check specific date or last N days
#
# Example Usage:
#   # Check yesterday (default)
#   ./bin/monitoring/check_boxscore_completeness.sh
#
#   # Check specific date
#   ./bin/monitoring/check_boxscore_completeness.sh --date 2025-12-23
#
#   # Check last 7 days
#   ./bin/monitoring/check_boxscore_completeness.sh --days 7
#
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
ALERT_THRESHOLD=90  # Alert if any team below this percentage
CRITICAL_THRESHOLD=70  # Critical alert threshold

# Default to yesterday
CHECK_DATE=$(date -d "yesterday" +%Y-%m-%d)
DAYS_BACK=1

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --date)
            CHECK_DATE="$2"
            DAYS_BACK=0
            shift 2
            ;;
        --days)
            DAYS_BACK="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--date YYYY-MM-DD] [--days N]"
            echo ""
            echo "Options:"
            echo "  --date    Check specific date"
            echo "  --days    Check last N days (default: 1 = yesterday)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Calculate date range
if [ "$DAYS_BACK" -gt 0 ]; then
    END_DATE=$(date -d "yesterday" +%Y-%m-%d)
    START_DATE=$(date -d "$DAYS_BACK days ago" +%Y-%m-%d)
else
    START_DATE="$CHECK_DATE"
    END_DATE="$CHECK_DATE"
fi

echo -e "${BLUE}=================================================${NC}"
echo -e "${BLUE}Boxscore Completeness Check${NC}"
echo -e "${BLUE}=================================================${NC}"
echo ""
echo -e "Date Range: ${START_DATE} to ${END_DATE}"
echo -e "Alert Threshold: ${ALERT_THRESHOLD}%"
echo -e "Critical Threshold: ${CRITICAL_THRESHOLD}%"
echo ""

# Run the completeness query
RESULT=$(bq query --use_legacy_sql=false --format=csv "
WITH schedule AS (
  SELECT game_date, home_team_tricode as team FROM nba_raw.nbac_schedule
  WHERE game_date >= '${START_DATE}' AND game_date <= '${END_DATE}'
  UNION ALL
  SELECT game_date, away_team_tricode as team FROM nba_raw.nbac_schedule
  WHERE game_date >= '${START_DATE}' AND game_date <= '${END_DATE}'
),
team_games AS (
  SELECT team, COUNT(DISTINCT game_date) as scheduled_games
  FROM schedule
  GROUP BY team
),
boxscore_games AS (
  SELECT team_abbr, COUNT(DISTINCT game_date) as boxscore_games
  FROM nba_raw.bdl_player_boxscores
  WHERE game_date >= '${START_DATE}' AND game_date <= '${END_DATE}'
  GROUP BY team_abbr
)
SELECT
  t.team,
  t.scheduled_games,
  COALESCE(b.boxscore_games, 0) as boxscore_games,
  ROUND(COALESCE(b.boxscore_games, 0) * 100.0 / t.scheduled_games, 1) as coverage_pct
FROM team_games t
LEFT JOIN boxscore_games b ON t.team = b.team_abbr
ORDER BY coverage_pct, t.team
")

# Parse results and check for issues
CRITICAL_TEAMS=""
ALERT_TEAMS=""
ALL_OK=true

echo -e "${BLUE}Team Coverage:${NC}"
echo "----------------------------------------------"

# Skip header and process each line
echo "$RESULT" | tail -n +2 | while IFS=, read -r team scheduled boxscore coverage; do
    # Remove quotes if present
    team=$(echo "$team" | tr -d '"')
    coverage=$(echo "$coverage" | tr -d '"')

    if [ -z "$team" ]; then
        continue
    fi

    # Determine status
    coverage_int=${coverage%.*}

    if [ "$coverage_int" -lt "$CRITICAL_THRESHOLD" ]; then
        echo -e "${RED}  $team: $coverage% ($boxscore/$scheduled games) - CRITICAL${NC}"
    elif [ "$coverage_int" -lt "$ALERT_THRESHOLD" ]; then
        echo -e "${YELLOW}  $team: $coverage% ($boxscore/$scheduled games) - WARNING${NC}"
    else
        echo -e "${GREEN}  $team: $coverage% ($boxscore/$scheduled games)${NC}"
    fi
done

echo ""

# Find specific missing games
echo -e "${BLUE}Missing Games:${NC}"
echo "----------------------------------------------"

MISSING=$(bq query --use_legacy_sql=false --format=csv "
WITH schedule AS (
  SELECT game_date, home_team_tricode as team FROM nba_raw.nbac_schedule
  WHERE game_date >= '${START_DATE}' AND game_date <= '${END_DATE}'
  UNION ALL
  SELECT game_date, away_team_tricode as team FROM nba_raw.nbac_schedule
  WHERE game_date >= '${START_DATE}' AND game_date <= '${END_DATE}'
),
boxscores AS (
  SELECT DISTINCT game_date, team_abbr FROM nba_raw.bdl_player_boxscores
  WHERE game_date >= '${START_DATE}' AND game_date <= '${END_DATE}'
)
SELECT s.game_date, s.team
FROM schedule s
LEFT JOIN boxscores b ON s.game_date = b.game_date AND s.team = b.team_abbr
WHERE b.team_abbr IS NULL
ORDER BY s.game_date, s.team
")

MISSING_COUNT=$(echo "$MISSING" | tail -n +2 | grep -v "^$" | wc -l | tr -d ' ')

if [ "$MISSING_COUNT" -eq 0 ]; then
    echo -e "${GREEN}  No missing games!${NC}"
else
    echo -e "${YELLOW}  $MISSING_COUNT missing game-team combinations:${NC}"
    echo "$MISSING" | tail -n +2 | head -20 | while IFS=, read -r date team; do
        date=$(echo "$date" | tr -d '"')
        team=$(echo "$team" | tr -d '"')
        [ -n "$date" ] && echo "    $date: $team"
    done

    if [ "$MISSING_COUNT" -gt 20 ]; then
        echo "    ... and $((MISSING_COUNT - 20)) more"
    fi
fi

echo ""

# Summary and recommendations
echo -e "${BLUE}Summary:${NC}"
echo "----------------------------------------------"

if [ "$MISSING_COUNT" -eq 0 ]; then
    echo -e "${GREEN}All games have boxscore data. No action needed.${NC}"
    exit 0
else
    echo -e "${YELLOW}Found $MISSING_COUNT missing game-team combinations.${NC}"
    echo ""
    echo "To backfill missing dates, run:"
    echo ""

    # Extract unique dates
    DATES=$(echo "$MISSING" | tail -n +2 | cut -d',' -f1 | tr -d '"' | sort -u | tr '\n' ' ')
    echo "  cd /home/naji/code/nba-stats-scraper"
    echo "  for DATE in $DATES; do"
    echo "    PYTHONPATH=. .venv/bin/python scrapers/balldontlie/bdl_box_scores.py --date \$DATE --group gcs"
    echo "  done"
    echo ""
    echo "Then process through Phase 2:"
    echo "  PYTHONPATH=. .venv/bin/python backfill_jobs/raw/bdl_boxscores/bdl_boxscores_raw_backfill.py --dates \"$(echo $DATES | tr ' ' ',')\""

    # Check if any team is below critical threshold
    CRITICAL_COUNT=$(echo "$RESULT" | tail -n +2 | awk -F, -v thresh="$CRITICAL_THRESHOLD" '$4 < thresh {print}' | grep -c "^" || echo "0")

    if [ "$CRITICAL_COUNT" -gt 0 ]; then
        echo ""
        echo -e "${RED}CRITICAL: $CRITICAL_COUNT teams below ${CRITICAL_THRESHOLD}% coverage!${NC}"
        echo "This may cause circuit breaker issues in Phase 3."
        exit 2
    fi

    exit 1
fi
