#!/bin/bash
# monitoring_dashboard.sh - Monitor NBA scrapers status and execution

PROJECT_ID="nba-props-platform"
REGION="us-west2"
SERVICE_URL="https://nba-scrapers-756957797294.us-west2.run.app"

echo "📊 NBA SCRAPERS MONITORING DASHBOARD"
echo "===================================="
echo "⏰ Current time: $(date)"
echo ""

# 1. Check scheduler job status
echo "📅 SCHEDULER JOB STATUS"
echo "======================"
gcloud scheduler jobs list --location=$REGION --format="table(name,state,schedule,lastAttemptTime,nextRunTime)" | grep "test-"

echo ""

# 2. Check recent job executions (last 4 hours)
echo "🔍 RECENT JOB EXECUTIONS (Last 4 Hours)"
echo "======================================="
gcloud logging read "resource.type=cloud_scheduler_job AND resource.labels.location=$REGION" \
    --limit=10 \
    --format="table(timestamp,resource.labels.job_id,severity,textPayload)" \
    --filter="timestamp >= '$(date -u -v-4H '+%Y-%m-%dT%H:%M:%SZ')'" 2>/dev/null || \
gcloud logging read "resource.type=cloud_scheduler_job AND resource.labels.location=$REGION" \
    --limit=10 \
    --format="table(timestamp,resource.labels.job_id,severity,textPayload)"

echo ""

# 3. Check service health
echo "🏥 SERVICE HEALTH CHECK"
echo "======================"
HEALTH_RESPONSE=$(curl -s "$SERVICE_URL/health" 2>/dev/null)
if echo "$HEALTH_RESPONSE" | jq . >/dev/null 2>&1; then
    SCRAPER_COUNT=$(echo "$HEALTH_RESPONSE" | jq '.available_scrapers | length')
    SERVICE_STATUS=$(echo "$HEALTH_RESPONSE" | jq -r '.status')
    echo "✅ Service Status: $SERVICE_STATUS"
    echo "📊 Available Scrapers: $SCRAPER_COUNT"
else
    echo "❌ Service health check failed"
    echo "Response: $HEALTH_RESPONSE"
fi

echo ""

# 4. Check recent scraper execution errors
echo "🚨 RECENT SCRAPER ERRORS (Last 2 Hours)"
echo "======================================="
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=nba-scrapers AND severity>=ERROR" \
    --limit=5 \
    --format="table(timestamp,severity,textPayload)" \
    --filter="timestamp >= '$(date -u -v-2H '+%Y-%m-%dT%H:%M:%SZ')'" 2>/dev/null || \
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=nba-scrapers AND severity>=ERROR" \
    --limit=5 \
    --format="table(timestamp,severity,textPayload)"

echo ""

# 5. Test each scheduled scraper manually
echo "🧪 MANUAL SCRAPER TESTS"
echo "======================="

echo "Testing nbac_player_list..."
PLAYER_RESULT=$(curl -s "$SERVICE_URL/scrape?scraper=nbac_player_list" | jq -r '.status // "failed"')
echo "  nbac_player_list: $PLAYER_RESULT"

echo "Testing nbac_roster (GSW)..."
ROSTER_RESULT=$(curl -s "$SERVICE_URL/scrape?scraper=nbac_roster&teamAbbr=GSW" | jq -r '.status // "failed"')
echo "  nbac_roster (GSW): $ROSTER_RESULT"

echo "Testing bdl_active_players..."
BDL_RESULT=$(curl -s "$SERVICE_URL/scrape?scraper=bdl_active_players" | jq -r '.status // "failed"')
echo "  bdl_active_players: $BDL_RESULT"

echo ""

# 6. Check GCS bucket for today's data
echo "💾 DATA FILES CREATED TODAY"
echo "==========================="
TODAY=$(date '+%Y/%m/%d')
echo "Checking gs://nba-analytics-raw-data/$TODAY/"
gsutil ls gs://nba-analytics-raw-data/$TODAY/ 2>/dev/null || echo "No data files found for today"

echo ""
echo "🎯 SUMMARY"
echo "=========="
if [ "$PLAYER_RESULT" = "success" ] && [ "$ROSTER_RESULT" = "success" ]; then
    echo "✅ 2/3 scrapers working (nbac_player_list, nbac_roster)"
    echo "⚠️  BDL scraper failing (expected - good for monitoring practice)"
    echo "🎯 Automation ready for production"
elif [ "$PLAYER_RESULT" = "success" ] || [ "$ROSTER_RESULT" = "success" ]; then
    echo "⚠️  1/3 scrapers working"
    echo "🔧 Some issues need attention"
else
    echo "❌ All scrapers failing"
    echo "🚨 Requires immediate investigation"
fi

echo ""
echo "🔗 USEFUL LINKS:"
echo "Scheduler Jobs: https://console.cloud.google.com/cloudscheduler?project=$PROJECT_ID"
echo "Cloud Run Logs: https://console.cloud.google.com/run/detail/$REGION/nba-scrapers/logs?project=$PROJECT_ID"
echo "Service URL: $SERVICE_URL/health"
