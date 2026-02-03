#!/bin/bash
# P2-2: Prediction Timing Lag Monitor (Session 89)
#
# Detects regression in prediction timing - ensures predictions still run at
# 2:30 AM ET (not regressing to 7 AM like before Sessions 73-74 improvements).
#
# Usage: ./bin/monitoring/check-prediction-timing.sh [game-date]
#
# Prevents: Regression to late predictions (7 AM instead of 2:30 AM)
# Reference: Sessions 73-74 - Early prediction improvements

set -e

GAME_DATE=${1:-$(date +%Y-%m-%d)}
PROJECT="nba-props-platform"

echo "=============================================="
echo "P2-2: Prediction Timing Lag Monitor"
echo "=============================================="
echo "Game date: $GAME_DATE"
echo "Project: $PROJECT"
echo ""

# Query to check prediction timing vs line availability
QUERY="
WITH line_timing AS (
  SELECT
    game_date,
    MIN(created_at) as first_line_available
  FROM \`$PROJECT.nba_raw.bettingpros_player_points_props\`
  WHERE game_date = DATE('$GAME_DATE')
    AND points_line IS NOT NULL
  GROUP BY game_date
),
pred_timing AS (
  SELECT
    game_date,
    MIN(created_at) as first_prediction,
    COUNT(DISTINCT player_lookup) as players_with_predictions
  FROM \`$PROJECT.nba_predictions.player_prop_predictions\`
  WHERE game_date = DATE('$GAME_DATE')
    AND system_id = 'catboost_v9'
  GROUP BY game_date
)
SELECT
  p.game_date,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S %Z', l.first_line_available, 'America/New_York') as first_line_et,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S %Z', p.first_prediction, 'America/New_York') as first_pred_et,
  TIMESTAMP_DIFF(p.first_prediction, l.first_line_available, MINUTE) as lag_minutes,
  ROUND(TIMESTAMP_DIFF(p.first_prediction, l.first_line_available, MINUTE) / 60.0, 1) as lag_hours,
  p.players_with_predictions,
  CASE
    WHEN TIMESTAMP_DIFF(p.first_prediction, l.first_line_available, HOUR) > 4
      THEN 'CRITICAL'
    WHEN TIMESTAMP_DIFF(p.first_prediction, l.first_line_available, HOUR) > 2
      THEN 'WARNING'
    ELSE 'OK'
  END as status
FROM pred_timing p
LEFT JOIN line_timing l USING (game_date)
"

# Run query
echo "Analyzing prediction timing..."
RESULT=$(bq query --use_legacy_sql=false --format=csv "$QUERY" 2>&1)

if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: BigQuery query failed"
    echo "$RESULT"
    exit 1
fi

# Check if we got results
RESULT_ROWS=$(echo "$RESULT" | tail -n +2 | wc -l)

if [ "$RESULT_ROWS" -eq 0 ]; then
    echo ""
    echo "=============================================="
    echo "⚠️  NO DATA FOUND"
    echo "=============================================="
    echo ""
    echo "No predictions or lines found for $GAME_DATE"
    echo ""
    echo "Possible reasons:"
    echo "  1. No games scheduled for this date"
    echo "  2. Predictions haven't run yet"
    echo "  3. Lines haven't been scraped yet"
    echo ""
    echo "Check schedule:"
    echo "  bq query \"SELECT COUNT(*) FROM nba_reference.nba_schedule WHERE game_date = '$GAME_DATE'\""
    exit 2
fi

# Parse result (skip header, get data row)
DATA_ROW=$(echo "$RESULT" | tail -1)

IFS=',' read -r DATE FIRST_LINE FIRST_PRED LAG_MIN LAG_HOURS PLAYERS STATUS <<< "$DATA_ROW"

echo ""
echo "=============================================="
echo "TIMING ANALYSIS"
echo "=============================================="
echo "Game date:              $DATE"
echo "Players predicted:      $PLAYERS"
echo ""
echo "First line available:   $FIRST_LINE"
echo "First prediction made:  $FIRST_PRED"
echo ""
echo "Lag time:               ${LAG_HOURS} hours (${LAG_MIN} minutes)"
echo ""

# Status-specific output
case "$STATUS" in
    OK)
        echo "✅ STATUS: OK"
        echo ""
        echo "Prediction timing is optimal."
        echo "Lag is within acceptable range (<= 2 hours)."
        echo ""
        echo "Expected behavior:"
        echo "  - Lines scraped: ~2:00 AM ET (BettingPros)"
        echo "  - Predictions run: 2:30 AM ET (early predictions scheduler)"
        echo "  - Expected lag: 30-60 minutes"
        ;;

    WARNING)
        echo "⚠️  STATUS: WARNING"
        echo ""
        echo "Prediction timing is slower than optimal."
        echo "Lag is 2-4 hours (acceptable but not ideal)."
        echo ""
        echo "Investigation recommended:"
        echo "  1. Check if early predictions scheduler ran"
        echo "  2. Verify prediction-coordinator logs for delays"
        echo "  3. Check if scheduler time is correct (2:30 AM ET)"
        echo ""
        echo "Scheduler jobs to check:"
        echo "  gcloud scheduler jobs list --location=us-west2 | grep predictions-early"
        ;;

    CRITICAL)
        echo "🚨 STATUS: CRITICAL - TIMING REGRESSION DETECTED"
        echo ""
        echo "Prediction timing has regressed!"
        echo "Lag is > 4 hours (indicates early predictions not running)."
        echo ""
        echo "This suggests predictions reverted to 7 AM scheduler instead of 2:30 AM."
        echo ""
        echo "=============================================="
        echo "IMMEDIATE ACTIONS"
        echo "=============================================="
        echo ""
        echo "1. Verify early predictions scheduler exists:"
        echo "   gcloud scheduler jobs describe predictions-early \\"
        echo "     --location=us-west2 --format=json | jq '.schedule'"
        echo ""
        echo "2. Check scheduler execution logs:"
        echo "   gcloud logging read 'resource.type=\"cloud_scheduler_job\" \\"
        echo "     AND resource.labels.job_id=\"predictions-early\"' \\"
        echo "     --limit=10 --format=json"
        echo ""
        echo "3. Verify prediction-coordinator logs:"
        echo "   gcloud logging read 'resource.labels.service_name=\"prediction-coordinator\" \\"
        echo "     AND jsonPayload.game_date=\"$GAME_DATE\"' \\"
        echo "     --limit=20 --format=\"table(timestamp,jsonPayload.message)\""
        echo ""
        echo "4. Check scheduler configuration:"
        echo "   cat bin/orchestrators/setup_early_predictions_scheduler.sh"
        echo ""
        echo "5. Re-run setup if needed:"
        echo "   ./bin/orchestrators/setup_early_predictions_scheduler.sh"
        echo ""
        echo "=============================================="
        echo "REFERENCE"
        echo "=============================================="
        echo ""
        echo "Sessions 73-74: Implemented early predictions (2:30 AM ET)"
        echo "Before: Predictions at 7:00 AM (5-hour lag)"
        echo "After:  Predictions at 2:30 AM (30-min lag)"
        echo ""
        echo "Timing regression = lost competitive advantage"
        ;;
esac

echo ""
echo "=============================================="
echo "HISTORICAL COMPARISON"
echo "=============================================="
echo ""

# Query last 7 days for trend
TREND_QUERY="
WITH line_timing AS (
  SELECT
    game_date,
    MIN(created_at) as first_line_available
  FROM \`$PROJECT.nba_raw.bettingpros_player_points_props\`
  WHERE game_date >= DATE_SUB(DATE('$GAME_DATE'), INTERVAL 7 DAY)
    AND game_date <= DATE('$GAME_DATE')
    AND points_line IS NOT NULL
  GROUP BY game_date
),
pred_timing AS (
  SELECT
    game_date,
    MIN(created_at) as first_prediction
  FROM \`$PROJECT.nba_predictions.player_prop_predictions\`
  WHERE game_date >= DATE_SUB(DATE('$GAME_DATE'), INTERVAL 7 DAY)
    AND game_date <= DATE('$GAME_DATE')
    AND system_id = 'catboost_v9'
  GROUP BY game_date
)
SELECT
  p.game_date,
  ROUND(TIMESTAMP_DIFF(p.first_prediction, l.first_line_available, MINUTE) / 60.0, 1) as lag_hours
FROM pred_timing p
LEFT JOIN line_timing l USING (game_date)
ORDER BY p.game_date DESC
LIMIT 7
"

echo "Last 7 days prediction lag (hours):"
echo ""

TREND_RESULT=$(bq query --use_legacy_sql=false --format=csv "$TREND_QUERY" 2>&1 | tail -n +2)

if [ -n "$TREND_RESULT" ]; then
    echo "$TREND_RESULT" | awk -F',' '{printf "  %s: %.1f hours\n", $1, $2}'
else
    echo "  (No trend data available)"
fi

echo ""
echo "=============================================="

# Exit with appropriate code
if [ "$STATUS" = "CRITICAL" ]; then
    echo "🚨 CRITICAL: Timing regression detected"
    echo "=============================================="
    exit 1
elif [ "$STATUS" = "WARNING" ]; then
    echo "⚠️  WARNING: Timing slower than optimal"
    echo "=============================================="
    exit 0  # Don't fail on warnings
else
    echo "✅ Prediction timing is optimal"
    echo "=============================================="
    exit 0
fi
