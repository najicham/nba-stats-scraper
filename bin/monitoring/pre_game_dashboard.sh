#!/bin/bash
# Pre-Game Readiness Dashboard
# Runs at 5 PM ET to surface issues before games start
# Session 209: Priority 5 - Pre-Game Dashboard

set -euo pipefail

GAME_DATE=${1:-$(TZ=America/New_York date +%Y-%m-%d)}

echo "========================================"
echo "PRE-GAME READINESS DASHBOARD"
echo "Date: $GAME_DATE"
echo "Time: $(TZ=America/New_York date '+%H:%M:%S %Z')"
echo "========================================"
echo ""

# Initialize status (will be set to WARNING or CRITICAL if issues detected)
OVERALL_STATUS="OK"

# ============================================
# 1. GAMES SCHEDULED
# ============================================
GAMES=$(bq query --use_legacy_sql=false --format=csv --quiet \
  "SELECT COUNT(*) FROM nba_reference.nba_schedule
   WHERE game_date = '$GAME_DATE' AND game_status = 1" 2>/dev/null | tail -1)

echo "📅 GAMES SCHEDULED:"
if [ "$GAMES" = "0" ] || [ -z "$GAMES" ]; then
    echo "   ⚠️  No games scheduled for tonight"
    echo "   (This is expected on off-days)"
else
    echo "   ✅ $GAMES games scheduled for tonight"
fi
echo ""

# ============================================
# 2. DAILY SIGNAL
# ============================================
SIGNAL_DATA=$(bq query --use_legacy_sql=false --format=csv --quiet \
  "SELECT daily_signal, high_edge_picks, pct_over, premium_picks
   FROM nba_predictions.daily_prediction_signals
   WHERE game_date = '$GAME_DATE' AND system_id = 'catboost_v9'" 2>/dev/null | tail -1)

echo "📊 DAILY SIGNAL:"
if [ -z "$SIGNAL_DATA" ] || [ "$SIGNAL_DATA" = "daily_signal,high_edge_picks,pct_over,premium_picks" ]; then
    echo "   ❌ No signal computed yet for $GAME_DATE"
    OVERALL_STATUS="CRITICAL"
else
    IFS=',' read -r SIGNAL HIGH_EDGE PCT_OVER PREMIUM <<< "$SIGNAL_DATA"

    # Color code signal
    if [ "$SIGNAL" = "GREEN" ]; then
        SIGNAL_ICON="🟢"
    elif [ "$SIGNAL" = "YELLOW" ]; then
        SIGNAL_ICON="🟡"
    elif [ "$SIGNAL" = "RED" ]; then
        SIGNAL_ICON="🔴"
    else
        SIGNAL_ICON="⚪"
    fi

    echo "   Signal: $SIGNAL_ICON $SIGNAL"
    echo "   High edge picks (5+): $HIGH_EDGE"
    echo "   Premium picks (3+): $PREMIUM"
    echo "   Percent over: $PCT_OVER%"
fi
echo ""

# ============================================
# 3. PREDICTIONS
# ============================================
PRED_DATA=$(bq query --use_legacy_sql=false --format=csv --quiet \
  "SELECT
     COUNT(*) as total,
     COUNTIF(is_actionable) as actionable,
     COUNT(DISTINCT player_lookup) as unique_players
   FROM nba_predictions.player_prop_predictions
   WHERE game_date = '$GAME_DATE' AND is_active = TRUE" 2>/dev/null | tail -1)

echo "🎯 PREDICTIONS:"
if [ -z "$PRED_DATA" ] || [ "$PRED_DATA" = "total,actionable,unique_players" ]; then
    echo "   ❌ No predictions generated yet for $GAME_DATE"
    OVERALL_STATUS="CRITICAL"
else
    IFS=',' read -r TOTAL ACTIONABLE UNIQUE_PLAYERS <<< "$PRED_DATA"

    if [ "$ACTIONABLE" -lt 50 ]; then
        echo "   ⚠️  Total predictions: $TOTAL"
        echo "   ⚠️  Actionable (edge 3+): $ACTIONABLE (LOW - expected >100)"
        OVERALL_STATUS="WARNING"
    else
        echo "   ✅ Total predictions: $TOTAL"
        echo "   ✅ Actionable (edge 3+): $ACTIONABLE"
    fi
    echo "   Unique players: $UNIQUE_PLAYERS"
fi
echo ""

# ============================================
# 4. FEATURE QUALITY
# ============================================
QUALITY_DATA=$(bq query --use_legacy_sql=false --format=csv --quiet \
  "SELECT
     COUNT(*) as total,
     COUNTIF(is_quality_ready) as ready,
     COUNTIF(quality_alert_level = 'red') as red_alerts,
     COUNTIF(quality_alert_level = 'yellow') as yellow_alerts,
     COUNTIF(quality_alert_level = 'green') as green_alerts
   FROM nba_predictions.ml_feature_store_v2
   WHERE game_date = '$GAME_DATE'" 2>/dev/null | tail -1)

echo "🔬 FEATURE QUALITY:"
if [ -z "$QUALITY_DATA" ] || [ "$QUALITY_DATA" = "total,ready,red_alerts,yellow_alerts,green_alerts" ]; then
    echo "   ❌ No feature store data yet for $GAME_DATE"
    OVERALL_STATUS="CRITICAL"
else
    IFS=',' read -r TOTAL READY RED YELLOW GREEN <<< "$QUALITY_DATA"

    if [ "$TOTAL" -gt 0 ]; then
        READY_PCT=$(awk "BEGIN {printf \"%.1f\", 100.0 * $READY / $TOTAL}")

        if (( $(echo "$READY_PCT < 70" | bc -l) )); then
            echo "   ⚠️  Quality-ready: $READY / $TOTAL (${READY_PCT}% - target 75%+)"
            OVERALL_STATUS="WARNING"
        else
            echo "   ✅ Quality-ready: $READY / $TOTAL (${READY_PCT}%)"
        fi

        echo "   Alert levels:"
        echo "     Green:  $GREEN"
        echo "     Yellow: $YELLOW"
        if [ "$RED" -gt 0 ]; then
            echo "     Red:    $RED ⚠️"
        else
            echo "     Red:    $RED"
        fi
    else
        echo "   ⚠️  No players in feature store"
        OVERALL_STATUS="WARNING"
    fi
fi
echo ""

# ============================================
# 5. PHASE 3 COMPLETION
# ============================================
echo "📋 PHASE 3 PROCESSORS:"
PHASE3_STATUS=$(python3 << EOF
from google.cloud import firestore

db = firestore.Client(project='nba-props-platform')
doc = db.collection('phase3_completion').document('$GAME_DATE').get()

if doc.exists:
    data = doc.to_dict()
    completed = [k for k in data.keys() if not k.startswith('_')]
    mode = data.get('_mode', 'unknown')
    triggered = data.get('_triggered', False)

    # Mode-specific expectations
    expected = {'overnight': 5, 'same_day': 3, 'evening': 4}.get(mode, 5)
    count = len(completed)

    if count >= expected:
        print(f"OK|{count}|{expected}|{mode}|{triggered}")
    elif count >= expected - 1:
        print(f"WARNING|{count}|{expected}|{mode}|{triggered}")
    else:
        print(f"CRITICAL|{count}|{expected}|{mode}|{triggered}")
else:
    print("CRITICAL|0|5|unknown|False")
EOF
)

IFS='|' read -r P3_STATUS P3_COUNT P3_EXPECTED P3_MODE P3_TRIGGERED <<< "$PHASE3_STATUS"

if [ "$P3_STATUS" = "OK" ]; then
    echo "   ✅ Complete: $P3_COUNT/$P3_EXPECTED processors (mode: $P3_MODE)"
elif [ "$P3_STATUS" = "WARNING" ]; then
    echo "   ⚠️  Incomplete: $P3_COUNT/$P3_EXPECTED processors (mode: $P3_MODE)"
    OVERALL_STATUS="WARNING"
else
    echo "   ❌ Not run: $P3_COUNT/$P3_EXPECTED processors"
    OVERALL_STATUS="CRITICAL"
fi
echo "   Phase 4 triggered: $P3_TRIGGERED"
echo ""

# ============================================
# OVERALL STATUS SUMMARY
# ============================================
echo "========================================"
if [ "$OVERALL_STATUS" = "OK" ]; then
    echo "✅ OVERALL STATUS: READY FOR TONIGHT"
    echo ""
    echo "All systems nominal. Predictions are ready."
    exit 0
elif [ "$OVERALL_STATUS" = "WARNING" ]; then
    echo "⚠️  OVERALL STATUS: WARNINGS DETECTED"
    echo ""
    echo "Some issues detected but predictions are available."
    echo "Review warnings above before games start."
    exit 1
else
    echo "❌ OVERALL STATUS: CRITICAL ISSUES"
    echo ""
    echo "Critical problems detected. Investigation required."
    echo "Predictions may not be ready for tonight's games."
    exit 2
fi
