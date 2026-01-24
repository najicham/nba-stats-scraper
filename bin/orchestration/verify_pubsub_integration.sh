#!/bin/bash
set -euo pipefail
# Verify Pub/Sub Integration - Simple Check

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔍 Pub/Sub Integration Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 1. Check infrastructure
echo "1️⃣ Infrastructure Status:"
echo ""
echo "   Topics:"
gcloud pubsub topics list --filter="name:scraper-complete" --format="value(name)"
echo ""
echo "   Subscriptions:"
gcloud pubsub subscriptions list --filter="topic:scraper-complete" --format="value(name,state)"
echo ""

# 2. Check recent scraper activity
echo "2️⃣ Recent Scraper Activity (Last Hour):"
bq query --use_legacy_sql=false --format=pretty "
SELECT 
  triggered_at,
  scraper_name,
  status,
  SUBSTR(gcs_output_path, 1, 80) as gcs_file
FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
WHERE triggered_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
ORDER BY triggered_at DESC
LIMIT 10
"
echo ""

# 3. Check Pub/Sub publishing
echo "3️⃣ Pub/Sub Events Published (Last Hour):"
TIMESTAMP=$(date -u -d '1 hour ago' '+%Y-%m-%dT%H:%M:%SZ')
EVENTS=$(gcloud logging read \
  "resource.labels.service_name=nba-scrapers
   AND textPayload:\"Published scraper-complete event\"
   AND timestamp>=\"${TIMESTAMP}\"" \
  --limit=10 \
  --format=json 2>/dev/null)

EVENT_COUNT=$(echo "$EVENTS" | jq -s 'length')
echo "   Events published: $EVENT_COUNT"

if [ "$EVENT_COUNT" -gt 0 ]; then
  echo ""
  echo "   Recent events:"
  echo "$EVENTS" | jq -r '.[] | "   - " + (.timestamp) + " | " + (.textPayload | split("scraper_name=")[1] | split(",")[0])'
fi
echo ""

# 4. Check processor receipts
echo "4️⃣ Processor Activity (Last Hour):"
TIMESTAMP=$(date -u -d '1 hour ago' '+%Y-%m-%dT%H:%M:%SZ')
PROCESSED=$(gcloud logging read \
  "resource.labels.service_name=nba-processors
   AND timestamp>=\"${TIMESTAMP}\"" \
  --limit=10 \
  --format=json 2>/dev/null)

PROC_COUNT=$(echo "$PROCESSED" | jq -s 'length')
echo "   Processor log entries: $PROC_COUNT"

if [ "$PROC_COUNT" -gt 0 ]; then
  echo ""
  echo "   Recent activity:"
  echo "$PROCESSED" | jq -r '.[] | select(.textPayload != null) | "   - " + (.timestamp) + " | " + (.textPayload | tostring | .[0:80])'
fi
echo ""

# 5. Check for successful processing
echo "5️⃣ Successfully Processed Files (Last Hour):"
SUCCESS=$(gcloud logging read \
  "resource.labels.service_name=nba-processors
   AND textPayload:\"Successfully processed\"
   AND timestamp>=\"${TIMESTAMP}\"" \
  --limit=5 \
  --format=json 2>/dev/null)

SUCCESS_COUNT=$(echo "$SUCCESS" | jq -s 'length')
echo "   Successful processing: $SUCCESS_COUNT files"

if [ "$SUCCESS_COUNT" -gt 0 ]; then
  echo ""
  echo "   Details:"
  echo "$SUCCESS" | jq -r '.[] | "   - " + (.timestamp) + " | " + .textPayload'
fi
echo ""

# 6. Check for errors
echo "6️⃣ Processor Errors (Last Hour):"
ERRORS=$(gcloud logging read \
  "resource.labels.service_name=nba-processors
   AND severity=ERROR
   AND timestamp>=\"${TIMESTAMP}\"" \
  --limit=5 \
  --format=json 2>/dev/null)

ERROR_COUNT=$(echo "$ERRORS" | jq -s 'length')
echo "   Errors: $ERROR_COUNT"

if [ "$ERROR_COUNT" -gt 0 ]; then
  echo ""
  echo "   Error details:"
  echo "$ERRORS" | jq -r '.[] | "   - " + (.timestamp) + " | " + (.textPayload // .jsonPayload.message // "Unknown error")'
fi
echo ""

# 7. Check BigQuery writes
echo "7️⃣ Recent BigQuery Writes (Last Hour):"
echo "   Checking sample tables for recent inserts..."
TABLES=("bdl_games" "bdl_player_boxscores" "nbac_schedule")

for table in "${TABLES[@]}"; do
  COUNT=$(bq query --use_legacy_sql=false --format=csv --max_rows=1 \
    "SELECT COUNT(*) as count
     FROM \`nba-props-platform.nba_raw.${table}\`
     WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)" 2>/dev/null | tail -1)
  
  if [ -n "$COUNT" ] && [ "$COUNT" != "count" ]; then
    echo "   - ${table}: ${COUNT} records"
  fi
done
echo ""

# 8. Summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Integration Summary:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ "$EVENT_COUNT" -gt 0 ] && [ "$SUCCESS_COUNT" -gt 0 ]; then
  echo "   ✅ Integration is WORKING!"
  echo "   - Events published: $EVENT_COUNT"
  echo "   - Files processed: $SUCCESS_COUNT"
  echo ""
  echo "   The Pub/Sub pipeline is operational:"
  echo "   Scrapers → Pub/Sub → Processors → BigQuery ✓"
  echo ""
elif [ "$EVENT_COUNT" -gt 0 ] && [ "$SUCCESS_COUNT" -eq 0 ]; then
  echo "   ⚠️  Partial integration"
  echo "   - Events published: $EVENT_COUNT"
  echo "   - Files processed: $SUCCESS_COUNT"
  echo ""
  echo "   Events are being published but not processed."
  echo "   Check processor logs for issues."
  echo ""
elif [ "$EVENT_COUNT" -eq 0 ]; then
  echo "   ℹ️  No recent activity"
  echo "   - No scrapers have run in the last hour"
  echo "   - This is normal if no workflows are scheduled"
  echo ""
  echo "   To verify manually, trigger orchestration:"
  echo "   curl -X POST \$SERVICE_URL/evaluate -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\""
  echo ""
fi

if [ "$ERROR_COUNT" -gt 0 ]; then
  echo "   ⚠️  Errors detected: $ERROR_COUNT"
  echo "   Review error details above"
  echo ""
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
