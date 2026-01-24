#!/bin/bash
# bin/testing/mlb/run_mlb_tests.sh
#
# MLB Deployment Verification Tests
#
# Runs a comprehensive test suite to verify MLB pipeline components:
#   Phase 1: Cloud Run Health Checks
#   Phase 2: BigQuery Dataset Verification
#   Phase 3: Model Availability
#   Phase 4: Pipeline Replay (dry run)
#   Phase 5: Recent Data Check
#
# Usage:
#   ./bin/testing/mlb/run_mlb_tests.sh              # Run all tests
#   ./bin/testing/mlb/run_mlb_tests.sh --quick      # Quick health check only
#   ./bin/testing/mlb/run_mlb_tests.sh --verbose    # Show detailed output
#
# Exit codes:
#   0 = All tests passed
#   1 = Some tests failed
#   2 = Critical failure
#
# Created: 2026-01-15
# Part of MLB E2E Test System

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"
QUICK_MODE=false
VERBOSE=false

# Parse arguments
for arg in "$@"; do
    case $arg in
        --quick)
            QUICK_MODE=true
            ;;
        --verbose)
            VERBOSE=true
            ;;
    esac
done

# Cloud Run URLs
PREDICTION_WORKER_URL="https://mlb-prediction-worker-756957797294.us-west2.run.app"
GRADING_SERVICE_URL="https://mlb-grading-service-756957797294.us-west2.run.app"

# Test counters
PASSED=0
FAILED=0
WARNINGS=0

# Helper functions
log_test() {
    echo -e "\n${YELLOW}[$1]${NC} $2"
}

log_pass() {
    echo -e "  ${GREEN}PASS${NC} $1"
    ((PASSED++))
}

log_fail() {
    echo -e "  ${RED}FAIL${NC} $1"
    ((FAILED++))
}

log_warn() {
    echo -e "  ${YELLOW}WARN${NC} $1"
    ((WARNINGS++))
}

log_info() {
    if [[ "$VERBOSE" == "true" ]]; then
        echo -e "  INFO: $1"
    fi
}

echo "=============================================="
echo "  MLB Deployment Verification Tests"
echo "=============================================="
echo "Project:    $PROJECT_ID"
echo "Quick Mode: $QUICK_MODE"
echo "Verbose:    $VERBOSE"
echo "=============================================="

# =============================================================================
# PHASE 1: Cloud Run Health Checks
# =============================================================================
log_test "PHASE 1" "Cloud Run Health Checks"

# Prediction Worker
echo -n "  Testing Prediction Worker... "
WORKER_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$PREDICTION_WORKER_URL/health" 2>/dev/null || echo "000")
if [[ "$WORKER_STATUS" == "200" ]]; then
    log_pass "Prediction Worker (HTTP $WORKER_STATUS)"
else
    log_fail "Prediction Worker (HTTP $WORKER_STATUS)"
fi

# Get worker info
if [[ "$VERBOSE" == "true" ]]; then
    WORKER_INFO=$(curl -s "$PREDICTION_WORKER_URL/" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"  Model: {d.get('model_version','?')}, Status: {d.get('status','?')}\")" 2>/dev/null || echo "  Could not get worker info")
    echo "$WORKER_INFO"
fi

# Grading Service (if deployed)
echo -n "  Testing Grading Service... "
GRADING_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$GRADING_SERVICE_URL/health" 2>/dev/null || echo "000")
if [[ "$GRADING_STATUS" == "200" ]]; then
    log_pass "Grading Service (HTTP $GRADING_STATUS)"
elif [[ "$GRADING_STATUS" == "000" ]]; then
    log_warn "Grading Service not deployed"
else
    log_fail "Grading Service (HTTP $GRADING_STATUS)"
fi

if [[ "$QUICK_MODE" == "true" ]]; then
    echo ""
    echo "=============================================="
    echo "  Quick Mode - Skipping remaining phases"
    echo "=============================================="
    echo ""
    echo "Results: $PASSED passed, $FAILED failed, $WARNINGS warnings"
    exit $([[ $FAILED -gt 0 ]] && echo 1 || echo 0)
fi

# =============================================================================
# PHASE 2: BigQuery Dataset Verification
# =============================================================================
log_test "PHASE 2" "BigQuery Dataset Verification"

# Check mlb_raw
echo -n "  Checking mlb_raw dataset... "
if bq show --dataset "${PROJECT_ID}:mlb_raw" &>/dev/null; then
    TABLE_COUNT=$(bq ls "${PROJECT_ID}:mlb_raw" 2>/dev/null | grep -c TABLE || echo "0")
    log_pass "mlb_raw ($TABLE_COUNT tables)"
else
    log_fail "mlb_raw dataset not found"
fi

# Check mlb_analytics
echo -n "  Checking mlb_analytics dataset... "
if bq show --dataset "${PROJECT_ID}:mlb_analytics" &>/dev/null; then
    TABLE_COUNT=$(bq ls "${PROJECT_ID}:mlb_analytics" 2>/dev/null | grep -c TABLE || echo "0")
    log_pass "mlb_analytics ($TABLE_COUNT tables)"
else
    log_fail "mlb_analytics dataset not found"
fi

# Check mlb_predictions
echo -n "  Checking mlb_predictions dataset... "
if bq show --dataset "${PROJECT_ID}:mlb_predictions" &>/dev/null; then
    TABLE_COUNT=$(bq ls "${PROJECT_ID}:mlb_predictions" 2>/dev/null | grep -c TABLE || echo "0")
    log_pass "mlb_predictions ($TABLE_COUNT tables)"
else
    log_fail "mlb_predictions dataset not found"
fi

# Check key tables exist
echo -n "  Checking pitcher_game_summary... "
if bq show "${PROJECT_ID}:mlb_analytics.pitcher_game_summary" &>/dev/null; then
    log_pass "pitcher_game_summary exists"
else
    log_fail "pitcher_game_summary not found"
fi

# =============================================================================
# PHASE 3: Model Availability
# =============================================================================
log_test "PHASE 3" "Model Availability"

# Check V1.4 model
echo -n "  Checking V1.4 model... "
V1_4_MODEL="gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_4features_20260114_142456.json"
if gsutil -q stat "$V1_4_MODEL" 2>/dev/null; then
    log_pass "V1.4 model available"
else
    log_fail "V1.4 model not found"
fi

# Check V1.6 model
echo -n "  Checking V1.6 model... "
V1_6_MODEL="gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json"
if gsutil -q stat "$V1_6_MODEL" 2>/dev/null; then
    log_pass "V1.6 model available"
else
    log_fail "V1.6 model not found"
fi

# =============================================================================
# PHASE 4: Pipeline Replay (Dry Run)
# =============================================================================
log_test "PHASE 4" "Pipeline Replay Test (Dry Run)"

echo -n "  Running replay dry run... "
cd "$(dirname "$0")/../../.."

REPLAY_OUTPUT=$(PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-09-28 --dry-run 2>&1)
REPLAY_EXIT=$?

if [[ $REPLAY_EXIT -eq 0 ]]; then
    log_pass "Pipeline replay dry run"
else
    log_fail "Pipeline replay dry run (exit code $REPLAY_EXIT)"
    if [[ "$VERBOSE" == "true" ]]; then
        echo "$REPLAY_OUTPUT" | tail -20
    fi
fi

# =============================================================================
# PHASE 5: Recent Data Check
# =============================================================================
log_test "PHASE 5" "Recent Data Check"

# Check for recent pitcher stats
echo -n "  Checking recent pitcher stats... "
RECENT_STATS=$(bq query --nouse_legacy_sql --format=csv \
    "SELECT MAX(game_date) as max_date FROM \`${PROJECT_ID}.mlb_raw.mlb_pitcher_stats\` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 180 DAY)" 2>/dev/null | tail -1)

if [[ -n "$RECENT_STATS" && "$RECENT_STATS" != "null" && "$RECENT_STATS" != "" ]]; then
    log_pass "Recent pitcher stats (latest: $RECENT_STATS)"
else
    log_warn "No recent pitcher stats (expected during off-season)"
fi

# Check for recent props
echo -n "  Checking recent betting props... "
RECENT_PROPS=$(bq query --nouse_legacy_sql --format=csv \
    "SELECT MAX(game_date) as max_date FROM \`${PROJECT_ID}.mlb_raw.oddsa_pitcher_props\` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 180 DAY)" 2>/dev/null | tail -1)

if [[ -n "$RECENT_PROPS" && "$RECENT_PROPS" != "null" && "$RECENT_PROPS" != "" ]]; then
    log_pass "Recent betting props (latest: $RECENT_PROPS)"
else
    log_warn "No recent betting props (expected during off-season)"
fi

# Check pitcher_game_summary date range
echo -n "  Checking analytics data range... "
ANALYTICS_RANGE=$(bq query --nouse_legacy_sql --format=csv \
    "SELECT MIN(game_date) as min_date, MAX(game_date) as max_date FROM \`${PROJECT_ID}.mlb_analytics.pitcher_game_summary\`" 2>/dev/null | tail -1)

if [[ -n "$ANALYTICS_RANGE" ]]; then
    log_pass "Analytics data range: $ANALYTICS_RANGE"
else
    log_fail "Could not query analytics data range"
fi

# =============================================================================
# SUMMARY
# =============================================================================
echo ""
echo "=============================================="
echo "  TEST SUMMARY"
echo "=============================================="
echo -e "  ${GREEN}Passed:${NC}   $PASSED"
echo -e "  ${RED}Failed:${NC}   $FAILED"
echo -e "  ${YELLOW}Warnings:${NC} $WARNINGS"
echo "=============================================="

if [[ $FAILED -gt 0 ]]; then
    echo -e "\n${RED}Some tests failed. Review output above.${NC}"
    exit 1
elif [[ $WARNINGS -gt 0 ]]; then
    echo -e "\n${YELLOW}All tests passed with warnings.${NC}"
    exit 0
else
    echo -e "\n${GREEN}All tests passed!${NC}"
    exit 0
fi
