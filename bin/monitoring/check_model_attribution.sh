#!/bin/bash
# check_model_attribution.sh - Monitor model attribution field health
# Session 91: Prevents NULL model_file_name issues from going unnoticed
#
# Usage: ./bin/monitoring/check_model_attribution.sh [--hours N]
#
# Returns exit code 0 if healthy, 1 if issues found

set -e

HOURS=${1:-24}
if [[ "$1" == "--hours" ]]; then
    HOURS=${2:-24}
fi

echo "=== Model Attribution Health Check ==="
echo "Checking predictions from last ${HOURS} hours..."
echo ""

# Query model attribution status
RESULT=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT
  model_file_name,
  COUNT(*) as predictions
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE system_id = 'catboost_v9'
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL ${HOURS} HOUR)
GROUP BY 1
ORDER BY 2 DESC
")

# Parse results
NULL_COUNT=0
POPULATED_COUNT=0
MODEL_NAME=""

while IFS=, read -r model_name count; do
    if [[ "$model_name" == "model_file_name" ]]; then
        continue  # Skip header
    fi
    if [[ -z "$model_name" || "$model_name" == "null" || "$model_name" == "NULL" ]]; then
        NULL_COUNT=$((NULL_COUNT + count))
    else
        POPULATED_COUNT=$((POPULATED_COUNT + count))
        MODEL_NAME="$model_name"
    fi
done <<< "$RESULT"

TOTAL=$((NULL_COUNT + POPULATED_COUNT))

echo "Results:"
echo "  Total predictions: $TOTAL"
echo "  With model attribution: $POPULATED_COUNT"
echo "  Missing attribution (NULL): $NULL_COUNT"
if [[ -n "$MODEL_NAME" ]]; then
    echo "  Model file: $MODEL_NAME"
fi
echo ""

# Determine status
if [[ $TOTAL -eq 0 ]]; then
    echo "⚠️  WARNING: No predictions found in last ${HOURS} hours"
    echo "   This may be normal if predictions haven't run yet."
    exit 0
elif [[ $NULL_COUNT -eq 0 ]]; then
    echo "✅ PASS: All predictions have model attribution"
    exit 0
elif [[ $POPULATED_COUNT -eq 0 ]]; then
    echo "🔴 CRITICAL: ALL predictions have NULL model attribution!"
    echo ""
    echo "Investigation steps:"
    echo "1. Check if fix is deployed: gcloud run services describe prediction-worker --region=us-west2 --format=\"value(metadata.labels.commit-sha)\""
    echo "   Expected: 4ada201f or later"
    echo ""
    echo "2. Check worker logs for metadata extraction:"
    echo "   gcloud logging read 'resource.labels.service_name=\"prediction-worker\" AND textPayload=~\"catboost_meta\"' --limit=5"
    exit 1
else
    # Mixed - some NULL, some populated
    PCT=$((POPULATED_COUNT * 100 / TOTAL))
    echo "🟡 WARNING: Mixed results - ${PCT}% have attribution"
    echo "   This may be expected if some predictions were created before the fix."
    echo ""
    echo "   Check when NULL predictions were created:"
    echo "   bq query --use_legacy_sql=false \"SELECT DATE(created_at), model_file_name, COUNT(*) FROM nba_predictions.player_prop_predictions WHERE system_id='catboost_v9' AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL ${HOURS} HOUR) GROUP BY 1,2 ORDER BY 1\""
    exit 0
fi
