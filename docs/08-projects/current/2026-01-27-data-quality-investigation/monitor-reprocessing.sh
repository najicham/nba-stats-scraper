#!/bin/bash
# Monitor reprocessing progress for Jan 26-27 data quality fixes
# Run this script to continuously monitor the reprocessing

echo "==================================================================="
echo "Data Quality Reprocessing Monitor"
echo "Started: $(date)"
echo "==================================================================="
echo ""

# Target metrics
TARGET_USAGE_RATE=90.0
TARGET_PREDICTIONS=80
TARGET_LINES=80

# Baseline metrics
BASELINE_USAGE_RATE=57.8
BASELINE_PREDICTIONS=0
BASELINE_LINES=37

# Counter
ITERATION=0
MAX_ITERATIONS=60  # Monitor for 1 hour (60 checks at 60 seconds each)

while [ $ITERATION -lt $MAX_ITERATIONS ]; do
    ITERATION=$((ITERATION + 1))

    echo "==================================================================="
    echo "Check #$ITERATION at $(date)"
    echo "==================================================================="

    # Check Jan 26 usage_rate
    echo ""
    echo "📊 Jan 26 Usage Rate (Target: ${TARGET_USAGE_RATE}%, Baseline: ${BASELINE_USAGE_RATE}%)"
    USAGE_RATE=$(bq query --use_legacy_sql=false --format=csv "
    SELECT ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL AND usage_rate <= 50) / COUNT(*), 1) as usage_pct
    FROM \`nba-props-platform.nba_analytics.player_game_summary\`
    WHERE game_date = '2026-01-26'" | tail -n 1)
    echo "   Current: ${USAGE_RATE}%"

    # Check if improved
    if (( $(echo "$USAGE_RATE > $BASELINE_USAGE_RATE" | bc -l) )); then
        echo "   ✅ IMPROVED from baseline!"
        if (( $(echo "$USAGE_RATE >= $TARGET_USAGE_RATE" | bc -l) )); then
            echo "   🎉 TARGET REACHED!"
        fi
    else
        echo "   ⏳ No change yet (still at baseline)"
    fi

    # Check Jan 27 predictions
    echo ""
    echo "🔮 Jan 27 Predictions (Target: ${TARGET_PREDICTIONS}+, Baseline: ${BASELINE_PREDICTIONS})"
    PREDICTIONS=$(bq query --use_legacy_sql=false --format=csv "
    SELECT COUNT(*) as prediction_count
    FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
    WHERE game_date = '2026-01-27' AND is_active = TRUE" | tail -n 1)
    echo "   Current: ${PREDICTIONS}"

    if [ "$PREDICTIONS" -gt "$BASELINE_PREDICTIONS" ]; then
        echo "   ✅ PREDICTIONS GENERATED!"
        if [ "$PREDICTIONS" -ge "$TARGET_PREDICTIONS" ]; then
            echo "   🎉 TARGET REACHED!"
        fi
    else
        echo "   ⏳ No predictions yet"
    fi

    # Check Jan 27 betting lines
    echo ""
    echo "💰 Jan 27 Betting Lines (Target: ${TARGET_LINES}+, Baseline: ${BASELINE_LINES})"
    LINES=$(bq query --use_legacy_sql=false --format=csv "
    SELECT COUNTIF(has_prop_line) as players_with_lines
    FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
    WHERE game_date = '2026-01-27'" | tail -n 1)
    echo "   Current: ${LINES} players"

    if [ "$LINES" -gt "$BASELINE_LINES" ]; then
        echo "   ✅ IMPROVED from baseline!"
        if [ "$LINES" -ge "$TARGET_LINES" ]; then
            echo "   🎉 TARGET REACHED!"
        fi
    else
        echo "   ⏳ No change yet (still at baseline)"
    fi

    # Check if all targets reached
    echo ""
    if (( $(echo "$USAGE_RATE >= $TARGET_USAGE_RATE" | bc -l) )) && [ "$PREDICTIONS" -ge "$TARGET_PREDICTIONS" ] && [ "$LINES" -ge "$TARGET_LINES" ]; then
        echo "🎉🎉🎉 ALL TARGETS REACHED! 🎉🎉🎉"
        echo ""
        echo "Reprocessing appears to be complete. Run full validation:"
        echo ""
        echo "  /validate-historical 2026-01-26 2026-01-27"
        echo ""
        echo "  python scripts/spot_check_data_accuracy.py \\"
        echo "    --start-date 2026-01-26 \\"
        echo "    --end-date 2026-01-27 \\"
        echo "    --samples 10 \\"
        echo "    --checks rolling_avg,usage_rate"
        echo ""
        break
    fi

    # Wait 60 seconds before next check (unless last iteration)
    if [ $ITERATION -lt $MAX_ITERATIONS ]; then
        echo ""
        echo "⏰ Waiting 60 seconds before next check... (Ctrl+C to stop)"
        sleep 60
    fi
done

echo ""
echo "==================================================================="
echo "Monitoring ended: $(date)"
echo "==================================================================="

if [ $ITERATION -eq $MAX_ITERATIONS ]; then
    echo ""
    echo "⚠️ Reached maximum monitoring time (1 hour)"
    echo "   Reprocessing may be taking longer than expected."
    echo ""
    echo "Next steps:"
    echo "  1. Check Cloud Functions logs for any errors"
    echo "  2. Verify Cloud Scheduler jobs are running"
    echo "  3. Consider manual trigger if needed"
    echo ""
    echo "Manual reprocessing commands:"
    echo ""
    echo "  # Trigger daily orchestrator manually"
    echo "  gcloud functions call daily-orchestrator \\"
    echo "    --data '{\"date\":\"2026-01-26\"}'"
    echo ""
fi
