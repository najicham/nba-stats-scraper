#!/bin/bash
#
# Check Vegas Line Coverage in Feature Store
#
# This script monitors the Vegas line coverage in the ML feature store
# to detect regressions like the Session 76 issue (44.7% coverage).
#
# IMPORTANT: Vegas coverage represents % of players WITH BETTING LINES, not total players.
# Sportsbooks only offer props for starters and key rotation players (40-50% of roster).
#
# Historical baseline (Jan 2026): 37-50% coverage is NORMAL and healthy
# This is NOT a bug - it reflects real sportsbook behavior
#
# Expected coverage: 35-50% (normal range)
# Alert threshold: <30% (degraded)
# Critical threshold: <20% (severely broken)
#
# Usage:
#   ./bin/monitoring/check_vegas_line_coverage.sh [--date YYYY-MM-DD] [--days N]
#
# Options:
#   --date    Specific date to check (default: today)
#   --days    Number of days to check (default: 1)
#   --alert   Slack webhook URL for alerts (optional)
#
# Exit codes:
#   0 = Coverage ≥35% (healthy - normal sportsbook behavior)
#   1 = Coverage 20-34% (warning - below normal)
#   2 = Coverage <20% (critical - data pipeline broken)

set -euo pipefail

# Default values
CHECK_DATE=$(date +%Y-%m-%d)
DAYS_LOOKBACK=1
ALERT_WEBHOOK="${SLACK_WEBHOOK_URL_WARNING:-}"
CRITICAL_WEBHOOK="${SLACK_WEBHOOK_URL_ERROR:-}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --date)
            CHECK_DATE="$2"
            shift 2
            ;;
        --days)
            DAYS_LOOKBACK="$2"
            shift 2
            ;;
        --alert)
            ALERT_WEBHOOK="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=== Vegas Line Coverage Check ==="
echo "Date: $CHECK_DATE"
echo "Lookback: $DAYS_LOOKBACK days"
echo ""

# Run BigQuery check
RESULT=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT
  game_date,
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as coverage_pct,
  COUNT(*) as total_records,
  COUNTIF(features[OFFSET(25)] > 0) as with_vegas
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(DATE('$CHECK_DATE'), INTERVAL $DAYS_LOOKBACK DAY)
  AND game_date <= DATE('$CHECK_DATE')
  AND ARRAY_LENGTH(features) >= 33
GROUP BY game_date
ORDER BY game_date DESC
" 2>&1)

# Parse results
echo "$RESULT"
echo ""

# Extract average coverage
AVG_COVERAGE=$(echo "$RESULT" | tail -n +2 | awk -F',' '{sum+=$2; count++} END {if(count>0) print sum/count; else print 0}')

# Determine status (updated Feb 2026 - realistic thresholds)
if (( $(echo "$AVG_COVERAGE >= 35" | bc -l) )); then
    STATUS="✅ HEALTHY"
    EXIT_CODE=0
elif (( $(echo "$AVG_COVERAGE >= 20" | bc -l) )); then
    STATUS="🟡 WARNING"
    EXIT_CODE=1
else
    STATUS="🔴 CRITICAL"
    EXIT_CODE=2
fi

echo "Average Coverage: ${AVG_COVERAGE}%"
echo "Status: $STATUS"
echo ""

# Send alerts if needed
if [[ $EXIT_CODE -eq 2 ]] && [[ -n "$CRITICAL_WEBHOOK" ]]; then
    echo "Sending CRITICAL alert..."
    curl -X POST "$CRITICAL_WEBHOOK" \
        -H 'Content-Type: application/json' \
        -d "{
            \"text\": \"🚨 CRITICAL: Vegas Line Coverage Dropped to ${AVG_COVERAGE}%\",
            \"blocks\": [{
                \"type\": \"section\",
                \"text\": {
                    \"type\": \"mrkdwn\",
                    \"text\": \"*Vegas Line Coverage CRITICAL*\n\n*Coverage*: ${AVG_COVERAGE}% (expected: 35-50%)\n*Date Range*: Last $DAYS_LOOKBACK days ending $CHECK_DATE\n*Impact*: Feature store missing betting context\n*Action*: Check Phase 4 deployment and BettingPros scraper\"
                }
            }]
        }" || true
elif [[ $EXIT_CODE -eq 1 ]] && [[ -n "$ALERT_WEBHOOK" ]]; then
    echo "Sending WARNING alert..."
    curl -X POST "$ALERT_WEBHOOK" \
        -H 'Content-Type: application/json' \
        -d "{
            \"text\": \"⚠️ WARNING: Vegas Line Coverage at ${AVG_COVERAGE}%\",
            \"blocks\": [{
                \"type\": \"section\",
                \"text\": {
                    \"type\": \"mrkdwn\",
                    \"text\": \"*Vegas Line Coverage Warning*\n\n*Coverage*: ${AVG_COVERAGE}% (expected: 35-50%)\n*Date Range*: Last $DAYS_LOOKBACK days ending $CHECK_DATE\n*Action*: Monitor and investigate if trend continues\"
                }
            }]
        }" || true
fi

exit $EXIT_CODE
