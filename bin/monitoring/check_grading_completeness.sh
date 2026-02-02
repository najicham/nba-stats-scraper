#!/bin/bash
#
# Check Grading Completeness by Model
#
# This script monitors grading coverage for all active prediction models
# to detect when grading falls behind (like the Session 77 issue).
#
# Expected coverage: ≥80%
# Alert threshold: <50% for any model
# Critical threshold: Any model with 0% grading
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

echo "=== Grading Completeness Check ==="
echo "Last $DAYS_LOOKBACK days"
echo ""

# Run BigQuery check
RESULT=$(bq query --use_legacy_sql=false --format=csv "
WITH prediction_counts AS (
  SELECT
    'player_prop_predictions' as source,
    system_id,
    COUNT(*) as record_count
  FROM nba_predictions.player_prop_predictions
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL $DAYS_LOOKBACK DAY)
    AND current_points_line IS NOT NULL
  GROUP BY system_id

  UNION ALL

  SELECT
    'prediction_accuracy' as source,
    system_id,
    COUNT(*) as record_count
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL $DAYS_LOOKBACK DAY)
  GROUP BY system_id
)
SELECT
  system_id,
  MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END) as predictions,
  MAX(CASE WHEN source = 'prediction_accuracy' THEN record_count END) as graded,
  ROUND(100.0 * MAX(CASE WHEN source = 'prediction_accuracy' THEN record_count END) /
        NULLIF(MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END), 0), 1) as coverage_pct,
  CASE
    WHEN ROUND(100.0 * MAX(CASE WHEN source = 'prediction_accuracy' THEN record_count END) /
         NULLIF(MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END), 0), 1) < 50
    THEN 'CRITICAL'
    WHEN ROUND(100.0 * MAX(CASE WHEN source = 'prediction_accuracy' THEN record_count END) /
         NULLIF(MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END), 0), 1) < 80
    THEN 'WARNING'
    ELSE 'OK'
  END as status
FROM prediction_counts
GROUP BY system_id
HAVING MAX(CASE WHEN source = 'player_prop_predictions' THEN record_count END) > 0
ORDER BY coverage_pct ASC
" 2>&1)

echo "$RESULT"
echo ""

# Count issues
CRITICAL_COUNT=$(echo "$RESULT" | grep -c "CRITICAL" || echo "0")
WARNING_COUNT=$(echo "$RESULT" | grep -c "WARNING" || echo "0")

# Determine overall status
if [[ $CRITICAL_COUNT -gt 0 ]]; then
    STATUS="🔴 CRITICAL"
    EXIT_CODE=2
    MESSAGE="$CRITICAL_COUNT model(s) with <50% grading coverage"
elif [[ $WARNING_COUNT -gt 0 ]]; then
    STATUS="🟡 WARNING"
    EXIT_CODE=1
    MESSAGE="$WARNING_COUNT model(s) with 50-79% grading coverage"
else
    STATUS="✅ HEALTHY"
    EXIT_CODE=0
    MESSAGE="All models ≥80% grading coverage"
fi

echo "Overall Status: $STATUS"
echo "$MESSAGE"
echo ""

# Send alert if needed
if [[ $EXIT_CODE -gt 0 ]] && [[ -n "$ALERT_WEBHOOK" ]]; then
    MODELS=$(echo "$RESULT" | grep -E "CRITICAL|WARNING" | awk -F',' '{print $1 ": " $4 "%"}' | paste -sd '\\n' -)

    echo "Sending alert..."
    curl -X POST "$ALERT_WEBHOOK" \
        -H 'Content-Type: application/json' \
        -d "{
            \"text\": \"$STATUS: Grading Completeness Issue\",
            \"blocks\": [{
                \"type\": \"section\",
                \"text\": {
                    \"type\": \"mrkdwn\",
                    \"text\": \"*Grading Completeness Alert*\n\n$MESSAGE\n\n*Affected Models:*\n$MODELS\n\n*Action*: Run grading backfill: \\\`PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py --start-date <date> --end-date <date>\\\`\"
                }
            }]
        }" || true
fi

exit $EXIT_CODE
