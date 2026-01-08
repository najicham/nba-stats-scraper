#!/bin/bash
# MLB Daily health check script - run each morning to verify pipeline status
# Usage: ./bin/monitoring/mlb_daily_health_check.sh [DATE]

DATE=${1:-$(TZ=America/New_York date +%Y-%m-%d)}
YESTERDAY=$(TZ=America/New_York date -d "$DATE - 1 day" +%Y-%m-%d)

echo "================================================"
echo "MLB DAILY HEALTH CHECK: $DATE"
echo "================================================"
echo ""

# 1. Check MLB services health
echo "SERVICE HEALTH:"
for svc in mlb-phase1-scrapers mlb-phase3-analytics-processors mlb-phase4-precompute-processors mlb-prediction-worker mlb-phase6-grading; do
  STATUS=$(curl -s --max-time 5 "https://${svc}-f7p3g7f6ya-wl.a.run.app/health" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null)
  if [ -z "$STATUS" ] || [ "$STATUS" = "null" ]; then
    echo "   $svc: UNKNOWN (no response)"
  elif [ "$STATUS" = "healthy" ]; then
    echo "   $svc: OK"
  else
    echo "   $svc: $STATUS"
  fi
done

# 2. Check games scheduled (MLB season check)
echo ""
echo "GAMES SCHEDULED:"
GAMES=$(bq query --use_legacy_sql=false --format=csv --quiet "
SELECT COUNT(DISTINCT game_pk)
FROM mlb_raw.mlb_schedule
WHERE game_date = '$DATE'" 2>/dev/null | tail -1)
echo "   Games scheduled for $DATE: ${GAMES:-0}"

if [ "${GAMES:-0}" = "0" ]; then
  echo "   (MLB is likely in off-season or no games today)"
fi

# 3. Check raw pitcher data availability
echo ""
echo "RAW DATA (Last 7 Days):"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  game_date,
  COUNT(*) as pitcher_stats,
  COUNT(DISTINCT game_id) as games
FROM mlb_raw.mlb_pitcher_stats
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 7" 2>/dev/null

# 4. Check analytics data
echo ""
echo "ANALYTICS (pitcher_game_summary):"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  game_date,
  COUNT(*) as summaries,
  COUNT(DISTINCT player_lookup) as pitchers
FROM mlb_analytics.pitcher_game_summary
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 7" 2>/dev/null

# 5. Check precompute features
echo ""
echo "PRECOMPUTE (pitcher_ml_features):"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  game_date,
  COUNT(*) as features,
  COUNT(DISTINCT player_lookup) as pitchers
FROM mlb_precompute.pitcher_ml_features
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 7" 2>/dev/null

# 6. Check predictions
echo ""
echo "PREDICTIONS:"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNT(DISTINCT pitcher_lookup) as pitchers,
  ROUND(AVG(confidence), 1) as avg_confidence
FROM mlb_predictions.pitcher_strikeouts
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 7" 2>/dev/null

# 7. Check grading results
echo ""
echo "GRADING RESULTS (Last 7 Days):"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(is_correct = TRUE) as correct,
  COUNTIF(is_correct = FALSE) as incorrect,
  ROUND(100.0 * COUNTIF(is_correct = TRUE) / NULLIF(COUNT(*), 0), 1) as accuracy_pct
FROM mlb_predictions.pitcher_strikeouts
WHERE graded_at IS NOT NULL
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 7" 2>/dev/null

# 8. Check for recent errors
echo ""
echo "RECENT ERRORS (last 6h):"
ERROR_COUNT=$(gcloud logging read 'resource.labels.service_name=~"mlb" AND severity>=ERROR' \
  --limit=10 --format="value(timestamp)" --freshness=6h 2>/dev/null | wc -l)
if [ "$ERROR_COUNT" -gt 0 ]; then
  echo "   Found $ERROR_COUNT errors:"
  gcloud logging read 'resource.labels.service_name=~"mlb" AND severity>=ERROR' \
    --limit=5 --format="table(timestamp,resource.labels.service_name,textPayload)" --freshness=6h 2>/dev/null | head -20
else
  echo "   No MLB errors in last 6 hours"
fi

# 9. Check scheduler job status
echo ""
echo "SCHEDULER JOBS:"
gcloud scheduler jobs list --location=us-west2 --format="table(ID,STATE,SCHEDULE)" 2>/dev/null | grep mlb

# 10. Check Pub/Sub subscriptions
echo ""
echo "PUB/SUB SUBSCRIPTIONS:"
for sub in mlb-phase3-analytics-sub mlb-phase4-precompute-sub mlb-phase5-predictions-sub mlb-phase6-grading-sub; do
  UNACKED=$(gcloud pubsub subscriptions describe $sub --format="value(numUnackedMessages)" 2>/dev/null)
  echo "   $sub: ${UNACKED:-0} unacked messages"
done

# Summary
echo ""
echo "================================================"
echo "SUMMARY"
echo "================================================"

# Determine overall status
OVERALL_STATUS="HEALTHY"

# Check if any service is down
for svc in mlb-phase1-scrapers mlb-phase3-analytics-processors mlb-phase4-precompute-processors mlb-prediction-worker mlb-phase6-grading; do
  STATUS=$(curl -s --max-time 3 "https://${svc}-f7p3g7f6ya-wl.a.run.app/health" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null)
  if [ "$STATUS" != "healthy" ]; then
    OVERALL_STATUS="DEGRADED"
    break
  fi
done

# Check for errors
if [ "$ERROR_COUNT" -gt 5 ]; then
  OVERALL_STATUS="NEEDS ATTENTION"
fi

echo "Pipeline Status: $OVERALL_STATUS"
echo "Date: $DATE"
echo "Games Today: ${GAMES:-0}"
echo "Recent Errors: ${ERROR_COUNT:-0}"
echo ""
echo "Run at: $(TZ=America/New_York date '+%Y-%m-%d %H:%M:%S %Z')"
