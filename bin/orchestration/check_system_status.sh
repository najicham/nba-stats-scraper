#!/bin/bash
set -euo pipefail
# Quick System Status Check
# After processor deployment

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Post-Deployment System Status"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 1. Check processor deployment
echo "1️⃣ Processor Deployment Status:"
gcloud run services describe nba-processors \
  --region=us-west2 \
  --format="table(
    status.latestReadyRevisionName,
    status.latestCreatedRevisionName,
    status.traffic[0].percent
  )" 2>/dev/null || echo "   ❌ Could not get processor status"
echo ""

# 2. Check Pub/Sub backlog
echo "2️⃣ Pub/Sub Queue Status:"
BACKLOG=$(gcloud pubsub subscriptions describe nba-processors-sub \
  --format='value(numUndeliveredMessages)' 2>/dev/null)
if [ $? -eq 0 ]; then
  if [ "$BACKLOG" -eq 0 ]; then
    echo "   ✅ Backlog: $BACKLOG messages (healthy)"
  elif [ "$BACKLOG" -lt 100 ]; then
    echo "   ℹ️  Backlog: $BACKLOG messages (normal)"
  else
    echo "   ⚠️  Backlog: $BACKLOG messages (investigate)"
  fi
else
  echo "   ❌ Could not check backlog"
fi
echo ""

# 3. Check recent scraper activity
echo "3️⃣ Recent Scraper Activity (last hour):"
SCRAPER_RUNS=$(bq query --use_legacy_sql=false --format=csv --max_rows=1 "
SELECT COUNT(*) as total
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
" 2>/dev/null | tail -1)
echo "   Total runs: $SCRAPER_RUNS"
echo ""

# 4. Check scraper failures
echo "4️⃣ Failed Scrapers (last hour):"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  scraper_name,
  COUNT(*) as failures,
  ARRAY_AGG(error_message LIMIT 2) as sample_errors
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  AND status = 'FAILED'
GROUP BY scraper_name
ORDER BY failures DESC
LIMIT 10
" 2>/dev/null || echo "   ❌ Could not query scraper failures"
echo ""

# 5. Check recent Pub/Sub publishing
echo "5️⃣ Recent Pub/Sub Publishing (last 30 min):"
PUB_COUNT=$(gcloud logging read \
  "resource.labels.service_name=nba-scrapers
   AND textPayload:\"Published scraper-complete event\"
   AND timestamp>=\`date -u -d '30 minutes ago' --iso-8601=seconds\`" \
  --limit=1000 --format=json 2>/dev/null | jq -s 'length')
if [ $? -eq 0 ]; then
  echo "   Events published: $PUB_COUNT"
else
  echo "   ❌ Could not check publishing logs"
fi
echo ""

# 6. Check recent processor activity
echo "6️⃣ Recent Processor Activity (last 30 min):"
PROC_COUNT=$(gcloud logging read \
  "resource.labels.service_name=nba-processors
   AND textPayload:\"Successfully processed\"
   AND timestamp>=\`date -u -d '30 minutes ago' --iso-8601=seconds\`" \
  --limit=1000 --format=json 2>/dev/null | jq -s 'length')
if [ $? -eq 0 ]; then
  echo "   Files processed: $PROC_COUNT"
else
  echo "   ❌ Could not check processor logs"
fi
echo ""

# 7. Check processor errors
echo "7️⃣ Processor Errors (last 30 min):"
ERROR_COUNT=$(gcloud logging read \
  "resource.labels.service_name=nba-processors
   AND severity=ERROR
   AND timestamp>=\`date -u -d '30 minutes ago' --iso-8601=seconds\`" \
  --limit=100 --format=json 2>/dev/null | jq -s 'length')
if [ $? -eq 0 ]; then
  if [ "$ERROR_COUNT" -eq 0 ]; then
    echo "   ✅ No errors"
  else
    echo "   ⚠️  $ERROR_COUNT errors found"
    echo ""
    echo "   Sample errors:"
    gcloud logging read \
      "resource.labels.service_name=nba-processors
       AND severity=ERROR
       AND timestamp>=\`date -u -d '30 minutes ago' --iso-8601=seconds\`" \
      --limit=3 \
      --format="table(timestamp,textPayload)" 2>/dev/null
  fi
else
  echo "   ❌ Could not check errors"
fi
echo ""

# 8. Check DLQ
echo "8️⃣ Dead Letter Queue Status:"
DLQ_COUNT=$(gcloud pubsub subscriptions describe nba-scraper-complete-dlq-sub \
  --format='value(numUndeliveredMessages)' 2>/dev/null)
if [ $? -eq 0 ]; then
  if [ "$DLQ_COUNT" -eq 0 ]; then
    echo "   ✅ DLQ: $DLQ_COUNT messages (healthy)"
  else
    echo "   ⚠️  DLQ: $DLQ_COUNT messages (investigate)"
  fi
else
  echo "   ❌ Could not check DLQ"
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Status check complete"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
