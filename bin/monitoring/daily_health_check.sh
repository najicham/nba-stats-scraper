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

# 3. Prediction Coverage (Expected vs Actual)
echo ""
echo "PREDICTION COVERAGE (Last 7 Days):"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  ppc.game_date,
  ppc.unique_players as predicted,
  ctx.total_players as expected,
  ROUND(100.0 * ppc.unique_players / NULLIF(ctx.total_players, 0), 1) as coverage_pct,
  ctx.total_players - ppc.unique_players as missing
FROM (
  SELECT game_date, COUNT(DISTINCT player_lookup) as unique_players
  FROM nba_predictions.player_prop_predictions
  WHERE is_active = TRUE GROUP BY 1
) ppc
JOIN (
  SELECT game_date, COUNT(*) as total_players
  FROM nba_analytics.upcoming_player_game_context
  WHERE is_production_ready = TRUE GROUP BY 1
) ctx ON ppc.game_date = ctx.game_date
WHERE ppc.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY ppc.game_date DESC" 2>/dev/null

# 4. Check Phase 3 completion state (Firestore)
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

# 5. Check ML Feature Store
echo ""
echo "ML FEATURE STORE:"
bq query --use_legacy_sql=false --format=pretty "
SELECT COUNT(*) as features
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '$DATE'" 2>/dev/null

# 6. Check for recent errors
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

# 7. Service health
echo ""
echo "SERVICE HEALTH:"
for svc in nba-phase3-analytics-processors nba-phase4-precompute-processors prediction-coordinator; do
  STATUS=$(curl -s --max-time 5 "https://${svc}-f7p3g7f6ya-wl.a.run.app/health" 2>/dev/null | jq -r '.status' 2>/dev/null)
  if [ -z "$STATUS" ] || [ "$STATUS" = "null" ]; then
    STATUS="UNREACHABLE"
  fi
  printf "   %-40s %s\n" "$svc:" "$STATUS"
done

# 8. Quick summary
echo ""
echo "================================================"
echo "SUMMARY:"
PRED_COUNT=$(bq query --use_legacy_sql=false --format=csv --quiet "SELECT COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date = '$DATE' AND is_active = TRUE" 2>/dev/null | tail -1)

# Get today's coverage percentage
COVERAGE_PCT=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT ROUND(100.0 * ppc.unique_players / NULLIF(ctx.total_players, 0), 1) as coverage_pct
FROM (SELECT COUNT(DISTINCT player_lookup) as unique_players FROM nba_predictions.player_prop_predictions WHERE game_date = '$DATE' AND is_active = TRUE) ppc
CROSS JOIN (SELECT COUNT(*) as total_players FROM nba_analytics.upcoming_player_game_context WHERE game_date = '$DATE' AND is_production_ready = TRUE) ctx" 2>/dev/null | tail -1)

if [ "${PRED_COUNT:-0}" -gt 0 ]; then
  echo "   Pipeline status: HEALTHY (${PRED_COUNT} predictions)"
  if [ -n "$COVERAGE_PCT" ] && [ "$COVERAGE_PCT" != "null" ]; then
    COVERAGE_INT=${COVERAGE_PCT%.*}
    if [ "${COVERAGE_INT:-0}" -lt 40 ]; then
      echo "   ⚠️  Coverage WARNING: ${COVERAGE_PCT}% (expected ~46% due to min_minutes filter)"
    else
      echo "   Coverage: ${COVERAGE_PCT}%"
    fi
  fi
else
  echo "   Pipeline status: NEEDS ATTENTION (no predictions for $DATE)"
fi
echo "================================================"
echo "Check complete at $(date)"
