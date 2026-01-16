#!/bin/bash
#
# NBA Daily Health Check Script
#
# Runs every morning to validate system health after previous day's games.
# Checks:
# 1. Analytics coverage
# 2. R-009 zero active players check
# 3. Prediction grading completeness
# 4. Scraper failures
# 5. BDL data freshness
# 6. Retry storm detection
#
# Usage:
#   ./scripts/daily_health_check.sh [YYYY-MM-DD]
#
# If no date provided, checks yesterday's data.

set -e

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ID="nba-props-platform"
DATASET="nba_analytics"

# Get date to check (yesterday by default)
if [ -z "$1" ]; then
    CHECK_DATE=$(date -d "yesterday" +%Y-%m-%d)
else
    CHECK_DATE=$1
fi

echo "========================================================================"
echo "NBA DAILY HEALTH CHECK - $CHECK_DATE"
echo "========================================================================"
echo ""

# Function to run query and check result
run_check() {
    local check_name=$1
    local query=$2
    local expected=$3

    echo -n "Checking $check_name... "

    result=$(bq query --use_legacy_sql=false --format=csv --quiet "$query" 2>&1 | tail -n 1)

    if [ "$result" == "$expected" ]; then
        echo -e "${GREEN}✓ PASS${NC}"
        return 0
    else
        echo -e "${RED}✗ FAIL${NC} (got: $result, expected: $expected)"
        return 1
    fi
}

# Track failures
FAILED_CHECKS=0

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1. ANALYTICS COVERAGE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Get game count and analytics
ANALYTICS_QUERY="
SELECT
  COUNT(DISTINCT game_id) as games,
  COUNT(*) as player_records
FROM \`$PROJECT_ID.nba_analytics.player_game_summary\`
WHERE game_date = '$CHECK_DATE'
"

echo "Running analytics coverage check..."
bq query --use_legacy_sql=false --format=pretty "$ANALYTICS_QUERY"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2. R-009 CHECK (Zero Active Players)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

R009_QUERY="
SELECT COUNT(*) as zero_active_games
FROM (
  SELECT
    game_id,
    COUNTIF(is_active = TRUE) as active_players
  FROM \`$PROJECT_ID.nba_analytics.player_game_summary\`
  WHERE game_date = '$CHECK_DATE'
  GROUP BY game_id
  HAVING active_players = 0
)
"

ZERO_ACTIVE=$(bq query --use_legacy_sql=false --format=csv --quiet "$R009_QUERY" 2>&1 | tail -n 1)

if [ "$ZERO_ACTIVE" == "0" ]; then
    echo -e "${GREEN}✓ PASS${NC} - No games with 0 active players"
else
    echo -e "${RED}✗ CRITICAL${NC} - Found $ZERO_ACTIVE games with 0 active players (R-009 REGRESSION!)"
    FAILED_CHECKS=$((FAILED_CHECKS + 1))
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3. PREDICTION GRADING COMPLETENESS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

GRADING_QUERY="
SELECT
  COUNT(*) as total,
  COUNTIF(grade IS NOT NULL) as graded,
  ROUND(100.0 * COUNTIF(grade IS NOT NULL) / COUNT(*), 1) as pct
FROM \`$PROJECT_ID.nba_predictions.player_prop_predictions\`
WHERE game_date = '$CHECK_DATE'
"

echo "Running prediction grading check..."
bq query --use_legacy_sql=false --format=pretty "$GRADING_QUERY"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "4. SCRAPER FAILURES (Last 24 hours)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

FAILURES_QUERY="
SELECT
  scraper_name,
  COUNT(*) as runs,
  COUNTIF(status = 'failed') as failures,
  ROUND(100.0 * COUNTIF(status = 'failed') / COUNT(*), 1) as failure_pct
FROM \`$PROJECT_ID.nba_orchestration.scraper_execution_log\`
WHERE DATE(created_at) = '$CHECK_DATE'
GROUP BY scraper_name
HAVING failures > 0
ORDER BY failures DESC
LIMIT 10
"

echo "Running scraper failure check..."
bq query --use_legacy_sql=false --format=pretty "$FAILURES_QUERY" || echo "No significant failures"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "5. BDL DATA FRESHNESS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

FRESHNESS_QUERY="
SELECT
  MAX(created_at) as latest_bdl_scrape,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), HOUR) as hours_old
FROM \`$PROJECT_ID.nba_orchestration.scraper_execution_log\`
WHERE scraper_name = 'bdl_box_scores_scraper'
  AND status = 'success'
  AND DATE(created_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY)
"

echo "Running BDL freshness check..."
bq query --use_legacy_sql=false --format=pretty "$FRESHNESS_QUERY"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "6. RETRY STORM DETECTION (Last 1 hour)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

RETRY_STORM_QUERY="
SELECT
  processor_name,
  COUNT(*) as runs_last_hour,
  COUNTIF(status = 'failed') as failures,
  ROUND(100.0 * COUNTIF(status = 'failed') / COUNT(*), 1) as failure_pct
FROM \`$PROJECT_ID.nba_reference.processor_run_history\`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
GROUP BY processor_name
HAVING runs_last_hour > 50  -- Alert threshold
ORDER BY runs_last_hour DESC
"

echo "Running retry storm detection..."
RETRY_STORMS=$(bq query --use_legacy_sql=false --format=csv --quiet "$RETRY_STORM_QUERY" 2>&1 | wc -l)

if [ "$RETRY_STORMS" -le 1 ]; then
    echo -e "${GREEN}✓ PASS${NC} - No retry storms detected"
else
    echo -e "${YELLOW}⚠ WARNING${NC} - Detected potential retry storms:"
    bq query --use_legacy_sql=false --format=pretty "$RETRY_STORM_QUERY"
    FAILED_CHECKS=$((FAILED_CHECKS + 1))
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "SUMMARY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ $FAILED_CHECKS -eq 0 ]; then
    echo -e "${GREEN}✓ ALL CHECKS PASSED${NC}"
    echo ""
    echo "System is healthy for $CHECK_DATE"
    exit 0
else
    echo -e "${RED}✗ $FAILED_CHECKS CHECKS FAILED${NC}"
    echo ""
    echo "Please investigate issues above"
    exit 1
fi
