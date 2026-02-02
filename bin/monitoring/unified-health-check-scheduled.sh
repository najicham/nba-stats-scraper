#!/bin/bash
#
# Unified Health Check - NBA Props Platform (Scheduled Version)
#
# Simplified version for Cloud Scheduler execution - skips deployment drift check
# which is handled separately by GitHub Actions.
#
# Runs critical monitors and returns overall system health score.
#
# Usage:
#   ./bin/monitoring/unified-health-check-scheduled.sh [--verbose]
#
# Exit codes:
#   0 = All systems healthy (score ≥80)
#   1 = System degraded (score 50-79)
#   2 = System critical (score <50 or any critical failures)

set -euo pipefail

# Parse arguments
VERBOSE=false
if [[ "${1:-}" == "--verbose" ]]; then
    VERBOSE=true
fi

TOTAL_CHECKS=0
PASSED_CHECKS=0
CRITICAL_FAILURES=0

echo "=== NBA Props Platform - Health Check (Scheduled) ==="
echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Check 1: Vegas Line Coverage
echo "[1/5] Vegas Line Coverage..."
if $VERBOSE; then
    ./bin/monitoring/check_vegas_line_coverage.sh --days 1 || CHECK_RESULT=$?
    CHECK_RESULT=${CHECK_RESULT:-0}
else
    OUTPUT=$(./bin/monitoring/check_vegas_line_coverage.sh --days 1 2>&1) || CHECK_RESULT=$?
    CHECK_RESULT=${CHECK_RESULT:-0}
fi

if [[ $CHECK_RESULT -eq 0 ]]; then
    echo "✅ PASS"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
elif [[ $CHECK_RESULT -eq 1 ]]; then
    echo "🟡 WARNING"
    if ! $VERBOSE && [[ -n "${OUTPUT:-}" ]]; then echo "$OUTPUT"; fi
else
    echo "🔴 CRITICAL FAILURE"
    CRITICAL_FAILURES=$((CRITICAL_FAILURES + 1))
    if ! $VERBOSE && [[ -n "${OUTPUT:-}" ]]; then echo "$OUTPUT"; fi
fi
TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

# Check 2: Grading Completeness
echo "[2/5] Grading Completeness..."
if $VERBOSE; then
    ./bin/monitoring/check_grading_completeness.sh --days 3 || CHECK_RESULT=$?
    CHECK_RESULT=${CHECK_RESULT:-0}
else
    OUTPUT=$(./bin/monitoring/check_grading_completeness.sh --days 3 2>&1) || CHECK_RESULT=$?
    CHECK_RESULT=${CHECK_RESULT:-0}
fi

if [[ $CHECK_RESULT -eq 0 ]]; then
    echo "✅ PASS"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
elif [[ $CHECK_RESULT -eq 1 ]]; then
    echo "🟡 WARNING"
    if ! $VERBOSE && [[ -n "${OUTPUT:-}" ]]; then echo "$OUTPUT"; fi
else
    echo "🔴 CRITICAL FAILURE"
    CRITICAL_FAILURES=$((CRITICAL_FAILURES + 1))
    if ! $VERBOSE && [[ -n "${OUTPUT:-}" ]]; then echo "$OUTPUT"; fi
fi
TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

# Check 3: Phase 3 Completion (yesterday)
echo "[3/5] Phase 3 Completion..."
COMPLETE=$(python3 -c "
from google.cloud import firestore
from datetime import datetime, timedelta
db = firestore.Client()
date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
doc = db.collection('phase3_completion').document(date).get()
if doc.exists:
    data = doc.to_dict()
    print(len([k for k in data.keys() if not k.startswith('_')]))
else:
    print(0)
" 2>/dev/null || echo "0")

if [[ $COMPLETE -eq 5 ]]; then
    echo "✅ PASS (5/5)"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
elif [[ $COMPLETE -ge 3 ]]; then
    echo "🟡 WARNING ($COMPLETE/5)"
else
    echo "🔴 CRITICAL FAILURE ($COMPLETE/5)"
    CRITICAL_FAILURES=$((CRITICAL_FAILURES + 1))
fi
TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

# Check 4: Recent Predictions (today)
echo "[4/5] Recent Predictions..."
PRED_COUNT=$(bq query --use_legacy_sql=false --format=csv --quiet \
  "SELECT COUNT(*) FROM nba_predictions.player_prop_predictions
   WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'" 2>/dev/null | tail -1 || echo "0")

if [[ $PRED_COUNT -gt 100 ]]; then
    echo "✅ PASS ($PRED_COUNT predictions)"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
elif [[ $PRED_COUNT -gt 50 ]]; then
    echo "🟡 WARNING ($PRED_COUNT predictions - expected >100)"
else
    echo "🔴 CRITICAL FAILURE ($PRED_COUNT predictions)"
    CRITICAL_FAILURES=$((CRITICAL_FAILURES + 1))
fi
TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

# Check 5: BDB Coverage (yesterday)
echo "[5/5] BDB Play-by-Play Coverage..."
BDB_COV=$(bq query --use_legacy_sql=false --format=csv --quiet \
  "WITH schedule AS (
     SELECT COUNT(*) as total FROM nba_reference.nba_schedule
     WHERE game_date = CURRENT_DATE() - 1 AND game_status = 3
   ),
   bdb AS (
     SELECT COUNT(DISTINCT LPAD(CAST(bdb_game_id AS STRING), 10, '0')) as has_bdb
     FROM nba_raw.bigdataball_play_by_play
     WHERE game_date = CURRENT_DATE() - 1
   )
   SELECT CAST(ROUND(100.0 * COALESCE(has_bdb, 0) / NULLIF(total, 0), 0) AS INT64) FROM schedule, bdb" 2>/dev/null | tail -1 || echo "0")

# Handle NULL/empty result
BDB_COV=${BDB_COV:-0}
# Remove any decimal point that might slip through
BDB_COV=${BDB_COV%.*}

if [[ $BDB_COV -ge 90 ]]; then
    echo "✅ PASS ($BDB_COV%)"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
elif [[ $BDB_COV -ge 50 ]]; then
    echo "🟡 WARNING ($BDB_COV%)"
else
    echo "🔴 CRITICAL FAILURE ($BDB_COV%)"
    CRITICAL_FAILURES=$((CRITICAL_FAILURES + 1))
fi
TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

# Calculate health score
HEALTH_SCORE=$((100 * PASSED_CHECKS / TOTAL_CHECKS))

echo ""
echo "=== Health Summary ==="
echo "Checks Passed: $PASSED_CHECKS/$TOTAL_CHECKS"
echo "Health Score: $HEALTH_SCORE/100"
echo "Critical Failures: $CRITICAL_FAILURES"
echo ""
echo "Note: Deployment drift is monitored separately via GitHub Actions"
echo ""

# Determine overall status and exit code
if [[ $CRITICAL_FAILURES -gt 0 ]]; then
    echo "🔴 SYSTEM HEALTH: CRITICAL"
    EXIT_CODE=2
elif [[ $HEALTH_SCORE -lt 50 ]]; then
    echo "🔴 SYSTEM HEALTH: CRITICAL (low score)"
    EXIT_CODE=2
elif [[ $HEALTH_SCORE -lt 80 ]]; then
    echo "🟡 SYSTEM HEALTH: DEGRADED"
    EXIT_CODE=1
else
    echo "✅ SYSTEM HEALTH: OK"
    EXIT_CODE=0
fi

# Send alert if unhealthy and webhook configured
if [[ $EXIT_CODE -gt 0 ]] && [[ -n "${SLACK_WEBHOOK_URL_WARNING:-}" ]]; then
    STATUS_EMOJI="🟡"
    STATUS_TEXT="DEGRADED"
    WEBHOOK="$SLACK_WEBHOOK_URL_WARNING"

    if [[ $EXIT_CODE -eq 2 ]]; then
        STATUS_EMOJI="🔴"
        STATUS_TEXT="CRITICAL"
        WEBHOOK="${SLACK_WEBHOOK_URL_ERROR:-$SLACK_WEBHOOK_URL_WARNING}"
    fi

    curl -X POST "$WEBHOOK" \
        -H 'Content-Type: application/json' \
        -d "{
            \"text\": \"$STATUS_EMOJI System Health $STATUS_TEXT\",
            \"blocks\": [{
                \"type\": \"section\",
                \"text\": {
                    \"type\": \"mrkdwn\",
                    \"text\": \"*System Health Check: $STATUS_TEXT*\n\n*Health Score*: $HEALTH_SCORE/100\n*Checks Passed*: $PASSED_CHECKS/$TOTAL_CHECKS\n*Critical Failures*: $CRITICAL_FAILURES\n\n*Note*: Scheduled health check (deployment drift monitored separately)\"
                }
            }]
        }" 2>/dev/null || true
fi

exit $EXIT_CODE
