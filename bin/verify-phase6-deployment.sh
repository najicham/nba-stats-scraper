#!/usr/bin/env bash
#
# Phase 6 Deployment Verification Script
#
# Run this after the morning prediction run (7:30 AM ET / 12:30 UTC)
# to verify both Phase 6 exports and model attribution are working.
#
# Usage:
#   ./bin/verify-phase6-deployment.sh
#

set -euo pipefail

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

PASSED=0
FAILED=0
WARNINGS=0

echo "=========================================="
echo "Phase 6 Deployment Verification"
echo "=========================================="
echo "Date: $(date)"
echo ""

# Function to check status
check() {
    local name=$1
    local command=$2
    local expected=$3

    echo -e "${BLUE}Checking: $name${NC}"

    if result=$(eval "$command" 2>&1); then
        if [[ "$result" == *"$expected"* ]] || [[ "$expected" == "any" ]]; then
            echo -e "  ${GREEN}✓ PASS${NC}: $name"
            ((PASSED++))
            return 0
        else
            echo -e "  ${RED}✗ FAIL${NC}: $name"
            echo -e "  Expected: $expected"
            echo -e "  Got: $result"
            ((FAILED++))
            return 1
        fi
    else
        echo -e "  ${RED}✗ ERROR${NC}: $name"
        echo -e "  $result"
        ((FAILED++))
        return 1
    fi
}

warn() {
    local message=$1
    echo -e "  ${YELLOW}⚠ WARNING${NC}: $message"
    ((WARNINGS++))
}

echo "=========================================="
echo "1. Model Attribution Verification"
echo "=========================================="
echo ""

# Check if today's predictions have model attribution
echo -e "${BLUE}Checking model attribution for today's predictions...${NC}"
ATTRIBUTION_RESULT=$(bq query --use_legacy_sql=false --format=csv "
SELECT
  COUNT(*) as total,
  COUNT(model_file_name) as with_attribution,
  MAX(model_file_name) as example_model
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
" 2>&1 | tail -n +2)

TOTAL=$(echo "$ATTRIBUTION_RESULT" | cut -d',' -f1)
WITH_ATTR=$(echo "$ATTRIBUTION_RESULT" | cut -d',' -f2)
EXAMPLE_MODEL=$(echo "$ATTRIBUTION_RESULT" | cut -d',' -f3)

echo "  Total predictions: $TOTAL"
echo "  With attribution: $WITH_ATTR"
echo "  Example model: $EXAMPLE_MODEL"
echo ""

if [[ "$TOTAL" == "0" ]]; then
    warn "No predictions found for today yet. Run this after 7:30 AM ET."
elif [[ "$WITH_ATTR" == "$TOTAL" ]] && [[ "$EXAMPLE_MODEL" != "" ]]; then
    echo -e "  ${GREEN}✓ PASS${NC}: Model attribution working correctly"
    ((PASSED++))
else
    echo -e "  ${RED}✗ FAIL${NC}: Model attribution still NULL or incomplete"
    echo -e "  Expected: All predictions with model_file_name populated"
    echo -e "  Got: $WITH_ATTR/$TOTAL predictions with attribution"
    ((FAILED++))
fi

echo ""
echo "=========================================="
echo "2. Phase 6 Export Files Verification"
echo "=========================================="
echo ""

TODAY=$(date +%Y-%m-%d)

# Check picks file
echo -e "${BLUE}Checking picks file...${NC}"
if gsutil ls "gs://nba-props-platform-api/v1/picks/$TODAY.json" &>/dev/null; then
    echo -e "  ${GREEN}✓ PASS${NC}: Picks file exists"
    ((PASSED++))

    # Verify structure
    PICKS_DATA=$(gsutil cat "gs://nba-props-platform-api/v1/picks/$TODAY.json" 2>/dev/null)
    GROUPS=$(echo "$PICKS_DATA" | jq -r '.groups | length' 2>/dev/null || echo "0")

    if [[ "$GROUPS" == "9" ]]; then
        echo -e "  ${GREEN}✓ PASS${NC}: Picks file has 9 groups"
        ((PASSED++))
    else
        echo -e "  ${RED}✗ FAIL${NC}: Expected 9 groups, got $GROUPS"
        ((FAILED++))
    fi

    # Security check
    if echo "$PICKS_DATA" | grep -qiE "(system_id|subset_id|catboost|v9_|confidence|edge)"; then
        echo -e "  ${RED}✗ FAIL${NC}: Security leak detected in picks file"
        ((FAILED++))
    else
        echo -e "  ${GREEN}✓ PASS${NC}: No security leaks in picks file"
        ((PASSED++))
    fi
else
    echo -e "  ${RED}✗ FAIL${NC}: Picks file not found"
    warn "File should exist after predictions complete. Check orchestrator logs."
    ((FAILED++))
fi

echo ""

# Check signals file
echo -e "${BLUE}Checking signals file...${NC}"
if gsutil ls "gs://nba-props-platform-api/v1/signals/$TODAY.json" &>/dev/null; then
    echo -e "  ${GREEN}✓ PASS${NC}: Signals file exists"
    ((PASSED++))

    SIGNAL=$(gsutil cat "gs://nba-props-platform-api/v1/signals/$TODAY.json" 2>/dev/null | jq -r '.signal' 2>/dev/null || echo "none")
    if [[ "$SIGNAL" =~ ^(favorable|neutral|challenging)$ ]]; then
        echo -e "  ${GREEN}✓ PASS${NC}: Signal value valid: $SIGNAL"
        ((PASSED++))
    else
        echo -e "  ${RED}✗ FAIL${NC}: Invalid signal value: $SIGNAL"
        ((FAILED++))
    fi
else
    echo -e "  ${RED}✗ FAIL${NC}: Signals file not found"
    ((FAILED++))
fi

echo ""

# Check performance file
echo -e "${BLUE}Checking performance file...${NC}"
if gsutil ls "gs://nba-props-platform-api/v1/subsets/performance.json" &>/dev/null; then
    echo -e "  ${GREEN}✓ PASS${NC}: Performance file exists"
    ((PASSED++))

    PERF_DATA=$(gsutil cat "gs://nba-props-platform-api/v1/subsets/performance.json" 2>/dev/null)
    WINDOWS=$(echo "$PERF_DATA" | jq -r '.windows | keys | length' 2>/dev/null || echo "0")

    if [[ "$WINDOWS" == "3" ]]; then
        echo -e "  ${GREEN}✓ PASS${NC}: Performance file has 3 time windows"
        ((PASSED++))
    else
        echo -e "  ${RED}✗ FAIL${NC}: Expected 3 windows, got $WINDOWS"
        ((FAILED++))
    fi
else
    echo -e "  ${RED}✗ FAIL${NC}: Performance file not found"
    ((FAILED++))
fi

echo ""

# Check definitions file
echo -e "${BLUE}Checking definitions file...${NC}"
if gsutil ls "gs://nba-props-platform-api/v1/systems/subsets.json" &>/dev/null; then
    echo -e "  ${GREEN}✓ PASS${NC}: Definitions file exists"
    ((PASSED++))
else
    echo -e "  ${RED}✗ FAIL${NC}: Definitions file not found"
    ((FAILED++))
fi

echo ""
echo "=========================================="
echo "3. Orchestrator Health Check"
echo "=========================================="
echo ""

echo -e "${BLUE}Checking recent orchestrator logs...${NC}"
RECENT_LOGS=$(gcloud logging read 'resource.labels.function_name="phase5-to-phase6"
  AND timestamp>="'$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ)'"
  AND severity>=WARNING' --limit=5 --format="value(severity,textPayload)" 2>/dev/null || echo "")

if [[ -z "$RECENT_LOGS" ]]; then
    echo -e "  ${GREEN}✓ PASS${NC}: No errors or warnings in last hour"
    ((PASSED++))
else
    echo -e "  ${YELLOW}⚠ WARNING${NC}: Found warnings/errors in logs:"
    echo "$RECENT_LOGS" | head -5
    ((WARNINGS++))
fi

echo ""
echo "=========================================="
echo "4. Data Quality Checks"
echo "=========================================="
echo ""

# Check for NULL team/opponent values
echo -e "${BLUE}Checking for NULL teams/opponents in picks...${NC}"
if gsutil ls "gs://nba-props-platform-api/v1/picks/$TODAY.json" &>/dev/null; then
    NULL_COUNT=$(gsutil cat "gs://nba-props-platform-api/v1/picks/$TODAY.json" 2>/dev/null | \
        jq '[.groups[].picks[] | select(.team == null or .opponent == null)] | length' 2>/dev/null || echo "0")

    if [[ "$NULL_COUNT" == "0" ]]; then
        echo -e "  ${GREEN}✓ PASS${NC}: No NULL team/opponent values"
        ((PASSED++))
    else
        echo -e "  ${RED}✗ FAIL${NC}: Found $NULL_COUNT picks with NULL team/opponent"
        ((FAILED++))
    fi
fi

echo ""

# Check ROI values are reasonable
echo -e "${BLUE}Checking ROI values are reasonable...${NC}"
EXTREME_ROI=$(bq query --use_legacy_sql=false --format=csv "
SELECT subset_id,
  ROUND(100.0 * SUM(wins * 0.909 - (graded_picks - wins)) /
    NULLIF(SUM(graded_picks), 0), 1) as roi_pct
FROM nba_predictions.v_dynamic_subset_performance
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY subset_id
HAVING ABS(roi_pct) > 100
" 2>&1 | tail -n +2)

if [[ -z "$EXTREME_ROI" ]]; then
    echo -e "  ${GREEN}✓ PASS${NC}: All ROI values reasonable (within ±100%)"
    ((PASSED++))
else
    echo -e "  ${RED}✗ FAIL${NC}: Found extreme ROI values:"
    echo "$EXTREME_ROI"
    ((FAILED++))
fi

echo ""
echo "=========================================="
echo "Summary"
echo "=========================================="
echo ""
echo -e "${GREEN}Passed:${NC}   $PASSED"
echo -e "${RED}Failed:${NC}   $FAILED"
echo -e "${YELLOW}Warnings:${NC} $WARNINGS"
echo ""

if [[ $FAILED -eq 0 ]]; then
    echo -e "${GREEN}✓ ALL CHECKS PASSED!${NC}"
    echo ""
    echo "Phase 6 deployment is working correctly."
    echo "Ready to proceed with Phase 2 (Model Attribution Exporters)."
    exit 0
elif [[ $FAILED -le 2 ]]; then
    echo -e "${YELLOW}⚠ SOME CHECKS FAILED${NC}"
    echo ""
    echo "Minor issues detected. Review failures above."
    exit 1
else
    echo -e "${RED}✗ MULTIPLE CHECKS FAILED${NC}"
    echo ""
    echo "Significant issues detected. Investigate before proceeding."
    exit 2
fi
