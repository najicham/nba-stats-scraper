#!/bin/bash
# daily_data_quality_check.sh - Daily data quality validation for NBA predictions
#
# This script checks for:
# 1. Duplicate predictions in grading table
# 2. Duplicate business keys in source table
# 3. Prediction volume anomalies
# 4. Grading completion status
# 5. Confidence score normalization (catboost_v8)
#
# Usage: ./bin/validation/daily_data_quality_check.sh [--alert-slack]
#
# Exit codes:
#   0 - All checks passed
#   1 - Critical failures detected
#   2 - Warnings detected (non-blocking)

set -euo pipefail

PROJECT_ID="nba-props-platform"
SLACK_WEBHOOK="${SLACK_WEBHOOK_URL:-}"  # Set via environment variable
ALERT_SLACK=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --alert-slack)
            ALERT_SLACK=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "==================================="
echo "NBA Predictions Data Quality Check"
echo "==================================="
echo "Date: $(date)"
echo "Project: $PROJECT_ID"
echo ""

FAILURES=0
WARNINGS=0

# Helper function to send Slack alert
send_slack_alert() {
    local message="$1"
    local severity="$2"  # "error" or "warning"

    if [ "$ALERT_SLACK" = true ] && [ -n "$SLACK_WEBHOOK" ]; then
        local color="danger"
        if [ "$severity" = "warning" ]; then
            color="warning"
        fi

        curl -X POST "$SLACK_WEBHOOK" \
            -H "Content-Type: application/json" \
            -d "{
                \"attachments\": [{
                    \"color\": \"$color\",
                    \"title\": \"NBA Data Quality Alert\",
                    \"text\": \"$message\",
                    \"ts\": $(date +%s)
                }]
            }" \
            --silent --output /dev/null
    fi
}

# Check 1: Duplicate predictions in grading table
echo "Check 1: Duplicate predictions in grading table..."
DUPLICATES=$(bq query --project_id=$PROJECT_ID --use_legacy_sql=false --format=csv '
  SELECT COUNT(*) FROM `nba_predictions.duplicate_predictions_monitor`
' 2>/dev/null | tail -1)

if [ -z "$DUPLICATES" ]; then
    echo "❌ ERROR: Failed to query duplicate monitor"
    FAILURES=$((FAILURES + 1))
elif [ "$DUPLICATES" -gt 0 ]; then
    echo "❌ CRITICAL: Found $DUPLICATES duplicate predictions in grading table!"
    send_slack_alert "🚨 CRITICAL: Found $DUPLICATES duplicate predictions in grading table" "error"
    FAILURES=$((FAILURES + 1))
else
    echo "✅ No duplicate predictions in grading table"
fi

# Check 2: Duplicate business keys in source table (last 7 days)
echo ""
echo "Check 2: Duplicate business keys in source table..."
SOURCE_DUPES=$(bq query --project_id=$PROJECT_ID --use_legacy_sql=false --format=csv '
  SELECT COUNT(*)
  FROM (
    SELECT game_id, player_lookup, system_id, current_points_line, COUNT(*) as cnt
    FROM `nba_predictions.player_prop_predictions`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    GROUP BY 1,2,3,4
    HAVING cnt > 1
  )
' 2>/dev/null | tail -1)

if [ -z "$SOURCE_DUPES" ]; then
    echo "❌ ERROR: Failed to query source table"
    FAILURES=$((FAILURES + 1))
elif [ "$SOURCE_DUPES" -gt 0 ]; then
    echo "❌ CRITICAL: Found $SOURCE_DUPES duplicate business keys in source table!"
    send_slack_alert "🚨 CRITICAL: Found $SOURCE_DUPES duplicate business keys in predictions table (last 7 days)" "error"
    FAILURES=$((FAILURES + 1))
else
    echo "✅ Source table integrity OK (no duplicate business keys)"
fi

# Check 3: Prediction volume (yesterday)
echo ""
echo "Check 3: Prediction volume validation..."
YESTERDAY_COUNT=$(bq query --project_id=$PROJECT_ID --use_legacy_sql=false --format=csv '
  SELECT COUNT(DISTINCT CONCAT(game_id, player_lookup, system_id, CAST(current_points_line AS STRING)))
  FROM `nba_predictions.player_prop_predictions`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
' 2>/dev/null | tail -1)

if [ -z "$YESTERDAY_COUNT" ]; then
    echo "⚠️  WARNING: Failed to query prediction volume"
    WARNINGS=$((WARNINGS + 1))
elif [ "$YESTERDAY_COUNT" -lt 300 ]; then
    echo "⚠️  WARNING: Only $YESTERDAY_COUNT predictions yesterday (expected 400-800)"
    echo "   This may indicate prediction generation failed or incomplete game schedule"
    send_slack_alert "⚠️ WARNING: Low prediction volume yesterday ($YESTERDAY_COUNT, expected 400-800)" "warning"
    WARNINGS=$((WARNINGS + 1))
elif [ "$YESTERDAY_COUNT" -gt 1000 ]; then
    echo "⚠️  WARNING: $YESTERDAY_COUNT predictions yesterday (expected 400-800)"
    echo "   This may indicate duplicate predictions or multiple runs"
    send_slack_alert "⚠️ WARNING: High prediction volume yesterday ($YESTERDAY_COUNT, expected 400-800, possible duplicates)" "warning"
    WARNINGS=$((WARNINGS + 1))
else
    echo "✅ Prediction volume normal ($YESTERDAY_COUNT unique predictions)"
fi

# Check 4: Grading completion (yesterday's predictions)
echo ""
echo "Check 4: Grading completion status..."
UNGRADED=$(bq query --project_id=$PROJECT_ID --use_legacy_sql=false --format=csv '
  SELECT COUNT(DISTINCT p.prediction_id)
  FROM `nba_predictions.player_prop_predictions` p
  LEFT JOIN `nba_predictions.prediction_grades` g
    ON p.prediction_id = g.prediction_id
  WHERE p.game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    AND g.prediction_id IS NULL
    AND p.is_active = TRUE
    AND p.recommendation NOT IN ("PASS", "NO_LINE")
' 2>/dev/null | tail -1)

if [ -z "$UNGRADED" ]; then
    echo "⚠️  WARNING: Failed to query grading status"
    WARNINGS=$((WARNINGS + 1))
elif [ "$UNGRADED" -gt 50 ]; then
    echo "⚠️  WARNING: $UNGRADED predictions from yesterday not yet graded"
    echo "   Grading may be delayed or failed. Check scheduled query status."
    send_slack_alert "⚠️ WARNING: $UNGRADED predictions from yesterday not yet graded (may be delayed)" "warning"
    WARNINGS=$((WARNINGS + 1))
else
    if [ "$UNGRADED" -eq 0 ]; then
        echo "✅ Grading complete (all predictions graded)"
    else
        echo "✅ Grading mostly complete ($UNGRADED ungraded, acceptable)"
    fi
fi

# Check 5: catboost_v8 confidence score normalization
echo ""
echo "Check 5: catboost_v8 confidence normalization..."
BAD_CONFIDENCE=$(bq query --project_id=$PROJECT_ID --use_legacy_sql=false --format=csv '
  SELECT COUNT(*)
  FROM `nba_predictions.prediction_grades`
  WHERE system_id = "catboost_v8"
    AND confidence_score > 1
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
' 2>/dev/null | tail -1)

if [ -z "$BAD_CONFIDENCE" ]; then
    echo "⚠️  WARNING: Failed to query confidence scores"
    WARNINGS=$((WARNINGS + 1))
elif [ "$BAD_CONFIDENCE" -gt 0 ]; then
    echo "❌ CRITICAL: Found $BAD_CONFIDENCE catboost_v8 predictions with confidence > 1 (last 7 days)"
    echo "   Confidence scores should be normalized to 0-1 range"
    send_slack_alert "🚨 CRITICAL: Found $BAD_CONFIDENCE catboost_v8 predictions with unnormalized confidence (>1)" "error"
    FAILURES=$((FAILURES + 1))
else
    echo "✅ catboost_v8 confidence scores properly normalized"
fi

# Check 6: Data freshness (most recent prediction)
echo ""
echo "Check 6: Data freshness check..."
HOURS_SINCE_LAST_PREDICTION=$(bq query --project_id=$PROJECT_ID --use_legacy_sql=false --format=csv '
  SELECT TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), HOUR)
  FROM `nba_predictions.player_prop_predictions`
' 2>/dev/null | tail -1)

if [ -z "$HOURS_SINCE_LAST_PREDICTION" ]; then
    echo "⚠️  WARNING: Failed to query data freshness"
    WARNINGS=$((WARNINGS + 1))
elif [ "$HOURS_SINCE_LAST_PREDICTION" -gt 48 ]; then
    echo "❌ CRITICAL: Last prediction was $HOURS_SINCE_LAST_PREDICTION hours ago"
    echo "   Prediction worker may have stopped running"
    send_slack_alert "🚨 CRITICAL: No new predictions in $HOURS_SINCE_LAST_PREDICTION hours (worker may be down)" "error"
    FAILURES=$((FAILURES + 1))
elif [ "$HOURS_SINCE_LAST_PREDICTION" -gt 30 ]; then
    echo "⚠️  WARNING: Last prediction was $HOURS_SINCE_LAST_PREDICTION hours ago"
    send_slack_alert "⚠️ WARNING: Last prediction was $HOURS_SINCE_LAST_PREDICTION hours ago" "warning"
    WARNINGS=$((WARNINGS + 1))
else
    echo "✅ Data is fresh (last prediction $HOURS_SINCE_LAST_PREDICTION hours ago)"
fi

# Check 7: System coverage (all 6 systems active)
echo ""
echo "Check 7: Prediction system coverage..."
ACTIVE_SYSTEMS=$(bq query --project_id=$PROJECT_ID --use_legacy_sql=false --format=csv '
  SELECT COUNT(DISTINCT system_id)
  FROM `nba_predictions.player_prop_predictions`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
' 2>/dev/null | tail -1)

EXPECTED_SYSTEMS=6

if [ -z "$ACTIVE_SYSTEMS" ]; then
    echo "⚠️  WARNING: Failed to query system coverage"
    WARNINGS=$((WARNINGS + 1))
elif [ "$ACTIVE_SYSTEMS" -lt "$EXPECTED_SYSTEMS" ]; then
    echo "⚠️  WARNING: Only $ACTIVE_SYSTEMS out of $EXPECTED_SYSTEMS systems active (last 3 days)"
    echo "   Some prediction systems may have failed"
    send_slack_alert "⚠️ WARNING: Only $ACTIVE_SYSTEMS/$EXPECTED_SYSTEMS prediction systems active" "warning"
    WARNINGS=$((WARNINGS + 1))
else
    echo "✅ All $ACTIVE_SYSTEMS prediction systems active"
fi

# Summary
echo ""
echo "==================================="
echo "Data Quality Check Summary"
echo "==================================="

if [ $FAILURES -gt 0 ]; then
    echo "❌ Status: FAILED"
    echo "   Critical Issues: $FAILURES"
    echo "   Warnings: $WARNINGS"
    echo ""
    echo "Action required: Investigate and fix critical issues immediately"
    exit 1
elif [ $WARNINGS -gt 0 ]; then
    echo "⚠️  Status: WARNINGS"
    echo "   Critical Issues: 0"
    echo "   Warnings: $WARNINGS"
    echo ""
    echo "Action recommended: Review warnings and monitor"
    exit 2
else
    echo "✅ Status: ALL CHECKS PASSED"
    echo "   No issues detected"
    echo ""
    exit 0
fi
