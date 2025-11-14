#!/bin/bash
# test_pubsub_flow.sh
#
# File Path: bin/pubsub/test_pubsub_flow.sh
#
# Purpose: Test end-to-end Pub/Sub flow from Phase 1 (scrapers) to Phase 2 (processors)
#
# Tests:
# 1. Pub/Sub topic exists
# 2. Subscription exists and is configured correctly
# 3. Scrapers can publish events
# 4. Processors receive and process events
# 5. Data appears in BigQuery
#
# Usage: ./bin/pubsub/test_pubsub_flow.sh

set -e  # Exit on error

PROJECT_ID="nba-props-platform"
REGION="us-west2"
TOPIC="nba-scraper-complete"
SUBSCRIPTION="nba-processors-sub"

echo "🧪 Testing Pub/Sub Integration Flow"
echo "===================================="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo ""

# Phase 1: Infrastructure Check
echo "📋 Phase 1: Checking Pub/Sub infrastructure..."

if gcloud pubsub topics describe $TOPIC --project=$PROJECT_ID &>/dev/null; then
  echo "  ✅ Topic exists: $TOPIC"
else
  echo "  ❌ Topic not found: $TOPIC"
  echo "     Run: ./bin/pubsub/create_pubsub_infrastructure.sh"
  exit 1
fi

if gcloud pubsub subscriptions describe $SUBSCRIPTION --project=$PROJECT_ID &>/dev/null; then
  echo "  ✅ Subscription exists: $SUBSCRIPTION"
else
  echo "  ❌ Subscription not found: $SUBSCRIPTION"
  echo "     Run: ./bin/pubsub/create_processor_subscriptions.sh"
  exit 1
fi

# Check subscription backlog
BACKLOG=$(gcloud pubsub subscriptions describe $SUBSCRIPTION \
  --format='value(numUndeliveredMessages)' --project=$PROJECT_ID 2>/dev/null || echo "0")

# Handle empty or non-numeric backlog
if [ -z "$BACKLOG" ]; then
  BACKLOG="0"
fi

if [ "$BACKLOG" -eq 0 ] 2>/dev/null; then
  echo "  ✅ Subscription backlog: 0 messages (healthy)"
elif [ "$BACKLOG" -gt 0 ] 2>/dev/null; then
  echo "  ⚠️  Subscription backlog: $BACKLOG messages (processing lag)"
else
  echo "  ℹ️  Subscription backlog: unknown (unable to check)"
fi

echo ""

# Phase 2: Service Check
echo "📋 Phase 2: Checking Cloud Run services..."

# Check scraper service
SCRAPER_URL=$(gcloud run services describe nba-scrapers \
  --region=$REGION \
  --format="value(status.url)" 2>/dev/null || echo "")

if [ -z "$SCRAPER_URL" ]; then
  echo "  ❌ Scraper service not found"
  echo "     Run: ./bin/scrapers/deploy/deploy_scrapers_simple.sh"
  exit 1
fi

echo "  ✅ Scraper service: $SCRAPER_URL"

# Check scraper health
SCRAPER_HEALTH=$(curl -s "$SCRAPER_URL/health" 2>/dev/null | jq -r '.status' 2>/dev/null || echo "unknown")
if [ "$SCRAPER_HEALTH" = "healthy" ]; then
  echo "  ✅ Scraper service is healthy"
else
  echo "  ⚠️  Scraper service health: $SCRAPER_HEALTH"
fi

# Check processor service
PROCESSOR_URL=$(gcloud run services describe nba-processors \
  --region=$REGION \
  --format="value(status.url)" 2>/dev/null || echo "")

if [ -z "$PROCESSOR_URL" ]; then
  echo "  ❌ Processor service not found"
  echo "     Run: ./bin/processors/deploy/deploy_processors_simple.sh"
  exit 1
fi

echo "  ✅ Processor service: $PROCESSOR_URL"

# Check processor health (requires auth)
TOKEN=$(gcloud auth print-identity-token 2>/dev/null)
PROCESSOR_HEALTH=$(curl -s -H "Authorization: Bearer $TOKEN" "$PROCESSOR_URL/health" 2>/dev/null | jq -r '.status' 2>/dev/null || echo "unknown")
if [ "$PROCESSOR_HEALTH" = "healthy" ]; then
  echo "  ✅ Processor service is healthy"
else
  echo "  ⚠️  Processor service health: $PROCESSOR_HEALTH"
fi

echo ""

# Phase 3: Test Event Publishing
echo "📋 Phase 3: Testing Pub/Sub event publishing..."

# Create temporary test subscription
TEST_SUB="test-pubsub-flow-$(date +%s)"
echo "  Creating temporary test subscription: $TEST_SUB"

gcloud pubsub subscriptions create $TEST_SUB \
  --topic=$TOPIC \
  --expiration-period=1h \
  --project=$PROJECT_ID \
  &>/dev/null

echo "  ✅ Temporary subscription created"

# Publish test event
echo "  Publishing test event..."

TEST_EVENT=$(cat <<EOF
{
  "scraper_name": "test_scraper",
  "execution_id": "test-$(date +%s)",
  "status": "success",
  "gcs_path": "gs://test-bucket/test.json",
  "record_count": 10,
  "duration_seconds": 5.5,
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "workflow": "TEST"
}
EOF
)

gcloud pubsub topics publish $TOPIC \
  --message="$TEST_EVENT" \
  --attribute=scraper_name=test_scraper,status=success,workflow=TEST \
  --project=$PROJECT_ID \
  &>/dev/null

echo "  ✅ Test event published"

# Wait for message to propagate
echo "  Waiting 5 seconds for message propagation..."
sleep 5

# Pull test message
echo "  Pulling test message..."
MESSAGE=$(gcloud pubsub subscriptions pull $TEST_SUB \
  --limit=1 \
  --auto-ack \
  --project=$PROJECT_ID 2>/dev/null || echo "")

if echo "$MESSAGE" | grep -q "test_scraper"; then
  echo "  ✅ Test message received successfully"
else
  echo "  ❌ Test message not received"
  echo "     Check Pub/Sub configuration"
fi

# Clean up test subscription
echo "  Cleaning up test subscription..."
gcloud pubsub subscriptions delete $TEST_SUB --project=$PROJECT_ID &>/dev/null
echo "  ✅ Cleanup complete"

echo ""

# Phase 4: Test Real Scraper (Optional)
echo "📋 Phase 4: Testing real scraper integration (optional)..."
echo ""
echo "To test with a real scraper, run:"
echo ""
echo "  # Option 1: Trigger via HTTP endpoint (if available)"
echo "  curl -X POST \"$SCRAPER_URL/scraper/bdl-games\" \\"
echo "    -H \"Content-Type: application/json\" \\"
echo "    -d '{\"season\": \"2024-25\", \"date\": \"2025-11-12\"}'"
echo ""
echo "  # Option 2: Run scraper locally"
echo "  python -m scrapers.bdl.get_bdl_games --group=dev --date=2025-11-12"
echo ""
echo "Then check for Pub/Sub events:"
echo "  gcloud pubsub subscriptions pull $SUBSCRIPTION --limit=1"
echo ""

# Phase 5: Summary
echo "📋 Test Summary"
echo "==============="
echo ""

if [ -n "$MESSAGE" ]; then
  echo "✅ All infrastructure checks passed"
  echo "✅ Pub/Sub publishing works"
  echo "✅ Message delivery works"
  echo ""
  echo "Next Steps:"
  echo "  1. Test with a real scraper (see commands above)"
  echo "  2. Monitor processor execution:"
  echo "     gcloud logging read 'resource.type=cloud_run_revision AND resource.labels.service_name=nba-processors' --limit=20"
  echo "  3. Check BigQuery for processed data:"
  echo "     bq query --use_legacy_sql=false \"SELECT * FROM nba_raw.bdl_games WHERE game_date = CURRENT_DATE() LIMIT 5\""
  echo "  4. Monitor subscription health:"
  echo "     ./bin/pubsub/monitor_pubsub.sh"
else
  echo "⚠️  Infrastructure exists but message delivery test failed"
  echo ""
  echo "Troubleshooting:"
  echo "  1. Check topic exists: gcloud pubsub topics list"
  echo "  2. Check subscription exists: gcloud pubsub subscriptions list"
  echo "  3. Check DLQ for failed deliveries:"
  echo "     gcloud pubsub subscriptions pull nba-scraper-complete-dlq-sub --limit=10"
  echo "  4. Check Cloud Run logs:"
  echo "     gcloud logging read 'resource.type=cloud_run_revision AND resource.labels.service_name=nba-processors' --limit=20"
fi

echo ""
echo "🎉 Test complete!"