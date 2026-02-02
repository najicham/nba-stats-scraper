#!/bin/bash

# Weekly Model Drift Detection
# Checks model performance degradation and alerts if issues detected
#
# Usage: ./bin/monitoring/weekly_model_drift_check.sh
#
# Exit codes:
#   0 = No drift detected
#   1 = WARNING level drift
#   2 = CRITICAL level drift

set -euo pipefail

PROJECT="nba-props-platform"
SLACK_WEBHOOK="${SLACK_WEBHOOK_URL_WARNING:-}"
SLACK_CRITICAL="${SLACK_WEBHOOK_URL_ERROR:-}"

echo "==================================="
echo "Weekly Model Drift Check"
echo "Date: $(date)"
echo "==================================="
echo ""

# Check model performance over last 4 weeks
echo "Checking weekly hit rates..."
DRIFT_DATA=$(bq query --use_legacy_sql=false --format=csv "
SELECT
  system_id,
  DATE_TRUNC(game_date, WEEK) as week_start,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  ROUND(AVG(predicted_points - actual_points), 2) as bias
FROM nba_predictions.prediction_accuracy
WHERE system_id IN ('catboost_v9', 'catboost_v8', 'ensemble_v1_1')
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
  AND prediction_correct IS NOT NULL
GROUP BY system_id, week_start
ORDER BY system_id, week_start DESC
")

echo "$DRIFT_DATA"
echo ""

# Check for critical drift (hit rate < 55% for 2 consecutive weeks)
CRITICAL_DRIFT=$(echo "$DRIFT_DATA" | awk -F',' '
NR>1 {
    model=$1
    week=$2
    hit_rate=$4

    if (hit_rate < 55) {
        critical_weeks[model]++
    } else {
        critical_weeks[model] = 0
    }

    if (critical_weeks[model] >= 2) {
        print model " has hit rate < 55% for 2+ consecutive weeks"
        exit 1
    }
}')

# Check for warning drift (hit rate < 60% for 2 consecutive weeks)
WARNING_DRIFT=$(echo "$DRIFT_DATA" | awk -F',' '
NR>1 {
    model=$1
    hit_rate=$4

    if (hit_rate < 60) {
        warning_weeks[model]++
    } else {
        warning_weeks[model] = 0
    }

    if (warning_weeks[model] >= 2) {
        print model " has hit rate < 60% for 2+ consecutive weeks"
    }
}')

# Check Vegas edge
echo "Checking model vs Vegas accuracy..."
VEGAS_COMPARISON=$(bq query --use_legacy_sql=false --format=csv "
SELECT
  system_id,
  DATE_TRUNC(game_date, WEEK) as week,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as model_mae,
  ROUND(AVG(ABS(line_value - actual_points)), 2) as vegas_mae,
  ROUND(AVG(ABS(line_value - actual_points)) - AVG(ABS(predicted_points - actual_points)), 2) as edge
FROM nba_predictions.prediction_accuracy
WHERE system_id IN ('catboost_v9', 'catboost_v8', 'ensemble_v1_1')
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
  AND line_value IS NOT NULL
GROUP BY system_id, week
ORDER BY system_id, week DESC
")

echo "$VEGAS_COMPARISON"
echo ""

# Check if model is losing to Vegas (edge < 0 for 2+ weeks)
VEGAS_LOSS=$(echo "$VEGAS_COMPARISON" | awk -F',' '
NR>1 {
    model=$1
    edge=$5

    if (edge < 0) {
        vegas_loss_weeks[model]++
    } else {
        vegas_loss_weeks[model] = 0
    }

    if (vegas_loss_weeks[model] >= 2) {
        print model " losing to Vegas (negative edge) for 2+ weeks"
    }
}')

# Determine alert level
if [ -n "$CRITICAL_DRIFT" ]; then
    echo "🔴 CRITICAL DRIFT DETECTED:"
    echo "$CRITICAL_DRIFT"

    # Send Slack alert
    if [ -n "$SLACK_CRITICAL" ]; then
        curl -X POST "$SLACK_CRITICAL" \
          -H 'Content-Type: application/json' \
          -d "{
            \"text\": \"🔴 CRITICAL: Model Drift Detected\",
            \"blocks\": [{
              \"type\": \"section\",
              \"text\": {
                \"type\": \"mrkdwn\",
                \"text\": \"*Model Drift Alert*\n\n$CRITICAL_DRIFT\n\n*Action Required:*\n- Review model performance analysis\n- Consider emergency retraining\n- Check data quality for recent dates\"
              }
            }]
          }"
    fi

    exit 2
elif [ -n "$WARNING_DRIFT" ] || [ -n "$VEGAS_LOSS" ]; then
    echo "🟡 WARNING: Potential Drift Detected"
    [ -n "$WARNING_DRIFT" ] && echo "$WARNING_DRIFT"
    [ -n "$VEGAS_LOSS" ] && echo "$VEGAS_LOSS"

    # Send Slack warning
    if [ -n "$SLACK_WEBHOOK" ]; then
        curl -X POST "$SLACK_WEBHOOK" \
          -H 'Content-Type: application/json' \
          -d "{
            \"text\": \"🟡 WARNING: Model Drift Detected\",
            \"blocks\": [{
              \"type\": \"section\",
              \"text\": {
                \"type\": \"mrkdwn\",
                \"text\": \"*Model Drift Warning*\n\n$WARNING_DRIFT\n$VEGAS_LOSS\n\n*Recommended Actions:*\n- Monitor closely this week\n- Review player tier breakdown\n- Consider monthly retraining\"
              }
            }]
          }"
    fi

    exit 1
else
    echo "✅ No drift detected - models performing within thresholds"
    exit 0
fi
