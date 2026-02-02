#!/bin/bash
# Validate Feb 2, 2026 NEW V9 Model Performance
# Session 83 - Post-game validation script
#
# Run this AFTER Feb 2 games finish (after ~midnight ET)
#
# Usage:
#   ./bin/validate-feb2-model-performance.sh

set -e

echo "==================================="
echo "Feb 2 NEW V9 Model Validation"
echo "==================================="
echo ""

# Check if games are finished
echo "Step 1: Checking game status..."
game_status=$(bq query --use_legacy_sql=false --format=csv "
SELECT
  COUNT(*) as total_games,
  COUNTIF(game_status = 3) as finished_games,
  COUNTIF(game_status = 1) as scheduled_games,
  COUNTIF(game_status = 2) as in_progress_games
FROM nba_reference.nba_schedule
WHERE game_date = DATE('2026-02-02')" | tail -n +2)

echo "$game_status"

finished=$(echo "$game_status" | cut -d',' -f2)
total=$(echo "$game_status" | cut -d',' -f1)

if [ "$finished" != "$total" ]; then
    echo ""
    echo "WARNING: Not all games finished yet ($finished/$total)"
    echo "Some games may still be in progress or scheduled"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Exiting. Run this script after all games finish."
        exit 0
    fi
fi

echo ""
echo "Step 2: Running grading backfill for Feb 2..."
PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py --dates 2026-02-02

echo ""
echo "Step 3: Validating catboost_v9 performance..."
echo ""

# Get catboost_v9 performance
bq query --use_legacy_sql=false "
SELECT
  system_id,
  COUNT(*) as predictions,
  COUNTIF(prediction_correct IS NOT NULL) as graded,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae,
  ROUND(AVG(predicted_points - actual_points), 2) as bias
FROM nba_predictions.prediction_accuracy
WHERE game_date = DATE('2026-02-02')
  AND system_id = 'catboost_v9'
GROUP BY system_id"

echo ""
echo "Expected NEW Model Performance:"
echo "  - MAE: ~4.12"
echo "  - Hit Rate: ~74.6% (high-edge), ~56.5% (premium)"
echo "  - Bias: Negative (RED signal day - 79.5% UNDER recommendations)"
echo ""

echo "Step 4: Comparing catboost_v9 vs catboost_v9_2026_02..."
echo ""

bq query --use_legacy_sql=false "
SELECT
  system_id,
  COUNT(*) as predictions,
  COUNTIF(prediction_correct IS NOT NULL) as graded,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae,
  ROUND(AVG(predicted_points - actual_points), 2) as bias
FROM nba_predictions.prediction_accuracy
WHERE game_date = DATE('2026-02-02')
  AND system_id IN ('catboost_v9', 'catboost_v9_2026_02')
GROUP BY system_id
ORDER BY hit_rate DESC"

echo ""
echo "Expected: catboost_v9 should outperform catboost_v9_2026_02"
echo "  - catboost_v9: MAE ~4.12, HR ~74.6%"
echo "  - catboost_v9_2026_02: MAE ~5.08, HR ~50.84%"
echo ""

echo "Step 5: Analyzing by confidence and edge..."
echo ""

bq query --use_legacy_sql=false "
SELECT
  system_id,
  CASE
    WHEN confidence_score >= 92 AND ABS(predicted_points - line_value) >= 3 THEN 'Premium (92+ conf, 3+ edge)'
    WHEN ABS(predicted_points - line_value) >= 5 THEN 'High Edge (5+ edge)'
    ELSE 'Other'
  END as tier,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae
FROM nba_predictions.prediction_accuracy
WHERE game_date = DATE('2026-02-02')
  AND system_id = 'catboost_v9'
  AND prediction_correct IS NOT NULL
GROUP BY system_id, tier
ORDER BY tier"

echo ""
echo "Step 6: RED Signal Day Hypothesis Test..."
echo ""

# Check UNDER bias impact
bq query --use_legacy_sql=false "
SELECT
  recommendation,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae
FROM nba_predictions.prediction_accuracy
WHERE game_date = DATE('2026-02-02')
  AND system_id = 'catboost_v9'
  AND prediction_correct IS NOT NULL
GROUP BY recommendation"

echo ""
echo "RED Signal Day Context:"
echo "  - Feb 2 had 79.5% UNDER recommendations (extreme bias)"
echo "  - Historical RED days: 54% hit rate"
echo "  - Balanced days: 82% hit rate"
echo "  - Question: Did UNDER recs underperform tonight?"
echo ""

echo "Step 7: All Models Comparison..."
echo ""

bq query --use_legacy_sql=false "
SELECT
  system_id,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae
FROM nba_predictions.prediction_accuracy
WHERE game_date = DATE('2026-02-02')
  AND prediction_correct IS NOT NULL
GROUP BY system_id
ORDER BY hit_rate DESC"

echo ""
echo "==================================="
echo "Validation Complete!"
echo "==================================="
echo ""
echo "Next Steps:"
echo "1. Review performance vs expectations"
echo "2. If catboost_v9 MAE ~4.12 and HR ~74.6%: ✅ NEW model working!"
echo "3. If catboost_v9 MAE >5.0 and HR <55%: ⚠️ Wrong model loaded"
echo "4. Document findings in Session 83 handoff"
echo "5. Consider disabling catboost_v9_2026_02 if it underperforms"
echo ""
