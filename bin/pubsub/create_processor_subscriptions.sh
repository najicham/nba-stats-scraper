#!/bin/bash
# create_processor_subscriptions.sh
#
# File Path: bin/pubsub/create_processor_subscriptions.sh
#
# Purpose: Create Pub/Sub push subscriptions for Phase 2 processors
#
# Architecture: 3 consolidated Cloud Run services (not 21 individual services)
# - nba-processors: Raw processing (Phase 2)
# - nba-analytics-processors: Analytics (Phase 3)
# - nba-reference-processors: Reference data
#
# Each service receives ALL events and routes internally based on scraper_name.
# This is more cost-efficient than 21 separate services.
#
# Usage: ./bin/pubsub/create_processor_subscriptions.sh

set -e  # Exit on error

PROJECT_ID="nba-props-platform"
REGION="us-west2"
TOPIC="nba-scraper-complete"
DLQ_TOPIC="nba-scraper-complete-dlq"

echo "🔗 Creating Pub/Sub Processor Subscriptions"
echo "==========================================="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Topic: $TOPIC"
echo ""

# Get processor service URL
echo "📋 Phase 1: Discovering processor service..."
PROCESSOR_URL=$(gcloud run services describe nba-processors \
  --region=$REGION \
  --format="value(status.url)" 2>/dev/null)

if [ -z "$PROCESSOR_URL" ]; then
  echo "❌ Error: nba-processors service not found!"
  echo ""
  echo "Please deploy processors first:"
  echo "  ./bin/processors/deploy/deploy_processors_simple.sh"
  exit 1
fi

echo "✅ Processor service URL: $PROCESSOR_URL"

# Get service account
PROCESSOR_SA=$(gcloud run services describe nba-processors \
  --region=$REGION \
  --format="value(spec.template.spec.serviceAccountName)" 2>/dev/null || echo "")

if [ -z "$PROCESSOR_SA" ]; then
  PROCESSOR_SA="756957797294-compute@developer.gserviceaccount.com"
  echo "⚠️  Using default service account: $PROCESSOR_SA"
else
  echo "✅ Service account: $PROCESSOR_SA"
fi

echo ""

# Create main processor subscription (receives ALL scraper events)
echo "📋 Phase 2: Creating main processor subscription..."

SUB_NAME="nba-processors-sub"

if gcloud pubsub subscriptions describe $SUB_NAME --project=$PROJECT_ID &>/dev/null; then
  echo "⚠️  Subscription '$SUB_NAME' already exists"
  echo "    To recreate:"
  echo "    gcloud pubsub subscriptions delete $SUB_NAME --project=$PROJECT_ID"
  echo "    Then run this script again"
else
  echo "  Creating subscription: $SUB_NAME"
  echo "  Endpoint: $PROCESSOR_URL/process"
  echo "  Ack deadline: 600s (10 minutes)"
  echo "  Max delivery attempts: 5"
  echo "  DLQ: $DLQ_TOPIC"
  echo ""
  
  gcloud pubsub subscriptions create $SUB_NAME \
    --topic=$TOPIC \
    --ack-deadline=600 \
    --message-retention-duration=1h \
    --dead-letter-topic=$DLQ_TOPIC \
    --max-delivery-attempts=5 \
    --push-endpoint="$PROCESSOR_URL/process" \
    --push-auth-service-account=$PROCESSOR_SA \
    --project=$PROJECT_ID
  
  echo "✅ Created subscription: $SUB_NAME"
fi

echo ""

# Optional: Create filtered subscriptions for specific scraper groups
# Uncomment if you want to route specific scrapers differently

# echo "📋 Phase 3: Creating filtered subscriptions (optional)..."
# 
# # Example: Morning operations only
# if ! gcloud pubsub subscriptions describe nba-processors-morning-sub --project=$PROJECT_ID &>/dev/null; then
#   gcloud pubsub subscriptions create nba-processors-morning-sub \
#     --topic=$TOPIC \
#     --ack-deadline=600 \
#     --push-endpoint="$PROCESSOR_URL/process" \
#     --push-auth-service-account=$PROCESSOR_SA \
#     --message-filter='attributes.workflow="morning_operations"' \
#     --project=$PROJECT_ID
#   echo "✅ Created filtered subscription: nba-processors-morning-sub"
# fi

# Grant service account permission to invoke Cloud Run
echo "📋 Phase 3: Granting Cloud Run Invoker permission..."
gcloud run services add-iam-policy-binding nba-processors \
  --member="serviceAccount:$PROCESSOR_SA" \
  --role="roles/run.invoker" \
  --region=$REGION \
  --project=$PROJECT_ID \
  &>/dev/null
echo "✅ Service account can invoke Cloud Run processor"

# Summary
echo ""
echo "✅ Processor Subscriptions Setup Complete!"
echo "=========================================="
echo ""
echo "Created Subscriptions:"
echo "  • $SUB_NAME → $PROCESSOR_URL/process"
echo ""
echo "Configuration:"
echo "  • Ack deadline: 600 seconds (10 minutes)"
echo "  • Max delivery attempts: 3"
echo "  • DLQ: $DLQ_TOPIC"
echo "  • Filter: None (receives ALL scraper events)"
echo ""
echo "Next Steps:"
echo "  1. Deploy scrapers with Pub/Sub code: ./bin/scrapers/deploy/deploy_scrapers_simple.sh"
echo "  2. Test end-to-end flow: ./bin/pubsub/test_pubsub_flow.sh"
echo "  3. Monitor subscriptions: ./bin/pubsub/monitor_pubsub.sh"
echo ""
echo "Monitoring Commands:"
echo "  # Check subscription status"
echo "  gcloud pubsub subscriptions describe $SUB_NAME --project=$PROJECT_ID"
echo ""
echo "  # Check for undelivered messages (backlog)"
echo "  gcloud pubsub subscriptions describe $SUB_NAME \\"
echo "    --format='value(numUndeliveredMessages)' --project=$PROJECT_ID"
echo ""
echo "  # Pull messages manually (for testing)"
echo "  gcloud pubsub subscriptions pull $SUB_NAME --limit=1 --project=$PROJECT_ID"
echo ""
echo "Troubleshooting:"
echo "  # If processors not receiving events, check:"
echo "  1. Pub/Sub topic exists: gcloud pubsub topics list"
echo "  2. Subscription exists: gcloud pubsub subscriptions list"
echo "  3. Cloud Run service is healthy: curl \$PROCESSOR_URL/health"
echo "  4. Check DLQ for failed deliveries:"
echo "     gcloud pubsub subscriptions pull nba-scraper-complete-dlq-sub --limit=10"
echo ""
