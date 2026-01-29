#!/bin/bash
# Unified validation command - checks everything in one place
# Usage: ./bin/validate-all.sh [--date YYYY-MM-DD]

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Parse arguments
DATE=$(date +%Y-%m-%d)
if [[ "$1" == "--date" && -n "$2" ]]; then
    DATE="$2"
fi

echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  NBA PIPELINE VALIDATION - $DATE${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""

WARNINGS=0
ERRORS=0

check_result() {
    local name="$1"
    local status="$2"
    local detail="$3"
    
    if [[ "$status" == "ok" ]]; then
        echo -e "${GREEN}✅ $name${NC}"
        [[ -n "$detail" ]] && echo "   $detail"
    elif [[ "$status" == "warning" ]]; then
        echo -e "${YELLOW}⚠️  $name${NC}"
        [[ -n "$detail" ]] && echo "   $detail"
        ((WARNINGS++))
    else
        echo -e "${RED}❌ $name${NC}"
        [[ -n "$detail" ]] && echo "   $detail"
        ((ERRORS++))
    fi
}

# 1. DEPLOYMENT STATUS
echo -e "${BLUE}[1] DEPLOYMENT STATUS${NC}"
if ./bin/check-deployment-drift.sh 2>/dev/null | grep -q "Services with drift: 0"; then
    check_result "All services deployed" "ok" "No drift detected"
else
    DRIFT_COUNT=$(./bin/check-deployment-drift.sh 2>/dev/null | grep "Services with drift:" | grep -oE '[0-9]+' || echo "?")
    check_result "Deployment drift detected" "error" "$DRIFT_COUNT services need redeployment"
fi
echo ""

# 2. DATA FRESHNESS
echo -e "${BLUE}[2] DATA FRESHNESS${NC}"

# Check gamebook
GAMEBOOK_DATE=$(bq query --use_legacy_sql=false --format=csv \
    "SELECT MAX(game_date) FROM nba_raw.nbac_gamebook_player_stats" 2>/dev/null | tail -1)
if [[ "$GAMEBOOK_DATE" == "$DATE" ]] || [[ "$GAMEBOOK_DATE" == "$(date -d "$DATE - 1 day" +%Y-%m-%d)" ]]; then
    check_result "Gamebook data" "ok" "Latest: $GAMEBOOK_DATE"
else
    check_result "Gamebook data" "warning" "Latest: $GAMEBOOK_DATE (may be stale)"
fi

# Check predictions
PRED_COUNT=$(bq query --use_legacy_sql=false --format=csv \
    "SELECT COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date = '$DATE'" 2>/dev/null | tail -1)
if [[ "$PRED_COUNT" -gt 0 ]]; then
    check_result "Predictions" "ok" "$PRED_COUNT predictions for $DATE"
else
    check_result "Predictions" "warning" "No predictions for $DATE"
fi

# Check feature store
FEATURE_COUNT=$(bq query --use_legacy_sql=false --format=csv \
    "SELECT COUNT(*) FROM nba_predictions.ml_feature_store_v2 WHERE game_date = '$DATE'" 2>/dev/null | tail -1)
if [[ "$FEATURE_COUNT" -gt 0 ]]; then
    check_result "Feature store" "ok" "$FEATURE_COUNT features for $DATE"
else
    check_result "Feature store" "warning" "No features for $DATE"
fi
echo ""

# 3. DATA GAPS
echo -e "${BLUE}[3] DATA GAPS${NC}"
OPEN_GAPS=$(bq query --use_legacy_sql=false --format=csv \
    "SELECT COUNT(*) FROM nba_orchestration.data_gaps WHERE status = 'open'" 2>/dev/null | tail -1)
if [[ "$OPEN_GAPS" == "0" ]]; then
    check_result "Data gaps" "ok" "No open gaps"
else
    check_result "Data gaps" "warning" "$OPEN_GAPS open gaps"
fi
echo ""

# 4. PIPELINE ERRORS (last 24h)
echo -e "${BLUE}[4] PIPELINE ERRORS (last 24h)${NC}"
ERROR_COUNT=$(bq query --use_legacy_sql=false --format=csv \
    "SELECT COUNT(*) FROM nba_orchestration.pipeline_event_log 
     WHERE event_type LIKE '%error%' 
     AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)" 2>/dev/null | tail -1)
if [[ "$ERROR_COUNT" == "0" ]]; then
    check_result "Pipeline errors" "ok" "No errors in last 24h"
elif [[ "$ERROR_COUNT" -lt 10 ]]; then
    check_result "Pipeline errors" "warning" "$ERROR_COUNT errors in last 24h"
else
    check_result "Pipeline errors" "error" "$ERROR_COUNT errors in last 24h"
fi
echo ""

# Summary
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
if [[ $ERRORS -gt 0 ]]; then
    echo -e "${RED}STATUS: $ERRORS ERRORS, $WARNINGS WARNINGS${NC}"
    exit 1
elif [[ $WARNINGS -gt 0 ]]; then
    echo -e "${YELLOW}STATUS: $WARNINGS WARNINGS${NC}"
    exit 0
else
    echo -e "${GREEN}STATUS: ALL CHECKS PASSED${NC}"
    exit 0
fi
