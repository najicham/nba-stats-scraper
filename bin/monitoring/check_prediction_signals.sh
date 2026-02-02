#!/bin/bash
# check_prediction_signals.sh - Check daily prediction signals for anomalies
#
# Detects extreme UNDER/OVER signals that historically correlate with
# lower hit rates. Based on Session 70 analysis:
# - Balanced (25-45% OVER): 82% hit rate on high-edge picks
# - Heavy UNDER (<25% OVER): 54% hit rate (barely above breakeven)
#
# Usage: ./bin/monitoring/check_prediction_signals.sh [--date YYYY-MM-DD]
#
# Exit codes:
#   0 = GREEN signal (balanced)
#   1 = YELLOW signal (caution)
#   2 = RED signal (extreme skew)

set -euo pipefail

PROJECT_ID="nba-props-platform"
TARGET_DATE="${1:-TODAY}"

# Resolve date
if [ "$TARGET_DATE" = "TODAY" ] || [ "$TARGET_DATE" = "--date" ]; then
    if [ "$TARGET_DATE" = "--date" ]; then
        TARGET_DATE="${2:-TODAY}"
    fi
fi

if [ "$TARGET_DATE" = "TODAY" ]; then
    TARGET_DATE=$(TZ="America/New_York" date +%Y-%m-%d)
fi

echo "========================================"
echo "Pre-Game Signal Check: $TARGET_DATE"
echo "========================================"
echo ""

# Query signal data
RESULT=$(bq query --use_legacy_sql=false --format=json "
SELECT
  game_date,
  system_id,
  total_picks,
  high_edge_picks,
  ROUND(pct_over, 1) as pct_over,
  ROUND(pct_under, 1) as pct_under,
  daily_signal,
  signal_explanation,
  skew_category,
  volume_category
FROM nba_predictions.daily_prediction_signals
WHERE game_date = DATE('$TARGET_DATE')
  AND system_id = 'catboost_v9'
LIMIT 1" 2>/dev/null)

if [ -z "$RESULT" ] || [ "$RESULT" = "[]" ]; then
    echo "WARNING: No signal data found for $TARGET_DATE"
    echo ""
    echo "This could mean:"
    echo "  1. Predictions haven't been generated yet"
    echo "  2. Signal calculation hasn't run"
    echo ""
    echo "Check predictions: bq query \"SELECT COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date = '$TARGET_DATE'\""
    exit 0
fi

# Parse JSON result
SIGNAL=$(echo "$RESULT" | jq -r '.[0].daily_signal // "UNKNOWN"')
PCT_OVER=$(echo "$RESULT" | jq -r '.[0].pct_over // 0')
PCT_UNDER=$(echo "$RESULT" | jq -r '.[0].pct_under // 0')
TOTAL_PICKS=$(echo "$RESULT" | jq -r '.[0].total_picks // 0')
HIGH_EDGE=$(echo "$RESULT" | jq -r '.[0].high_edge_picks // 0')
EXPLANATION=$(echo "$RESULT" | jq -r '.[0].signal_explanation // "No explanation"')
SKEW=$(echo "$RESULT" | jq -r '.[0].skew_category // "UNKNOWN"')

# Display results
echo "System: catboost_v9"
echo "Date: $TARGET_DATE"
echo ""
echo "Signal Summary:"
echo "  Total Picks:      $TOTAL_PICKS"
echo "  High-Edge Picks:  $HIGH_EDGE"
echo "  % OVER:           $PCT_OVER%"
echo "  % UNDER:          $PCT_UNDER%"
echo "  Skew Category:    $SKEW"
echo ""

# Determine status and exit code
case $SIGNAL in
    GREEN)
        echo "========================================"
        echo "✅ SIGNAL: GREEN - Balanced"
        echo "========================================"
        echo ""
        echo "$EXPLANATION"
        echo ""
        echo "Action: Full confidence in picks"
        EXIT_CODE=0
        ;;
    YELLOW)
        echo "========================================"
        echo "🟡 SIGNAL: YELLOW - Caution"
        echo "========================================"
        echo ""
        echo "$EXPLANATION"
        echo ""
        echo "Action: Monitor performance closely"
        EXIT_CODE=1
        ;;
    RED)
        echo "========================================"
        echo "🔴 SIGNAL: RED - Warning"
        echo "========================================"
        echo ""
        echo "$EXPLANATION"
        echo ""
        echo "Action: Consider reducing bet sizing by 50%"
        echo "        Or skip high-edge picks today"
        echo ""
        echo "Historical context:"
        echo "  - Balanced days (25-45% OVER): 82% hit rate"
        echo "  - Heavy UNDER days (<25% OVER): 54% hit rate"
        echo "  - Statistical significance: p=0.0065"
        EXIT_CODE=2
        ;;
    *)
        echo "========================================"
        echo "⚠️  SIGNAL: UNKNOWN"
        echo "========================================"
        echo ""
        echo "Could not determine signal status"
        EXIT_CODE=0
        ;;
esac

# Show recent trend
echo ""
echo "Recent Signal Trend (Last 7 Days):"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  game_date,
  ROUND(pct_over, 1) as pct_over,
  daily_signal
FROM nba_predictions.daily_prediction_signals
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(DATE('$TARGET_DATE'), INTERVAL 6 DAY)
  AND game_date <= DATE('$TARGET_DATE')
ORDER BY game_date DESC" 2>/dev/null

exit $EXIT_CODE
