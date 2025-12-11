#!/bin/bash
#
# Backfill Health Monitor
#
# Run this periodically while a backfill is in progress to check:
# 1. Progress (dates being processed)
# 2. Failures accumulating
# 3. Cascade contamination
#
# Usage:
#   ./bin/backfill/monitor_backfill.sh 2021-11-01 2021-12-31
#   watch -n 60 ./bin/backfill/monitor_backfill.sh 2021-11-01 2021-12-31  # Auto-refresh
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

START=${1:-"2021-11-01"}
END=${2:-"2021-12-31"}

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}BACKFILL HEALTH CHECK${NC}"
echo -e "${BLUE}$(date)${NC}"
echo -e "${BLUE}Range: $START to $END${NC}"
echo -e "${BLUE}======================================${NC}"

echo ""
echo -e "${YELLOW}--- Progress (latest dates processed) ---${NC}"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  'TDZA' as proc, MAX(DATE(analysis_date)) as latest, COUNT(DISTINCT DATE(analysis_date)) as dates
FROM nba_precompute.team_defense_zone_analysis WHERE DATE(analysis_date) BETWEEN '$START' AND '$END'
UNION ALL
SELECT 'PSZA', MAX(DATE(analysis_date)), COUNT(DISTINCT DATE(analysis_date))
FROM nba_precompute.player_shot_zone_analysis WHERE DATE(analysis_date) BETWEEN '$START' AND '$END'
UNION ALL
SELECT 'PCF', MAX(DATE(game_date)), COUNT(DISTINCT DATE(game_date))
FROM nba_precompute.player_composite_factors WHERE DATE(game_date) BETWEEN '$START' AND '$END'
UNION ALL
SELECT 'PDC', MAX(DATE(cache_date)), COUNT(DISTINCT DATE(cache_date))
FROM nba_precompute.player_daily_cache WHERE DATE(cache_date) BETWEEN '$START' AND '$END'
UNION ALL
SELECT 'MLFS', MAX(DATE(game_date)), COUNT(DISTINCT DATE(game_date))
FROM nba_predictions.ml_feature_store_v2 WHERE DATE(game_date) BETWEEN '$START' AND '$END'
ORDER BY proc"

echo ""
echo -e "${YELLOW}--- Failure Categories (all time for range) ---${NC}"
FAILURES=$(bq query --use_legacy_sql=false --format=csv "
SELECT failure_category, COUNT(*) as cnt
FROM nba_processing.precompute_failures
WHERE analysis_date BETWEEN '$START' AND '$END'
GROUP BY 1 ORDER BY 2 DESC LIMIT 10" 2>/dev/null | tail -n +2)

if [ -z "$FAILURES" ]; then
    echo -e "${GREEN}No failures recorded yet${NC}"
else
    # Check for PROCESSING_ERROR
    if echo "$FAILURES" | grep -q "PROCESSING_ERROR"; then
        echo -e "${RED}WARNING: PROCESSING_ERROR detected! Consider stopping.${NC}"
    fi
    echo "$FAILURES" | while IFS=, read -r cat cnt; do
        if [ "$cat" = "PROCESSING_ERROR" ]; then
            echo -e "${RED}  $cat: $cnt${NC}"
        elif [ "$cat" = "INSUFFICIENT_DATA" ] || [ "$cat" = "EXPECTED_INCOMPLETE" ]; then
            echo -e "${GREEN}  $cat: $cnt (expected)${NC}"
        else
            echo -e "${YELLOW}  $cat: $cnt${NC}"
        fi
    done
fi

echo ""
echo -e "${YELLOW}--- Cascade Contamination Check ---${NC}"
BAD_RECORDS=$(bq query --use_legacy_sql=false --format=csv "
SELECT
  COUNT(*) as bad_records,
  (SELECT COUNT(*) FROM nba_precompute.player_composite_factors WHERE game_date BETWEEN '$START' AND '$END') as total
FROM nba_precompute.player_composite_factors
WHERE game_date BETWEEN '$START' AND '$END'
  AND opponent_strength_score = 0" 2>/dev/null | tail -n 1)

BAD=$(echo "$BAD_RECORDS" | cut -d',' -f1)
TOTAL=$(echo "$BAD_RECORDS" | cut -d',' -f2)

if [ "$TOTAL" -gt 0 ] 2>/dev/null; then
    PCT=$(echo "scale=2; $BAD * 100 / $TOTAL" | bc 2>/dev/null || echo "0")
    if [ "$BAD" -eq 0 ]; then
        echo -e "${GREEN}No contamination detected (0 / $TOTAL records)${NC}"
    elif (( $(echo "$PCT > 5" | bc -l 2>/dev/null || echo 0) )); then
        echo -e "${RED}CONTAMINATION DETECTED: $BAD / $TOTAL records ($PCT%) have zero opponent_strength_score${NC}"
        echo -e "${RED}Consider stopping and investigating!${NC}"
    else
        echo -e "${YELLOW}Minor issues: $BAD / $TOTAL records ($PCT%) - may be early season${NC}"
    fi
else
    echo "No PCF records found yet"
fi

echo ""
echo -e "${YELLOW}--- Recent Activity (last 30 min) ---${NC}"
RECENT=$(bq query --use_legacy_sql=false --format=csv "
SELECT processor_name, COUNT(*) as failures
FROM nba_processing.precompute_failures
WHERE analysis_date BETWEEN '$START' AND '$END'
  AND created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)
GROUP BY 1 ORDER BY 2 DESC" 2>/dev/null | tail -n +2)

if [ -z "$RECENT" ]; then
    echo -e "${GREEN}No new failures in last 30 minutes${NC}"
else
    echo "Recent failures by processor:"
    echo "$RECENT" | while IFS=, read -r proc cnt; do
        echo "  $proc: $cnt"
    done
fi

echo ""
echo -e "${YELLOW}--- Circuit Breaker Status ---${NC}"
CIRCUITS=$(bq query --use_legacy_sql=false --format=csv "
SELECT processor_name, COUNT(*) as tripped
FROM nba_orchestration.reprocess_attempts
WHERE analysis_date BETWEEN '$START' AND '$END'
  AND circuit_breaker_tripped = TRUE
  AND circuit_breaker_until > CURRENT_TIMESTAMP()
GROUP BY 1" 2>/dev/null | tail -n +2)

if [ -z "$CIRCUITS" ]; then
    echo -e "${GREEN}No circuit breakers tripped${NC}"
else
    echo -e "${RED}WARNING: Circuit breakers tripped!${NC}"
    echo "$CIRCUITS"
fi

echo ""
echo -e "${YELLOW}--- Production Ready % (latest 3 dates) ---${NC}"
bq query --use_legacy_sql=false --format=pretty "
SELECT game_date,
  ROUND(100.0 * COUNTIF(is_production_ready = TRUE) / COUNT(*), 1) as ready_pct,
  COUNT(*) as total
FROM nba_precompute.player_composite_factors
WHERE game_date BETWEEN '$START' AND '$END'
GROUP BY 1 ORDER BY 1 DESC LIMIT 3" 2>/dev/null

echo ""
echo -e "${YELLOW}--- Phase 5 Predictions Progress ---${NC}"
PREDICTIONS=$(bq query --use_legacy_sql=false --format=csv "
SELECT
  COUNT(DISTINCT game_date) as dates,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT system_id) as systems
FROM nba_predictions.player_prop_predictions
WHERE game_date BETWEEN '$START' AND '$END'" 2>/dev/null | tail -n 1)

if [ -z "$PREDICTIONS" ] || [ "$PREDICTIONS" = "0,0,0" ]; then
    echo "No predictions yet (Phase 5 not started)"
else
    DATES=$(echo "$PREDICTIONS" | cut -d',' -f1)
    TOTAL=$(echo "$PREDICTIONS" | cut -d',' -f2)
    SYSTEMS=$(echo "$PREDICTIONS" | cut -d',' -f3)
    echo "Dates: $DATES | Predictions: $TOTAL | Systems: $SYSTEMS"
    if [ "$SYSTEMS" -lt 5 ] 2>/dev/null; then
        echo -e "${YELLOW}WARNING: Only $SYSTEMS/5 systems generating predictions${NC}"
    fi
fi

echo ""
echo -e "${BLUE}======================================${NC}"
echo -e "Run with: ${GREEN}watch -n 60 ./bin/backfill/monitor_backfill.sh $START $END${NC}"
echo -e "${BLUE}======================================${NC}"
