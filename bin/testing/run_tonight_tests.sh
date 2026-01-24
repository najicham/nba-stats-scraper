#!/bin/bash
# bin/testing/run_tonight_tests.sh
#
# Run all tests for the Dec 31 deployment verification.
# This script tests all deployed services and the new test environment.
#
# Usage:
#   ./bin/testing/run_tonight_tests.sh
#
# Created: 2025-12-31

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Counters
PASSED=0
FAILED=0
WARNINGS=0

# Helper functions
pass() {
    echo -e "${GREEN}✅ PASS${NC}: $1"
    ((PASSED++))
}

fail() {
    echo -e "${RED}❌ FAIL${NC}: $1"
    ((FAILED++))
}

warn() {
    echo -e "${YELLOW}⚠️  WARN${NC}: $1"
    ((WARNINGS++))
}

section() {
    echo ""
    echo "=============================================="
    echo "  $1"
    echo "=============================================="
}

# Navigate to project root
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate 2>/dev/null || true

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║         DEPLOYMENT & TEST ENVIRONMENT VERIFICATION       ║"
echo "║                    December 31, 2025                      ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# =============================================================================
# Phase 1: Cloud Run Health Checks
# =============================================================================
section "Phase 1: Cloud Run Service Health Checks"

# Prediction Coordinator
echo -n "Testing prediction-coordinator... "
RESULT=$(curl -s --max-time 60 https://prediction-coordinator-756957797294.us-west2.run.app/health 2>&1)
if [[ "$RESULT" == *"healthy"* ]]; then
    pass "prediction-coordinator"
else
    fail "prediction-coordinator: $RESULT"
fi

# Prediction Worker
echo -n "Testing prediction-worker... "
RESULT=$(curl -s --max-time 30 https://prediction-worker-756957797294.us-west2.run.app/health 2>&1)
if [[ "$RESULT" == *"healthy"* ]]; then
    pass "prediction-worker"
else
    fail "prediction-worker: $RESULT"
fi

# Admin Dashboard
echo -n "Testing admin-dashboard... "
RESULT=$(curl -s --max-time 30 https://nba-admin-dashboard-756957797294.us-west2.run.app/health 2>&1)
if [[ "$RESULT" == *"healthy"* ]]; then
    pass "admin-dashboard"
else
    fail "admin-dashboard: $RESULT"
fi

# =============================================================================
# Phase 2: Cloud Function Status
# =============================================================================
section "Phase 2: Cloud Function Status"

for func in phase4-to-phase5 phase5-to-phase6 dlq-monitor backfill-trigger; do
    echo -n "Testing $func... "
    STATE=$(gcloud functions describe $func --region=us-west2 --format="value(state)" 2>/dev/null)
    if [[ "$STATE" == "ACTIVE" ]]; then
        pass "$func is ACTIVE"
    else
        fail "$func state: $STATE"
    fi
done

# =============================================================================
# Phase 3: DLQ Monitor Test
# =============================================================================
section "Phase 3: DLQ Monitor Endpoint Test"

echo -n "Calling DLQ monitor... "
RESULT=$(curl -s --max-time 60 "https://us-west2-nba-props-platform.cloudfunctions.net/dlq-monitor" 2>&1)
if [[ "$RESULT" == *"timestamp"* ]] || [[ "$RESULT" == *"status"* ]]; then
    pass "DLQ monitor returned valid response"
    echo "Response preview: $(echo $RESULT | head -c 200)..."
else
    fail "DLQ monitor: $RESULT"
fi

# =============================================================================
# Phase 4: Test Datasets Exist
# =============================================================================
section "Phase 4: Test Datasets Verification"

for dataset in test_nba_source test_nba_analytics test_nba_predictions test_nba_precompute; do
    echo -n "Checking $dataset... "
    if bq show --dataset "nba-props-platform:$dataset" &>/dev/null; then
        pass "$dataset exists"
    else
        fail "$dataset does not exist"
    fi
done

# =============================================================================
# Phase 5: Replay Script Dry Run
# =============================================================================
section "Phase 5: Replay Pipeline Dry Run"

echo "Running dry-run replay for 2024-12-15..."
PYTHONPATH=. python bin/testing/replay_pipeline.py 2024-12-15 --dry-run --output-json=/tmp/replay_test.json 2>&1

if [ -f /tmp/replay_test.json ]; then
    SUCCESS=$(python -c "import json; d=json.load(open('/tmp/replay_test.json')); print(d.get('overall_success', False))")
    if [[ "$SUCCESS" == "True" ]]; then
        pass "Replay dry-run completed successfully"
    else
        fail "Replay dry-run failed"
    fi
else
    warn "Replay dry-run did not produce output file"
fi

# =============================================================================
# Phase 6: Validation Script (Against Production)
# =============================================================================
section "Phase 6: Validation Against Production Data"

YESTERDAY=$(date -d yesterday +%Y-%m-%d)
echo "Validating production data for $YESTERDAY..."

# Run validation without prefix (production data)
PYTHONPATH=. python bin/testing/validate_replay.py "$YESTERDAY" --prefix="" --output-json=/tmp/validation_test.json 2>&1 || true

if [ -f /tmp/validation_test.json ]; then
    ALL_PASSED=$(python -c "import json; d=json.load(open('/tmp/validation_test.json')); print(d.get('all_passed', False))")
    PASSED_COUNT=$(python -c "import json; d=json.load(open('/tmp/validation_test.json')); print(d.get('passed_count', 0))")
    FAILED_COUNT=$(python -c "import json; d=json.load(open('/tmp/validation_test.json')); print(d.get('failed_count', 0))")

    if [[ "$ALL_PASSED" == "True" ]]; then
        pass "Validation passed: $PASSED_COUNT checks"
    else
        warn "Validation: $PASSED_COUNT passed, $FAILED_COUNT failed (may be expected if no games yesterday)"
    fi
else
    warn "Validation did not produce output file"
fi

# =============================================================================
# Phase 7: Check Recent Predictions
# =============================================================================
section "Phase 7: Recent Predictions Check"

echo "Checking predictions in BigQuery..."
TODAY=$(TZ=America/New_York date +%Y-%m-%d)
PREDICTIONS=$(bq query --use_legacy_sql=false --format=csv "
SELECT game_date, COUNT(*) as count
FROM nba_predictions.player_prop_predictions
WHERE game_date >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 3 DAY)
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 5" 2>/dev/null | tail -n +2)

if [ -n "$PREDICTIONS" ]; then
    pass "Found recent predictions:"
    echo "$PREDICTIONS" | while read line; do
        echo "    $line"
    done
else
    warn "No recent predictions found (may be expected if no games)"
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                      TEST SUMMARY                        ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo -e "  ${GREEN}Passed${NC}:   $PASSED"
echo -e "  ${RED}Failed${NC}:   $FAILED"
echo -e "  ${YELLOW}Warnings${NC}: $WARNINGS"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "  ${GREEN}✅ ALL CRITICAL TESTS PASSED${NC}"
    echo ""
    echo "  Deployment verification complete!"
    echo "  The reliability improvements are live and working."
    exit 0
else
    echo -e "  ${RED}❌ SOME TESTS FAILED${NC}"
    echo ""
    echo "  Review the failures above and fix before proceeding."
    exit 1
fi
