#!/bin/bash
#
# check-system-health.sh
#
# Quick health check for the grading system.
# Run this daily or whenever you want to verify system health.
#
# Usage: ./monitoring/check-system-health.sh

set -euo pipefail

PROJECT_ID="nba-props-platform"

echo "🏥 NBA Grading System Health Check"
echo "===================================="
echo "Time: $(date)"
echo ""

# Test 1: Recent grading activity
echo "1️⃣  Checking recent grading activity..."
RECENT_GRADING=$(bq query --use_legacy_sql=false --format=csv --max_rows=1 '
SELECT TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(graded_at), HOUR) as hours_ago
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
' 2>/dev/null | tail -1)

if [ -n "$RECENT_GRADING" ] && [ "$RECENT_GRADING" -lt 48 ]; then
  echo "   ✅ PASS: Last grading was $RECENT_GRADING hours ago"
else
  echo "   ❌ FAIL: No grading in last $RECENT_GRADING hours (expected <48)"
fi

# Test 2: Phase 3 503 errors
echo ""
echo "2️⃣  Checking for Phase 3 503 errors (last 100 logs)..."
ERROR_COUNT=$(gcloud functions logs read phase5b-grading --region=us-west2 --limit=100 2>/dev/null | grep -c "503" || echo "0")

if [ "$ERROR_COUNT" -eq 0 ]; then
  echo "   ✅ PASS: No 503 errors found"
else
  echo "   ❌ FAIL: Found $ERROR_COUNT instances of 503 errors"
fi

# Test 3: Phase 3 service health
echo ""
echo "3️⃣  Checking Phase 3 service health..."
PHASE3_STATUS=$(curl -s https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/health 2>/dev/null | jq -r '.status' || echo "error")

if [ "$PHASE3_STATUS" = "healthy" ]; then
  echo "   ✅ PASS: Phase 3 service is healthy"
else
  echo "   ❌ FAIL: Phase 3 service returned: $PHASE3_STATUS"
fi

# Test 4: Phase 3 minScale configuration
echo ""
echo "4️⃣  Checking Phase 3 minScale configuration..."
MIN_SCALE=$(gcloud run services describe nba-phase3-analytics-processors --region=us-west2 --format="value(spec.template.metadata.annotations['autoscaling.knative.dev/minScale'])" 2>/dev/null || echo "0")

if [ "$MIN_SCALE" -ge 1 ]; then
  echo "   ✅ PASS: minScale=$MIN_SCALE (prevents cold starts)"
else
  echo "   ⚠️  WARN: minScale=$MIN_SCALE (may cause 503 errors)"
fi

# Test 5: Grading coverage (last 3 days)
echo ""
echo "5️⃣  Checking grading coverage (last 3 days)..."
bq query --use_legacy_sql=false --format=pretty '
WITH coverage AS (
  SELECT
    game_date,
    COUNT(DISTINCT CONCAT(player_lookup, "|", system_id)) as total_preds,
    COALESCE((
      SELECT COUNT(DISTINCT CONCAT(player_lookup, "|", system_id))
      FROM `nba-props-platform.nba_predictions.prediction_accuracy` acc
      WHERE acc.game_date = pred.game_date
    ), 0) as graded_preds
  FROM `nba-props-platform.nba_predictions.player_prop_predictions` pred
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  GROUP BY game_date
)
SELECT
  game_date,
  total_preds as predictions,
  graded_preds as graded,
  ROUND(graded_preds * 100.0 / NULLIF(total_preds, 0), 1) as coverage_pct,
  CASE
    WHEN graded_preds * 100.0 / NULLIF(total_preds, 0) >= 70 THEN "✅"
    WHEN graded_preds * 100.0 / NULLIF(total_preds, 0) >= 40 THEN "🟡"
    ELSE "❌"
  END as status
FROM coverage
ORDER BY game_date DESC
' 2>/dev/null | tail -10

# Test 6: Duplicate check
echo ""
echo "6️⃣  Checking for duplicate grading records (last 7 days)..."
DUP_COUNT=$(bq query --use_legacy_sql=false --format=csv --max_rows=1 '
SELECT COUNT(*) as dup_count
FROM (
  SELECT player_lookup, game_id, system_id, line_value, COUNT(*) as cnt
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY 1,2,3,4
  HAVING COUNT(*) > 1
)
' 2>/dev/null | tail -1)

if [ "$DUP_COUNT" -eq 0 ]; then
  echo "   ✅ PASS: No duplicates found"
else
  echo "   ❌ FAIL: Found $DUP_COUNT duplicate business keys"
fi

# Summary
echo ""
echo "===================================="
echo "Health Check Complete"
echo "===================================="
echo ""
echo "For detailed monitoring, see:"
echo "  📖 docs/02-operations/GRADING-MONITORING-GUIDE.md"
echo "  🔧 docs/02-operations/GRADING-TROUBLESHOOTING-RUNBOOK.md"
echo ""
echo "To view full system status:"
echo "  cat STATUS-DASHBOARD.md"
