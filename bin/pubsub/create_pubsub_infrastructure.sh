#!/bin/bash
# create_pubsub_infrastructure.sh
# 
# File Path: bin/pubsub/create_pubsub_infrastructure.sh
#
# Purpose: Create Pub/Sub infrastructure for Phase 1 → Phase 2 handoff
#
# Creates:
# - nba-scraper-complete topic (main event bus)
# - nba-scraper-complete-dlq topic (dead letter queue)
# - nba-phase2-complete topic (Phase 2 → Phase 3 handoff, future)
# - IAM permissions for Cloud Run services
#
# Usage: ./bin/pubsub/create_pubsub_infrastructure.sh

set -e  # Exit on error

PROJECT_ID="nba-props-platform"
REGION="us-west2"

echo "🏗️  Setting up Pub/Sub Infrastructure for NBA Props Platform"
echo "============================================================="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo ""

# Get Cloud Run service accounts
echo "📋 Phase 1: Discovering Cloud Run service accounts..."
SCRAPER_SA=$(gcloud run services describe nba-scrapers \
  --region=$REGION \
  --format="value(spec.template.spec.serviceAccountName)" 2>/dev/null || echo "")

PROCESSOR_SA=$(gcloud run services describe nba-processors \
  --region=$REGION \
  --format="value(spec.template.spec.serviceAccountName)" 2>/dev/null || echo "")

if [ -z "$SCRAPER_SA" ]; then
  # Use default compute service account
  SCRAPER_SA="756957797294-compute@developer.gserviceaccount.com"
  echo "⚠️  Using default compute service account for scrapers: $SCRAPER_SA"
else
  echo "✅ Scraper service account: $SCRAPER_SA"
fi

if [ -z "$PROCESSOR_SA" ]; then
  # Use default compute service account
  PROCESSOR_SA="756957797294-compute@developer.gserviceaccount.com"
  echo "⚠️  Using default compute service account for processors: $PROCESSOR_SA"
else
  echo "✅ Processor service account: $PROCESSOR_SA"
fi

echo ""

# Create main topic for scraper completions
echo "📋 Phase 2: Creating main Pub/Sub topic..."
if gcloud pubsub topics describe nba-scraper-complete --project=$PROJECT_ID &>/dev/null; then
  echo "⚠️  Topic 'nba-scraper-complete' already exists (skipping)"
else
  gcloud pubsub topics create nba-scraper-complete \
    --message-retention-duration=1d \
    --project=$PROJECT_ID
  echo "✅ Created topic: nba-scraper-complete"
fi

# Create DLQ topic for failed deliveries
echo ""
echo "📋 Phase 3: Creating dead letter queue topic..."
if gcloud pubsub topics describe nba-scraper-complete-dlq --project=$PROJECT_ID &>/dev/null; then
  echo "⚠️  Topic 'nba-scraper-complete-dlq' already exists (skipping)"
else
  gcloud pubsub topics create nba-scraper-complete-dlq \
    --message-retention-duration=7d \
    --project=$PROJECT_ID
  echo "✅ Created DLQ topic: nba-scraper-complete-dlq"
fi

# Create DLQ subscription
echo ""
echo "📋 Phase 4: Creating DLQ subscription..."
if gcloud pubsub subscriptions describe nba-scraper-complete-dlq-sub --project=$PROJECT_ID &>/dev/null; then
  echo "⚠️  Subscription 'nba-scraper-complete-dlq-sub' already exists (skipping)"
else
  gcloud pubsub subscriptions create nba-scraper-complete-dlq-sub \
    --topic=nba-scraper-complete-dlq \
    --ack-deadline=60 \
    --project=$PROJECT_ID
  echo "✅ Created DLQ subscription: nba-scraper-complete-dlq-sub"
fi

# Create Phase 2 → Phase 3 handoff topic (for future use)
echo ""
echo "📋 Phase 5: Creating Phase 2 → Phase 3 handoff topic..."
if gcloud pubsub topics describe nba-phase2-complete --project=$PROJECT_ID &>/dev/null; then
  echo "⚠️  Topic 'nba-phase2-complete' already exists (skipping)"
else
  gcloud pubsub topics create nba-phase2-complete \
    --message-retention-duration=1d \
    --project=$PROJECT_ID
  echo "✅ Created topic: nba-phase2-complete"
fi

# Grant IAM permissions
echo ""
echo "📋 Phase 6: Setting up IAM permissions..."

# Grant scraper service account permission to publish
echo "  Granting Pub/Sub Publisher role to scrapers..."
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SCRAPER_SA" \
  --role="roles/pubsub.publisher" \
  --condition=None \
  &>/dev/null
echo "  ✅ Scrapers can publish to Pub/Sub topics"

# Grant processor service account permission to subscribe and ack
echo "  Granting Pub/Sub Subscriber role to processors..."
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$PROCESSOR_SA" \
  --role="roles/pubsub.subscriber" \
  --condition=None \
  &>/dev/null
echo "  ✅ Processors can subscribe to Pub/Sub topics"

# Grant processor service account permission to publish to Phase 2 → 3 topic
echo "  Granting Pub/Sub Publisher role to processors (for Phase 3 handoff)..."
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$PROCESSOR_SA" \
  --role="roles/pubsub.publisher" \
  --condition=None \
  &>/dev/null
echo "  ✅ Processors can publish to Phase 3 handoff topic"

# Summary
echo ""
echo "✅ Pub/Sub Infrastructure Setup Complete!"
echo "=========================================="
echo ""
echo "Created Topics:"
echo "  • nba-scraper-complete (Phase 1 → 2 handoff)"
echo "  • nba-scraper-complete-dlq (Failed deliveries)"
echo "  • nba-phase2-complete (Phase 2 → 3 handoff, future)"
echo ""
echo "Created Subscriptions:"
echo "  • nba-scraper-complete-dlq-sub (Monitor failed deliveries)"
echo ""
echo "IAM Permissions:"
echo "  • Scrapers ($SCRAPER_SA) can PUBLISH"
echo "  • Processors ($PROCESSOR_SA) can SUBSCRIBE and PUBLISH"
echo ""
echo "Next Steps:"
echo "  1. Create processor subscriptions: ./bin/pubsub/create_processor_subscriptions.sh"
echo "  2. Deploy scrapers with Pub/Sub code: ./bin/scrapers/deploy/deploy_scrapers_simple.sh"
echo "  3. Test end-to-end flow: ./bin/pubsub/test_pubsub_flow.sh"
echo ""
echo "Monitoring:"
echo "  # List all topics"
echo "  gcloud pubsub topics list --project=$PROJECT_ID"
echo ""
echo "  # Check DLQ for failed deliveries"
echo "  gcloud pubsub subscriptions pull nba-scraper-complete-dlq-sub --limit=10"
echo ""
echo "  # Monitor topic activity"
echo "  gcloud pubsub topics describe nba-scraper-complete --project=$PROJECT_ID"
echo ""
