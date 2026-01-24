#!/bin/bash
# bin/testing/run_mlb_e2e_test.sh
#
# Run an end-to-end test of the MLB pipeline with a historical date.
# Tests Phase 3 → Phase 4 → Phase 5 → Phase 6 flow.
#
# Usage:
#   ./bin/testing/run_mlb_e2e_test.sh 2025-06-15
#   ./bin/testing/run_mlb_e2e_test.sh 2025-06-15 --test-env  # Use test datasets
#
# Created: 2026-01-07

set -euo pipefail

# Configuration
TEST_DATE="${1:-2025-06-15}"
USE_TEST_ENV=false
DATASET_PREFIX=""

# Check for --test-env flag
for arg in "$@"; do
    if [[ "$arg" == "--test-env" ]]; then
        USE_TEST_ENV=true
        DATASET_PREFIX="test_"
    fi
done

# Service URLs
PHASE3_URL="https://mlb-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app"
PHASE4_URL="https://mlb-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app"
PHASE5_URL="https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app"
PHASE6_URL="https://mlb-phase6-grading-f7p3g7f6ya-wl.a.run.app"

# Get auth token
TOKEN=$(gcloud auth print-identity-token)

echo "=============================================="
echo "  MLB Pipeline End-to-End Test"
echo "=============================================="
echo "Test Date:       $TEST_DATE"
echo "Test Env:        $USE_TEST_ENV"
echo "Dataset Prefix:  ${DATASET_PREFIX:-'(none - production)'}"
echo "=============================================="
echo ""

# Helper function to make authenticated request
call_service() {
    local URL=$1
    local DATA=$2
    local SERVICE_NAME=$3

    echo -n "  Calling $SERVICE_NAME... "

    RESPONSE=$(curl -s -X POST "$URL" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d "$DATA" \
        --max-time 300)

    # Check for errors
    if echo "$RESPONSE" | grep -q '"error"'; then
        echo "FAILED"
        echo "    Error: $RESPONSE"
        return 1
    elif echo "$RESPONSE" | grep -q '"status":\s*"error"'; then
        echo "FAILED"
        echo "    Error: $RESPONSE"
        return 1
    else
        echo "OK"
        echo "    Response: $(echo "$RESPONSE" | head -c 200)"
        return 0
    fi
}

# Check services are healthy
echo "=== Checking Service Health ==="
for svc in mlb-phase3-analytics-processors mlb-phase4-precompute-processors mlb-prediction-worker mlb-phase6-grading; do
    echo -n "  $svc: "
    HEALTH=$(curl -s "https://${svc}-f7p3g7f6ya-wl.a.run.app/health" | head -c 100)
    if echo "$HEALTH" | grep -q '"healthy"'; then
        echo "✓ healthy"
    elif echo "$HEALTH" | grep -q '"status":\s*"healthy"'; then
        echo "✓ healthy"
    else
        echo "? ($HEALTH)"
    fi
done
echo ""

# Check if we have raw data for this date
echo "=== Checking Raw Data Availability ==="
RAW_COUNT=$(bq query --use_legacy_sql=false --format=csv \
    "SELECT COUNT(*) as cnt FROM mlb_raw.mlb_pitcher_stats WHERE game_date = '$TEST_DATE'" 2>/dev/null | tail -1)
echo "  Raw pitcher stats for $TEST_DATE: $RAW_COUNT rows"

if [[ "$RAW_COUNT" == "0" ]]; then
    echo ""
    echo "WARNING: No raw data found for $TEST_DATE. The pipeline may not have data to process."
    echo "Consider using a date with known data (e.g., 2025-07-15, 2025-08-15)."
    echo ""
fi

echo ""
echo "=== Running Pipeline Phases ==="

# Phase 3: Analytics
echo ""
echo "[Phase 3: Analytics Processing]"
if [[ -n "$DATASET_PREFIX" ]]; then
    PHASE3_DATA="{\"game_date\": \"$TEST_DATE\", \"dataset_prefix\": \"$DATASET_PREFIX\"}"
else
    PHASE3_DATA="{\"game_date\": \"$TEST_DATE\"}"
fi
call_service "$PHASE3_URL/process-date" "$PHASE3_DATA" "Phase 3 Analytics"

# Phase 4: Precompute
echo ""
echo "[Phase 4: Precompute/Features]"
if [[ -n "$DATASET_PREFIX" ]]; then
    PHASE4_DATA="{\"game_date\": \"$TEST_DATE\", \"dataset_prefix\": \"$DATASET_PREFIX\"}"
else
    PHASE4_DATA="{\"game_date\": \"$TEST_DATE\"}"
fi
call_service "$PHASE4_URL/process-date" "$PHASE4_DATA" "Phase 4 Precompute"

# Phase 5: Predictions (test with a known pitcher)
echo ""
echo "[Phase 5: Predictions]"
# First check if we can make a prediction
PHASE5_DATA="{\"pitcher_lookup\": \"garrett_crochet\", \"game_date\": \"$TEST_DATE\", \"strikeouts_line\": 7.5}"
call_service "$PHASE5_URL/predict" "$PHASE5_DATA" "Phase 5 Prediction (Crochet)"

# Phase 6: Grading
echo ""
echo "[Phase 6: Grading]"
if [[ -n "$DATASET_PREFIX" ]]; then
    PHASE6_DATA="{\"game_date\": \"$TEST_DATE\", \"dataset_prefix\": \"$DATASET_PREFIX\"}"
else
    PHASE6_DATA="{\"game_date\": \"$TEST_DATE\"}"
fi
call_service "$PHASE6_URL/grade-date" "$PHASE6_DATA" "Phase 6 Grading"

echo ""
echo "=============================================="
echo "  Pipeline Test Complete"
echo "=============================================="
echo ""

# Verify results in BigQuery
echo "=== Verifying Results in BigQuery ==="
if [[ -n "$DATASET_PREFIX" ]]; then
    ANALYTICS_DS="${DATASET_PREFIX}mlb_analytics"
    PRECOMPUTE_DS="${DATASET_PREFIX}mlb_precompute"
    PREDICTIONS_DS="${DATASET_PREFIX}mlb_predictions"
else
    ANALYTICS_DS="mlb_analytics"
    PRECOMPUTE_DS="mlb_precompute"
    PREDICTIONS_DS="mlb_predictions"
fi

echo ""
echo "Analytics (pitcher_game_summary):"
bq query --use_legacy_sql=false --format=pretty \
    "SELECT COUNT(*) as rows, MAX(processed_at) as last_updated
     FROM \`nba-props-platform.$ANALYTICS_DS.pitcher_game_summary\`
     WHERE game_date = '$TEST_DATE'" 2>/dev/null || echo "  (table may not exist)"

echo ""
echo "Precompute (pitcher_ml_features):"
bq query --use_legacy_sql=false --format=pretty \
    "SELECT COUNT(*) as rows, MAX(created_at) as last_updated
     FROM \`nba-props-platform.$PRECOMPUTE_DS.pitcher_ml_features\`
     WHERE game_date = '$TEST_DATE'" 2>/dev/null || echo "  (table may not exist)"

echo ""
echo "Predictions (pitcher_strikeouts):"
bq query --use_legacy_sql=false --format=pretty \
    "SELECT COUNT(*) as rows, MAX(created_at) as last_updated
     FROM \`nba-props-platform.$PREDICTIONS_DS.pitcher_strikeouts\`
     WHERE game_date = '$TEST_DATE'" 2>/dev/null || echo "  (table may not exist)"

echo ""
echo "=============================================="
echo "  Test Summary"
echo "=============================================="
echo "Date tested: $TEST_DATE"
echo "Environment: ${USE_TEST_ENV:+test}${USE_TEST_ENV:-production}"
echo ""
echo "Next steps:"
echo "  - Check logs: gcloud logging read 'resource.labels.service_name=~\"mlb\"' --limit=50"
echo "  - Query results: bq query 'SELECT * FROM ${PREDICTIONS_DS}.pitcher_strikeouts WHERE game_date = \"$TEST_DATE\"'"
