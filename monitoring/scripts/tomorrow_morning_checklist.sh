#!/bin/bash
# tomorrow_morning_checklist.sh - Simple monitoring checklist for tomorrow

echo "☀️  TOMORROW MORNING CHECKLIST (After 8:15 AM PT)"
echo "================================================="
echo "Run these commands to check your automated scrapers:"
echo ""

echo "1️⃣  CHECK IF JOBS RAN:"
echo "gcloud scheduler jobs list --location=us-west2 --format='table(name,lastAttemptTime,state)'"
echo ""

echo "2️⃣  CHECK JOB SUCCESS/FAILURE:"
echo "gcloud logging read 'resource.type=cloud_scheduler_job' --limit=5 --format='table(timestamp,resource.labels.job_id,severity,textPayload)'"
echo ""

echo "3️⃣  CHECK SERVICE HEALTH:"
echo "curl https://nba-scrapers-756957797294.us-west2.run.app/health | jq '.status'"
echo ""

echo "4️⃣  CHECK DATA FILES CREATED:"
echo "gsutil ls gs://nba-analytics-raw-data/\$(date '+%Y/%m/%d')/"
echo ""

echo "5️⃣  MANUAL TEST (if needed):"
echo "curl -X POST 'https://nba-scrapers-756957797294.us-west2.run.app/scrape?scraper=nbac_player_list' | jq '.status'"
echo ""

echo "6️⃣  CHECK BDL ERROR DETAILS (learning):"
echo "gcloud logging read 'resource.type=cloud_run_revision AND resource.labels.service_name=nba-scrapers AND severity>=ERROR' --limit=3"
echo ""

echo "📱 OR RUN THE FULL DASHBOARD:"
echo "./monitoring_dashboard.sh"
echo ""

echo "⏰ SCHEDULE REMINDER:"
echo "  8:00 AM PT: NBA Player List"
echo "  8:05 AM PT: BDL Active Players (will fail - learning opportunity)"
echo "  8:10 AM PT: GSW Roster"
echo ""

echo "🎯 SUCCESS CRITERIA:"
echo "  ✅ 2/3 scrapers successful (player list + GSW roster)"
echo "  ⚠️  BDL fails with 401 error (expected)"
echo "  ✅ Data files appear in GCS bucket"
