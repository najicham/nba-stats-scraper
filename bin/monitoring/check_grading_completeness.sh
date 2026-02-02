#!/bin/bash
#
# Check Grading Completeness by Model (Improved - Session 80)
#
# This script monitors grading coverage for active prediction models with improved accuracy.
#
# KEY IMPROVEMENT (Session 80):
# - Only counts GRADABLE predictions (ACTUAL_PROP/ESTIMATED_AVG with lines) in coverage calculation
# - Tracks line availability separately (what % of predictions have real betting lines)
# - Shows ungradable prediction count for visibility
#
# This prevents false alarms when predictions lack betting lines (which is expected behavior).
#
# Metrics:
# 1. Grading Coverage = graded / gradable predictions (ACTUAL_PROP + ESTIMATED_AVG)
#    - Expected: ≥80% OK, 50-79% WARNING, <50% CRITICAL
# 2. Line Availability = ACTUAL_PROP / total predictions
#    - Expected: ≥60% OK, 40-60% WARNING, <40% CRITICAL
# 3. Ungradable Count = NO_PROP_LINE predictions (informational)
#
# Usage:
#   ./bin/monitoring/check_grading_completeness.sh [--days N] [--alert URL]
#
# Options:
#   --days    Number of days to check (default: 3)
#   --alert   Slack webhook URL for alerts (optional)
#
# Exit codes:
#   0 = All models ≥80% graded
#   1 = At least one model 50-79% graded
#   2 = At least one model <50% graded

set -euo pipefail

# Default values
DAYS_LOOKBACK=3
ALERT_WEBHOOK="${SLACK_WEBHOOK_URL_WARNING:-}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --days)
            DAYS_LOOKBACK="$2"
            shift 2
            ;;
        --alert)
            ALERT_WEBHOOK="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=== Grading Completeness Check (Improved) ==="
echo "Last $DAYS_LOOKBACK days"
echo ""

# Run improved BigQuery check
RESULT=$(bq query --use_legacy_sql=false --format=csv "
WITH prediction_breakdown AS (
  -- Count ALL predictions (active and inactive) for accurate coverage calculation
  -- We grade based on what was predicted, not just what's currently active
  SELECT
    system_id,
    COUNT(*) as total_predictions,
    COUNTIF(line_source = 'ACTUAL_PROP') as actual_prop_count,
    COUNTIF(line_source = 'ESTIMATED_AVG') as estimated_avg_count,
    COUNTIF(line_source = 'NO_PROP_LINE') as no_prop_line_count,
    COUNTIF(line_source IN ('ACTUAL_PROP', 'ESTIMATED_AVG')) as gradable_count
  FROM nba_predictions.player_prop_predictions
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL $DAYS_LOOKBACK DAY)
  GROUP BY system_id
),
graded_counts AS (
  SELECT
    system_id,
    COUNT(*) as graded_count
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL $DAYS_LOOKBACK DAY)
  GROUP BY system_id
)
SELECT
  p.system_id,
  p.total_predictions,
  p.gradable_count,
  COALESCE(g.graded_count, 0) as graded,
  p.no_prop_line_count as ungradable,
  -- Grading coverage (only gradable predictions)
  ROUND(100.0 * COALESCE(g.graded_count, 0) / NULLIF(p.gradable_count, 0), 1) as grading_coverage_pct,
  -- Line availability (actual props vs total)
  ROUND(100.0 * p.actual_prop_count / NULLIF(p.total_predictions, 0), 1) as line_availability_pct,
  -- Status based on grading coverage
  CASE
    WHEN p.gradable_count = 0 THEN 'N/A'
    WHEN ROUND(100.0 * COALESCE(g.graded_count, 0) / NULLIF(p.gradable_count, 0), 1) < 50 THEN 'CRITICAL'
    WHEN ROUND(100.0 * COALESCE(g.graded_count, 0) / NULLIF(p.gradable_count, 0), 1) < 80 THEN 'WARNING'
    ELSE 'OK'
  END as grading_status,
  -- Status based on line availability
  CASE
    WHEN ROUND(100.0 * p.actual_prop_count / NULLIF(p.total_predictions, 0), 1) < 40 THEN 'LOW'
    WHEN ROUND(100.0 * p.actual_prop_count / NULLIF(p.total_predictions, 0), 1) < 60 THEN 'MEDIUM'
    ELSE 'GOOD'
  END as line_status
FROM prediction_breakdown p
LEFT JOIN graded_counts g USING (system_id)
WHERE p.total_predictions > 0
ORDER BY grading_coverage_pct ASC NULLS LAST, p.total_predictions DESC
" 2>&1)

echo "$RESULT"
echo ""

# Parse results for summary
CRITICAL_COUNT=$(echo "$RESULT" | grep -c ",CRITICAL," || echo "0")
WARNING_COUNT=$(echo "$RESULT" | grep -c ",WARNING," || echo "0")
LOW_LINE_COUNT=$(echo "$RESULT" | grep -c ",LOW\$" || echo "0")

# Determine overall grading status
if [[ $CRITICAL_COUNT -gt 0 ]]; then
    GRADING_STATUS="🔴 CRITICAL"
    EXIT_CODE=2
    GRADING_MESSAGE="$CRITICAL_COUNT model(s) with <50% grading coverage"
elif [[ $WARNING_COUNT -gt 0 ]]; then
    GRADING_STATUS="🟡 WARNING"
    EXIT_CODE=1
    GRADING_MESSAGE="$WARNING_COUNT model(s) with 50-79% grading coverage"
else
    GRADING_STATUS="✅ HEALTHY"
    EXIT_CODE=0
    GRADING_MESSAGE="All models ≥80% grading coverage"
fi

# Line availability status (informational, doesn't affect exit code)
if [[ $LOW_LINE_COUNT -gt 0 ]]; then
    LINE_STATUS="⚠️  $LOW_LINE_COUNT model(s) with <40% line availability"
else
    LINE_STATUS="✅ Good line availability across models"
fi

echo "=== Summary ==="
echo "Grading Coverage: $GRADING_STATUS"
echo "  $GRADING_MESSAGE"
echo ""
echo "Line Availability: $LINE_STATUS"
echo ""
echo "Note: Grading coverage only counts predictions with betting lines (ACTUAL_PROP/ESTIMATED_AVG)."
echo "      NO_PROP_LINE predictions are shown separately as 'ungradable' for visibility."
echo ""

# Send alert if needed
if [[ $EXIT_CODE -gt 0 ]] && [[ -n "$ALERT_WEBHOOK" ]]; then
    MODELS=$(echo "$RESULT" | grep -E ",CRITICAL,|,WARNING," | awk -F',' '{print $1 ": " $6 "% grading coverage"}' | paste -sd '\\n' -)

    echo "Sending alert..."
    curl -X POST "$ALERT_WEBHOOK" \
        -H 'Content-Type: application/json' \
        -d "{
            \"text\": \"$GRADING_STATUS: Grading Completeness Issue\",
            \"blocks\": [{
                \"type\": \"section\",
                \"text\": {
                    \"type\": \"mrkdwn\",
                    \"text\": \"*Grading Completeness Alert*\n\n$GRADING_MESSAGE\n\n*Affected Models:*\n$MODELS\n\n*Action*: Run grading backfill: \\\`PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py --start-date <date> --end-date <date>\\\`\"
                }
            }]
        }" || true
fi

exit $EXIT_CODE
