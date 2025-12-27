#!/bin/bash
# Self-healing pipeline check - runs after normal pipeline
# Usage: ./bin/pipeline/self_heal_check.sh
#
# This script:
# 1. Checks if tomorrow's predictions exist
# 2. If not, triggers force_predictions.sh
# 3. Clears any stuck run_history entries
#
# Set up as scheduler: 15 14 * * * (2:15 PM ET = 30 min after same-day-predictions)

set -e

SCRIPT_DIR="$(dirname "$0")"
TOMORROW=$(TZ=America/New_York date -d "tomorrow" +%Y-%m-%d)

echo "================================================"
echo "SELF-HEALING CHECK - $(TZ=America/New_York date)"
echo "Target date: $TOMORROW"
echo "================================================"
echo ""

# Step 1: Check if predictions exist for tomorrow
PREDS=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT COUNT(*) as cnt
FROM nba_predictions.player_prop_predictions
WHERE game_date = '$TOMORROW' AND is_active = TRUE" | tail -1)

GAMES=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT COUNT(*) as cnt
FROM nba_raw.nbac_schedule
WHERE game_date = '$TOMORROW'" | tail -1)

echo "Games scheduled: $GAMES"
echo "Predictions: $PREDS"
echo ""

# Step 2: If no games, nothing to do
if [ "$GAMES" -eq 0 ]; then
  echo "✅ No games scheduled for $TOMORROW - nothing to do"
  exit 0
fi

# Step 3: If predictions missing, trigger force run
if [ "$PREDS" -eq 0 ]; then
  echo "⚠️  No predictions for $TOMORROW - triggering self-healing..."
  echo ""

  # Clear stuck entries first
  python3 -c "
from google.cloud import firestore
from datetime import datetime, timedelta, timezone

db = firestore.Client()
now = datetime.now(timezone.utc)
cutoff = now - timedelta(hours=2)

cleared = 0
for doc in db.collection('run_history').where('status', '==', 'running').stream():
    data = doc.to_dict()
    started = data.get('started_at')
    if started and started < cutoff:
        doc.reference.delete()
        cleared += 1
        print(f'Cleared stuck: {doc.id}')

print(f'Total cleared: {cleared}')
" 2>/dev/null

  # Run force predictions
  "$SCRIPT_DIR/force_predictions.sh" "$TOMORROW"

  echo ""
  echo "Self-healing complete!"
else
  echo "✅ Predictions exist ($PREDS) - pipeline healthy"
fi

# Step 4: Check quality and alert if low
QUALITY=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT ROUND(AVG(feature_quality_score), 1) as avg_quality
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$TOMORROW'" | tail -1)

if [ -n "$QUALITY" ] && [ "$QUALITY" != "null" ]; then
  if (( $(echo "$QUALITY < 70" | bc -l) )); then
    echo ""
    echo "⚠️  Quality score ($QUALITY%) below threshold (70%)"
    echo "   Predictions were generated but may be less accurate"
  fi
fi

echo ""
echo "Done!"
