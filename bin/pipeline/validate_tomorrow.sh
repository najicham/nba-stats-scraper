#!/bin/bash
# Validate that tomorrow's predictions are ready
# Usage: ./bin/pipeline/validate_tomorrow.sh
#
# This script checks if the pipeline is healthy and predictions exist.
# Run this in the morning or set up as a scheduler for early warning.

set -euo pipefail

TOMORROW=$(TZ=America/New_York date -d "tomorrow" +%Y-%m-%d)
TODAY=$(TZ=America/New_York date +%Y-%m-%d)
ALERT_THRESHOLD=70  # Minimum quality score

echo "=============================================="
echo "PIPELINE VALIDATION - $(TZ=America/New_York date)"
echo "=============================================="
echo ""

# Check 1: Tomorrow's games scheduled?
echo "📅 [1/5] Checking scheduled games..."
GAMES=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT COUNT(*) as games
FROM nba_raw.nbac_schedule
WHERE game_date = '$TOMORROW'" | tail -1)

if [ "$GAMES" -eq 0 ]; then
  echo "  ⚠️  No games scheduled for $TOMORROW (might be off day)"
  exit 0
else
  echo "  ✅ $GAMES games scheduled for $TOMORROW"
fi

# Check 2: Predictions exist?
echo ""
echo "🎯 [2/5] Checking predictions..."
PREDS=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT COUNT(*) as cnt
FROM nba_predictions.player_prop_predictions
WHERE game_date = '$TOMORROW' AND is_active = TRUE" | tail -1)

if [ "$PREDS" -eq 0 ]; then
  echo "  ❌ NO PREDICTIONS for $TOMORROW"
  PRED_STATUS="MISSING"
else
  PLAYERS=$(bq query --use_legacy_sql=false --format=csv --quiet "
  SELECT COUNT(DISTINCT player_lookup) as cnt
  FROM nba_predictions.player_prop_predictions
  WHERE game_date = '$TOMORROW' AND is_active = TRUE" | tail -1)
  echo "  ✅ $PREDS predictions for $PLAYERS players"
  PRED_STATUS="OK"
fi

# Check 3: Quality scores
echo ""
echo "📊 [3/5] Checking quality scores..."
QUALITY=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT ROUND(AVG(feature_quality_score), 1) as avg_quality
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$TOMORROW'" | tail -1 | tr -d '"')

if [ -z "$QUALITY" ] || [ "$QUALITY" = "null" ] || [ "$QUALITY" = "" ]; then
  echo "  ⚠️  No quality data for $TOMORROW yet"
  QUALITY_STATUS="PENDING"
else
  # Use awk for numeric comparison (more reliable than bc)
  if awk "BEGIN {exit !($QUALITY < $ALERT_THRESHOLD)}"; then
    echo "  ⚠️  Quality score $QUALITY% is below threshold ($ALERT_THRESHOLD%)"
    QUALITY_STATUS="LOW"
  else
    echo "  ✅ Quality score: $QUALITY%"
    QUALITY_STATUS="OK"
  fi
fi

# Check 4: Stuck run_history entries
echo ""
echo "🔄 [4/5] Checking for stuck processes..."
STUCK=$(python3 -c "
from google.cloud import firestore
from datetime import datetime, timedelta, timezone

db = firestore.Client()
now = datetime.now(timezone.utc)
cutoff = now - timedelta(hours=4)

stuck = 0
for doc in db.collection('run_history').where('status', '==', 'running').stream():
    data = doc.to_dict()
    started = data.get('started_at')
    if started and started < cutoff:
        stuck += 1
print(stuck)
" 2>/dev/null)

if [ "$STUCK" -gt 0 ]; then
  echo "  ⚠️  $STUCK stuck processes found (>4 hours old)"
  STUCK_STATUS="STUCK"
else
  echo "  ✅ No stuck processes"
  STUCK_STATUS="OK"
fi

# Check 5: Today's game data processed?
echo ""
echo "📈 [5/5] Checking today's analytics data..."
TODAY_ANALYTICS=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT COUNT(DISTINCT player_lookup) as players
FROM nba_analytics.player_game_summary
WHERE game_date = '$TODAY'" | tail -1)

if [ "$TODAY_ANALYTICS" -eq 0 ]; then
  echo "  ⚠️  No analytics data for today ($TODAY) yet"
else
  echo "  ✅ $TODAY_ANALYTICS players in today's analytics"
fi

# Summary
echo ""
echo "=============================================="
echo "SUMMARY"
echo "=============================================="

if [ "$PRED_STATUS" = "MISSING" ]; then
  echo "❌ CRITICAL: Predictions missing for $TOMORROW"
  echo ""
  echo "Run: ./bin/pipeline/force_predictions.sh $TOMORROW"
  exit 1
elif [ "$QUALITY_STATUS" = "LOW" ] || [ "$STUCK_STATUS" = "STUCK" ]; then
  echo "⚠️  WARNING: Pipeline issues detected"
  echo ""
  echo "Consider running: ./bin/pipeline/force_predictions.sh $TOMORROW"
  exit 1
elif [ "$QUALITY_STATUS" = "PENDING" ]; then
  echo "⏳ Predictions exist but quality data pending"
  echo "   (Normal before same-day pipeline runs)"
  exit 0
else
  echo "✅ Pipeline healthy - predictions ready for $TOMORROW"
  exit 0
fi
