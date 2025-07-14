#!/bin/bash
set -e

SERVICE_URL=$(gcloud run services describe nba-scrapers --region us-west2 --format 'value(status.url)')
echo "🧪 Testing NBA Scrapers at: $SERVICE_URL"

echo "1️⃣ Health check..."
curl -s "$SERVICE_URL/health" | jq .

echo -e "\n2️⃣ Available scrapers..."
SCRAPER_COUNT=$(curl -s "$SERVICE_URL/scrapers" | jq '.count')
echo "📊 Found $SCRAPER_COUNT available scrapers"

echo -e "\n3️⃣ Testing odds historical events scraper..."
curl -X POST "$SERVICE_URL/scrape" \
  -H "Content-Type: application/json" \
  -d '{
    "scraper": "oddsa_events_his",
    "sport": "basketball_nba",
    "date": "2025-07-13T00:00:00Z",
    "group": "prod"
  }' | jq .

echo -e "\n4️⃣ Recent GCS files..."
gcloud storage ls gs://nba-analytics-raw-data/oddsapi/historical-events/ | tail -3 || echo "No files yet (normal for empty snapshots)"

echo -e "\n✅ All tests complete!"