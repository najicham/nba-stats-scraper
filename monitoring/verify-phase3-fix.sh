#!/bin/bash
#
# verify-phase3-fix.sh
#
# Quick verification script to check if Phase 3 fix resolved 503 errors
# Run this after the morning grading (6 AM ET / 11 AM UTC)
#
# Usage: ./monitoring/verify-phase3-fix.sh

set -euo pipefail

PROJECT_ID="nba-props-platform"
FIX_DEPLOYMENT_TIME="2026-01-18 05:13:00"

echo "🔍 Phase 3 Fix Verification Report"
echo "===================================="
echo "Fix deployed: $FIX_DEPLOYMENT_TIME UTC"
echo "Current time: $(date -u)"
echo ""

# Test 1: Check for 503 errors AFTER fix deployment
echo "1️⃣  Checking for 503 errors after fix deployment..."
echo "   Searching logs from Jan 18 05:13 UTC onwards..."
POST_FIX_LOGS=$(gcloud functions logs read phase5b-grading --region=us-west2 --limit=200 2>/dev/null | \
  awk '/2026-01-18 05:1[3-9]|2026-01-18 [0-9][6-9]|2026-01-1[89]/')

if echo "$POST_FIX_LOGS" | grep -q "503"; then
  ERROR_COUNT=$(echo "$POST_FIX_LOGS" | grep -c "503")
  echo "   ❌ FAIL: Found $ERROR_COUNT 503 errors after fix"
  echo "   ACTION: Verify minScale=1 on Phase 3 service"
  echo "$POST_FIX_LOGS" | grep "503" | head -3 | sed 's/^/   /'
else
  echo "   ✅ PASS: No 503 errors found after fix deployment"
fi

# Test 2: Check grading coverage for Jan 16-17
echo ""
echo "2️⃣  Checking grading coverage for Jan 16-17..."
COVERAGE_RESULT=$(bq query --use_legacy_sql=false --format=csv '
SELECT
  game_date,
  COUNT(*) as graded,
  CASE
    WHEN game_date = "2026-01-16" THEN ROUND(COUNT(*) * 100.0 / 268, 1)
    WHEN game_date = "2026-01-17" THEN ROUND(COUNT(*) * 100.0 / 217, 1)
    ELSE 0
  END as coverage_pct
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date IN ("2026-01-16", "2026-01-17")
GROUP BY game_date
ORDER BY game_date DESC
' 2>/dev/null | tail -n +2)

if [ -z "$COVERAGE_RESULT" ]; then
  echo "   ⏳ INFO: Jan 16-17 not graded yet (expected - grading hasn't run since fix)"
  echo "   Next grading: 6 AM ET / 11 AM UTC"
else
  echo "$COVERAGE_RESULT" | while IFS=',' read -r date graded pct; do
    if (( $(echo "$pct >= 70" | bc -l) )); then
      echo "   ✅ $date: $graded graded ($pct%)"
    else
      echo "   ⚠️  $date: $graded graded ($pct% - below 70% target)"
    fi
  done
fi

# Test 3: Check Phase 3 auto-heal success
echo ""
echo "3️⃣  Checking Phase 3 auto-heal success (after fix)..."
AUTOHEAL_LOGS=$(gcloud functions logs read phase5b-grading --region=us-west2 --limit=200 --format="value(TIME_UTC, LOG)" 2>/dev/null | \
  awk '/2026-01-18 [0-9][5-9]|2026-01-1[89]/' | grep -E "auto-heal|Phase 3" || echo "")

if echo "$AUTOHEAL_LOGS" | grep -q "Phase 3 analytics triggered successfully"; then
  echo "   ✅ PASS: Found auto-heal success messages"
  echo "   Sample log entries:"
  echo "$AUTOHEAL_LOGS" | grep "Phase 3 analytics triggered successfully" | head -3 | sed 's/^/   /'
elif [ -z "$AUTOHEAL_LOGS" ]; then
  echo "   ⏳ INFO: No auto-heal attempts found yet (may not be needed)"
else
  echo "   ⚠️  WARN: Auto-heal attempted but status unclear"
  echo "$AUTOHEAL_LOGS" | head -5 | sed 's/^/   /'
fi

# Test 4: Check Phase 3 service health
echo ""
echo "4️⃣  Checking Phase 3 service configuration..."
MIN_SCALE=$(gcloud run services describe nba-phase3-analytics-processors --region=us-west2 --format="value(spec.template.metadata.annotations['autoscaling.knative.dev/minScale'])" 2>/dev/null || echo "0")

if [ "$MIN_SCALE" -ge 1 ]; then
  echo "   ✅ PASS: minScale=$MIN_SCALE (prevents cold starts)"
else
  echo "   ❌ FAIL: minScale=$MIN_SCALE (should be 1)"
  echo "   ACTION: Run: gcloud run services update nba-phase3-analytics-processors --region=us-west2 --min-instances=1"
fi

# Summary
echo ""
echo "===================================="
echo "Verification Complete"
echo "===================================="
echo ""
echo "Expected Results:"
echo "  • Zero 503 errors after Jan 18 05:13 UTC ✅"
echo "  • Jan 16-17 coverage >70% ✅"
echo "  • Auto-heal working (if triggered) ✅"
echo "  • minScale=1 configured ✅"
echo ""
echo "If any tests failed, see:"
echo "  📖 docs/09-handoff/SESSION-99-PHASE3-FIX-COMPLETE.md"
echo "  🔧 docs/02-operations/GRADING-TROUBLESHOOTING-RUNBOOK.md"
echo ""
