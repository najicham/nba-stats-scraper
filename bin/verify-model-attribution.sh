#!/bin/bash
# Verify Model Attribution System
# Session 84 - February 2, 2026
#
# Purpose: Verify that model attribution fields are being populated correctly
# in predictions and that we can track which exact model file generated which predictions.
#
# Usage:
#   ./bin/verify-model-attribution.sh [--game-date YYYY-MM-DD]
#
# Examples:
#   ./bin/verify-model-attribution.sh                    # Check most recent predictions
#   ./bin/verify-model-attribution.sh --game-date 2026-02-03  # Check specific date

set -e

# Parse arguments
GAME_DATE=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --game-date)
            GAME_DATE="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--game-date YYYY-MM-DD]"
            exit 1
            ;;
    esac
done

# Default to checking last 3 days if no specific date provided
if [ -z "$GAME_DATE" ]; then
    DATE_FILTER="game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)"
else
    DATE_FILTER="game_date = DATE('$GAME_DATE')"
fi

echo "============================================"
echo "Model Attribution Verification"
echo "============================================"
echo ""

echo "Step 1: Checking model attribution coverage..."
echo ""

bq query --use_legacy_sql=false "
SELECT
  game_date,
  system_id,
  COUNT(*) as total_predictions,
  COUNTIF(model_file_name IS NOT NULL) as with_file_name,
  COUNTIF(model_training_start_date IS NOT NULL) as with_training_dates,
  COUNTIF(model_expected_mae IS NOT NULL) as with_expected_mae,
  ROUND(100.0 * COUNTIF(model_file_name IS NOT NULL) / COUNT(*), 1) as coverage_pct
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE $DATE_FILTER
GROUP BY game_date, system_id
ORDER BY game_date DESC, system_id"

echo ""
echo "Step 2: Checking model file distribution..."
echo ""

bq query --use_legacy_sql=false "
SELECT
  system_id,
  model_file_name,
  model_training_start_date,
  model_training_end_date,
  model_expected_mae,
  model_expected_hit_rate,
  COUNT(*) as predictions,
  MIN(game_date) as first_game,
  MAX(game_date) as last_game
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE $DATE_FILTER
  AND model_file_name IS NOT NULL
GROUP BY 1, 2, 3, 4, 5, 6
ORDER BY system_id, last_game DESC"

echo ""
echo "Step 3: Checking for missing model attribution..."
echo ""

bq query --use_legacy_sql=false "
SELECT
  system_id,
  COUNT(*) as predictions_without_attribution,
  MIN(created_at) as earliest,
  MAX(created_at) as latest
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE $DATE_FILTER
  AND system_id LIKE 'catboost_%'
  AND model_file_name IS NULL
GROUP BY system_id
ORDER BY predictions_without_attribution DESC
LIMIT 10"

echo ""
echo "Step 4: Verifying model file names match GCS..."
echo ""

# List actual model files in GCS
echo "Files in GCS bucket:"
gsutil ls gs://nba-props-platform-models/catboost/v9/*.cbm | tail -5

echo ""
echo "Step 5: Sample predictions with full attribution..."
echo ""

bq query --use_legacy_sql=false --max_rows=5 "
SELECT
  game_date,
  player_lookup,
  system_id,
  predicted_points,
  model_file_name,
  model_training_start_date,
  model_training_end_date,
  model_expected_mae,
  created_at
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE $DATE_FILTER
  AND model_file_name IS NOT NULL
ORDER BY created_at DESC
LIMIT 5"

echo ""
echo "============================================"
echo "Verification Complete!"
echo "============================================"
echo ""

# Check results and provide summary
coverage=$(bq query --use_legacy_sql=false --format=csv "
SELECT ROUND(100.0 * COUNTIF(model_file_name IS NOT NULL) / COUNT(*), 1) as coverage
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE $DATE_FILTER AND system_id = 'catboost_v9'" | tail -n +2)

echo "Summary:"
echo "--------"
echo "CatBoost V9 Coverage: ${coverage}%"
echo ""

if (( $(echo "$coverage >= 99" | bc -l) )); then
    echo "✅ PASS: Model attribution is working correctly"
    echo ""
    echo "Next steps:"
    echo "1. Model attribution is being tracked"
    echo "2. You can now distinguish which model version produced which results"
    echo "3. Historical analysis is possible using model_file_name field"
    exit 0
elif (( $(echo "$coverage >= 50" | bc -l) )); then
    echo "⚠️  PARTIAL: Model attribution is partially working"
    echo ""
    echo "Action needed:"
    echo "1. Check if prediction-worker was deployed with latest code"
    echo "2. Some predictions may be from older workers without attribution"
    echo "3. Wait for next prediction run to verify 100% coverage"
    exit 1
else
    echo "❌ FAIL: Model attribution is not working"
    echo ""
    echo "Troubleshooting steps:"
    echo "1. Verify prediction-worker deployment:"
    echo "   ./bin/check-deployment-drift.sh --verbose"
    echo ""
    echo "2. Check worker logs for errors:"
    echo "   gcloud logging read 'resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"prediction-worker\"' --limit=20"
    echo ""
    echo "3. Verify schema migration was applied:"
    echo "   bq show --schema nba_predictions.player_prop_predictions | grep model_file_name"
    exit 1
fi
