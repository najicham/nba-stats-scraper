#!/bin/bash
#
# Setup Fallback Pub/Sub Subscriptions
#
# Creates push subscriptions for fallback trigger topics so auto-retry
# processor can trigger fallback processing paths.
#
# Usage:
#   ./bin/orchestrators/setup_fallback_subscriptions.sh
#
# Created: 2026-01-25
# Part of: Pipeline Resilience Improvements

set -e

PROJECT_ID="nba-props-platform"
SERVICE_ACCOUNT="756957797294-compute@developer.gserviceaccount.com"

echo "=========================================="
echo "Setting up Fallback Subscriptions"
echo "=========================================="
echo ""

# Phase 2 fallback
echo "Creating Phase 2 fallback subscription..."
gcloud pubsub subscriptions create nba-phase2-fallback-sub \
  --topic=nba-phase2-fallback-trigger \
  --push-endpoint=https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/process \
  --push-auth-service-account=$SERVICE_ACCOUNT \
  --ack-deadline=600 \
  --message-retention-duration=1d \
  --project=$PROJECT_ID \
  2>&1 | grep -v "already exists" || echo "  ✓ Phase 2 subscription exists"

# Phase 3 fallback
echo "Creating Phase 3 fallback subscription..."
gcloud pubsub subscriptions create nba-phase3-fallback-sub \
  --topic=nba-phase3-fallback-trigger \
  --push-endpoint=https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process \
  --push-auth-service-account=$SERVICE_ACCOUNT \
  --ack-deadline=600 \
  --message-retention-duration=1d \
  --project=$PROJECT_ID \
  2>&1 | grep -v "already exists" || echo "  ✓ Phase 3 subscription exists"

# Phase 4 fallback
echo "Creating Phase 4 fallback subscription..."
gcloud pubsub subscriptions create nba-phase4-fallback-sub \
  --topic=nba-phase4-fallback-trigger \
  --push-endpoint=https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process \
  --push-auth-service-account=$SERVICE_ACCOUNT \
  --ack-deadline=600 \
  --message-retention-duration=1d \
  --project=$PROJECT_ID \
  2>&1 | grep -v "already exists" || echo "  ✓ Phase 4 subscription exists"

# Phase 5 fallback
echo "Creating Phase 5 fallback subscription..."
gcloud pubsub subscriptions create nba-phase5-fallback-sub \
  --topic=nba-phase5-fallback-trigger \
  --push-endpoint=https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/predict \
  --push-auth-service-account=$SERVICE_ACCOUNT \
  --ack-deadline=600 \
  --message-retention-duration=1d \
  --project=$PROJECT_ID \
  2>&1 | grep -v "already exists" || echo "  ✓ Phase 5 subscription exists"

echo ""
echo "=========================================="
echo "✅ Fallback subscriptions setup complete"
echo "=========================================="
echo ""
echo "Verify subscriptions:"
echo "  gcloud pubsub subscriptions list | grep fallback"
