#!/bin/bash
#
# Monitor System Recovery After Retry Storm Fix
#
# Monitors processor execution patterns in real-time to verify
# the retry storm fix is working.
#
# Usage:
#   ./scripts/monitor_system_recovery.sh [duration_minutes]
#
# Default duration: 30 minutes

set -e

# Configuration
PROJECT_ID="nba-props-platform"
DURATION_MINUTES=${1:-30}
CHECK_INTERVAL_SECONDS=60

# Colors
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "========================================================================"
echo "SYSTEM RECOVERY MONITORING"
echo "========================================================================"
echo "Duration: $DURATION_MINUTES minutes"
echo "Check interval: $CHECK_INTERVAL_SECONDS seconds"
echo "Started: $(date)"
echo "========================================================================"
echo ""

# Calculate end time
END_TIME=$(($(date +%s) + ($DURATION_MINUTES * 60)))

ITERATION=1

while [ $(date +%s) -lt $END_TIME ]; do
    CURRENT_TIME=$(date +"%Y-%m-%d %H:%M:%S")

    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Check #$ITERATION - $CURRENT_TIME${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    # Query: Processor runs in last 10 minutes
    QUERY="
    SELECT
      processor_name,
      COUNT(*) as runs_last_10min,
      COUNTIF(status = 'failed') as failures,
      COUNTIF(status = 'success') as successes,
      COUNT(DISTINCT skip_reason) as skip_reasons,
      ANY_VALUE(skip_reason) as sample_skip_reason
    FROM \`$PROJECT_ID.nba_reference.processor_run_history\`
    WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 10 MINUTE)
    GROUP BY processor_name
    HAVING runs_last_10min > 2
    ORDER BY runs_last_10min DESC
    LIMIT 10
    "

    echo ""
    echo "Top Processors (last 10 minutes):"
    bq query --use_legacy_sql=false --format=pretty "$QUERY" 2>&1

    # Check PlayerGameSummaryProcessor specifically
    PGS_QUERY="
    SELECT
      COUNT(*) as total_runs,
      COUNTIF(status = 'failed') as failures,
      COUNTIF(status = 'success') as successes,
      COUNTIF(skip_reason = 'games_not_finished') as games_not_finished_skips,
      COUNTIF(skip_reason = 'circuit_breaker_open') as circuit_breaker_skips,
      ROUND(100.0 * COUNTIF(status = 'success') / COUNT(*), 1) as success_pct
    FROM \`$PROJECT_ID.nba_reference.processor_run_history\`
    WHERE processor_name = 'PlayerGameSummaryProcessor'
      AND started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 10 MINUTE)
    "

    echo ""
    echo "PlayerGameSummaryProcessor (last 10 minutes):"
    PGS_RESULT=$(bq query --use_legacy_sql=false --format=csv --quiet "$PGS_QUERY" 2>&1 | tail -n +2)

    if [ -n "$PGS_RESULT" ]; then
        TOTAL_RUNS=$(echo "$PGS_RESULT" | cut -d',' -f1)
        FAILURES=$(echo "$PGS_RESULT" | cut -d',' -f2)
        SUCCESSES=$(echo "$PGS_RESULT" | cut -d',' -f3)
        GAMES_NOT_FINISHED=$(echo "$PGS_RESULT" | cut -d',' -f4)
        CIRCUIT_BREAKER=$(echo "$PGS_RESULT" | cut -d',' -f5)
        SUCCESS_PCT=$(echo "$PGS_RESULT" | cut -d',' -f6)

        echo "  Total runs: $TOTAL_RUNS"
        echo "  Successes: $SUCCESSES"
        echo "  Failures: $FAILURES"
        echo "  Games not finished skips: $GAMES_NOT_FINISHED"
        echo "  Circuit breaker skips: $CIRCUIT_BREAKER"
        echo "  Success rate: $SUCCESS_PCT%"

        # Assess health
        if [ "$TOTAL_RUNS" -gt 100 ]; then
            echo -e "  Status: ${RED}RETRY STORM ONGOING${NC} (>100 runs/10min)"
        elif [ "$TOTAL_RUNS" -gt 20 ]; then
            echo -e "  Status: ${YELLOW}ELEVATED ACTIVITY${NC} (>20 runs/10min)"
        elif [ "$GAMES_NOT_FINISHED" -gt 0 ]; then
            echo -e "  Status: ${GREEN}HEALTHY - EARLY EXIT WORKING${NC} (games not finished skips)"
        elif [ "$TOTAL_RUNS" -lt 5 ]; then
            echo -e "  Status: ${GREEN}HEALTHY - NORMAL ACTIVITY${NC} (<5 runs/10min)"
        else
            echo -e "  Status: ${BLUE}MONITORING${NC}"
        fi
    else
        echo -e "  Status: ${GREEN}NO ACTIVITY${NC} (0 runs in last 10 minutes)"
    fi

    # System health
    HEALTH_QUERY="
    SELECT
      COUNT(*) as total_runs,
      COUNTIF(status = 'success') as successes,
      ROUND(100.0 * COUNTIF(status = 'success') / COUNT(*), 1) as success_pct
    FROM \`$PROJECT_ID.nba_reference.processor_run_history\`
    WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 10 MINUTE)
    "

    echo ""
    echo "Overall System Health (last 10 minutes):"
    HEALTH_RESULT=$(bq query --use_legacy_sql=false --format=csv --quiet "$HEALTH_QUERY" 2>&1 | tail -n +2)

    if [ -n "$HEALTH_RESULT" ]; then
        SYSTEM_SUCCESS_PCT=$(echo "$HEALTH_RESULT" | cut -d',' -f3)
        echo "  Success rate: $SYSTEM_SUCCESS_PCT%"

        if (( $(echo "$SYSTEM_SUCCESS_PCT < 50" | bc -l) )); then
            echo -e "  Status: ${RED}CRITICAL${NC}"
        elif (( $(echo "$SYSTEM_SUCCESS_PCT < 70" | bc -l) )); then
            echo -e "  Status: ${YELLOW}DEGRADED${NC}"
        else
            echo -e "  Status: ${GREEN}HEALTHY${NC}"
        fi
    fi

    # Time remaining
    TIME_REMAINING=$(( ($END_TIME - $(date +%s)) / 60 ))
    echo ""
    echo "Time remaining: $TIME_REMAINING minutes"
    echo ""

    # Sleep unless this is the last iteration
    if [ $(date +%s) -lt $END_TIME ]; then
        sleep $CHECK_INTERVAL_SECONDS
    fi

    ITERATION=$((ITERATION + 1))
done

echo "========================================================================"
echo "MONITORING COMPLETE"
echo "========================================================================"
echo "Ended: $(date)"
echo ""
echo "Final system status check..."

# Final comprehensive check
FINAL_QUERY="
SELECT
  processor_name,
  COUNT(*) as runs_last_30min,
  COUNTIF(status = 'failed') as failures,
  COUNTIF(status = 'success') as successes,
  ROUND(100.0 * COUNTIF(status = 'success') / COUNT(*), 1) as success_pct
FROM \`$PROJECT_ID.nba_reference.processor_run_history\`
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)
GROUP BY processor_name
ORDER BY runs_last_30min DESC
LIMIT 20
"

echo ""
echo "Top 20 Processors (last 30 minutes):"
bq query --use_legacy_sql=false --format=pretty "$FINAL_QUERY"

echo ""
echo "Monitoring session complete."
