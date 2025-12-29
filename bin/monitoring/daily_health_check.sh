#!/bin/bash
# Daily health check script - run each morning to verify pipeline status
# Usage: ./bin/monitoring/daily_health_check.sh [DATE]

DATE=${1:-$(TZ=America/New_York date +%Y-%m-%d)}
YESTERDAY=$(TZ=America/New_York date -d "$DATE - 1 day" +%Y-%m-%d)

echo "================================================"
echo "DAILY HEALTH CHECK: $DATE"
echo "================================================"
echo ""

# 1. Check today's games from NBA API
echo "GAMES SCHEDULED:"
GAMES=$(curl -s "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json" 2>/dev/null | jq '.scoreboard.games | length' 2>/dev/null)
if [ -z "$GAMES" ] || [ "$GAMES" = "null" ]; then
  # Fallback to BigQuery
  GAMES=$(bq query --use_legacy_sql=false --format=csv --quiet "SELECT COUNT(DISTINCT game_id) FROM nba_raw.nbac_schedule WHERE game_date = '$DATE'" 2>/dev/null | tail -1)
fi
echo "   Games scheduled for $DATE: ${GAMES:-0}"

# 2. Check predictions for today
echo ""
echo "TODAY'S PREDICTIONS:"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  COUNT(*) as predictions,
  COUNT(DISTINCT game_id) as games,
  COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.player_prop_predictions
WHERE game_date = '$DATE' AND is_active = TRUE" 2>/dev/null

# 3. Check Phase 3 completion state (Firestore)
echo ""
echo "PHASE 3 COMPLETION STATE:"
python3 << EOF
from google.cloud import firestore
db = firestore.Client()
doc = db.collection('phase3_completion').document('$DATE').get()
if doc.exists:
    data = doc.to_dict()
    completed = [k for k in data if not k.startswith('_')]
    triggered = data.get('_triggered', False)
    print(f"   Processors complete: {len(completed)}/5")
    print(f"   Phase 4 triggered: {triggered}")
    for k in completed:
        print(f"     - {k}")
else:
    print("   No completion data yet")
EOF

# 4. Check ML Feature Store
echo ""
echo "ML FEATURE STORE:"
bq query --use_legacy_sql=false --format=pretty "
SELECT COUNT(*) as features
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$DATE'" 2>/dev/null

# 5. Check for recent errors
echo ""
echo "RECENT ERRORS (last 2h):"
ERROR_COUNT=$(gcloud logging read 'resource.type="cloud_run_revision" AND severity>=ERROR' \
  --limit=5 --format="value(timestamp)" --freshness=2h 2>/dev/null | wc -l)
if [ "$ERROR_COUNT" -gt 0 ]; then
  gcloud logging read 'resource.type="cloud_run_revision" AND severity>=ERROR' \
    --limit=5 --format="table(timestamp,resource.labels.service_name)" --freshness=2h 2>/dev/null
else
  echo "   No errors in last 2 hours"
fi

# 6. Service health
echo ""
echo "SERVICE HEALTH:"
for svc in nba-phase3-analytics-processors nba-phase4-precompute-processors prediction-coordinator; do
  STATUS=$(curl -s --max-time 5 "https://${svc}-f7p3g7f6ya-wl.a.run.app/health" 2>/dev/null | jq -r '.status' 2>/dev/null)
  if [ -z "$STATUS" ] || [ "$STATUS" = "null" ]; then
    STATUS="UNREACHABLE"
  fi
  printf "   %-40s %s\n" "$svc:" "$STATUS"
done

# 7. Quick summary
echo ""
echo "================================================"
echo "SUMMARY:"
PRED_COUNT=$(bq query --use_legacy_sql=false --format=csv --quiet "SELECT COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date = '$DATE' AND is_active = TRUE" 2>/dev/null | tail -1)
if [ "${PRED_COUNT:-0}" -gt 0 ]; then
  echo "   Pipeline status: HEALTHY (${PRED_COUNT} predictions)"
else
  echo "   Pipeline status: NEEDS ATTENTION (no predictions for $DATE)"
fi
echo "================================================"
echo "Check complete at $(date)"
