#!/bin/bash
# ==============================================================================
# Create Phase 2 → Phase 3 Pub/Sub Topics
# ==============================================================================
#
# This script creates all Pub/Sub topics and subscriptions needed for Phase 3
# deployment (Analytics processors).
#
# Topics Created:
#   - nba-phase2-raw-complete (main event topic)
#   - nba-phase2-raw-complete-dlq (dead letter queue)
#   - nba-phase3-fallback-trigger (time-based safety net)
#
# Prerequisites:
#   - gcloud CLI authenticated
#   - Project: nba-props-platform
#   - Permissions: pubsub.topics.create, pubsub.subscriptions.create
#
# Usage:
#   ./bin/infrastructure/create_phase2_phase3_topics.sh
#
# Created: 2025-11-16
# ==============================================================================

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Configuration
PROJECT_ID="nba-props-platform"
REGION="us-west2"
ANALYTICS_SERVICE_URL="https://nba-analytics-processors-f7p3g7f6ya-wl.a.run.app"
SERVICE_ACCOUNT="nba-pipeline@nba-props-platform.iam.gserviceaccount.com"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Phase 2 → Phase 3 Topic Creation${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# ==============================================================================
# Step 1: Create Main Topic (Phase 2 → Phase 3)
# ==============================================================================
echo -e "${YELLOW}Step 1: Creating main event topic...${NC}"

if gcloud pubsub topics describe nba-phase2-raw-complete --project=$PROJECT_ID &>/dev/null; then
    echo -e "${YELLOW}⚠️  Topic 'nba-phase2-raw-complete' already exists, skipping...${NC}"
else
    gcloud pubsub topics create nba-phase2-raw-complete \
        --project=$PROJECT_ID \
        --labels=phase=2,destination=phase3,environment=production,content=raw \
        --message-retention-duration=7d

    echo -e "${GREEN}✅ Created topic: nba-phase2-raw-complete${NC}"
fi

echo ""

# ==============================================================================
# Step 2: Create Dead Letter Queue Topic
# ==============================================================================
echo -e "${YELLOW}Step 2: Creating dead letter queue topic...${NC}"

if gcloud pubsub topics describe nba-phase2-raw-complete-dlq --project=$PROJECT_ID &>/dev/null; then
    echo -e "${YELLOW}⚠️  DLQ topic 'nba-phase2-raw-complete-dlq' already exists, skipping...${NC}"
else
    gcloud pubsub topics create nba-phase2-raw-complete-dlq \
        --project=$PROJECT_ID \
        --labels=phase=2,destination=phase3,type=dlq,environment=production \
        --message-retention-duration=7d

    echo -e "${GREEN}✅ Created DLQ topic: nba-phase2-raw-complete-dlq${NC}"
fi

echo ""

# ==============================================================================
# Step 3: Create Fallback Trigger Topics (Time-based safety nets)
# ==============================================================================
echo -e "${YELLOW}Step 3: Creating fallback trigger topics...${NC}"

# Phase 2 Fallback (triggers Phase 2 if Phase 1 fails)
if gcloud pubsub topics describe nba-phase2-fallback-trigger --project=$PROJECT_ID &>/dev/null; then
    echo -e "${YELLOW}⚠️  Fallback topic 'nba-phase2-fallback-trigger' already exists, skipping...${NC}"
else
    gcloud pubsub topics create nba-phase2-fallback-trigger \
        --project=$PROJECT_ID \
        --labels=phase=2,type=fallback-trigger,environment=production \
        --message-retention-duration=1d

    echo -e "${GREEN}✅ Created fallback topic: nba-phase2-fallback-trigger${NC}"
fi

# Phase 3 Fallback (triggers Phase 3 if Phase 2 fails)
if gcloud pubsub topics describe nba-phase3-fallback-trigger --project=$PROJECT_ID &>/dev/null; then
    echo -e "${YELLOW}⚠️  Fallback topic 'nba-phase3-fallback-trigger' already exists, skipping...${NC}"
else
    gcloud pubsub topics create nba-phase3-fallback-trigger \
        --project=$PROJECT_ID \
        --labels=phase=3,type=fallback-trigger,environment=production \
        --message-retention-duration=1d

    echo -e "${GREEN}✅ Created fallback topic: nba-phase3-fallback-trigger${NC}"
fi

echo ""

# ==============================================================================
# Step 4: Create Main Subscription (Event-Driven)
# ==============================================================================
echo -e "${YELLOW}Step 4: Creating main subscription (event-driven)...${NC}"

if gcloud pubsub subscriptions describe nba-phase3-analytics-sub --project=$PROJECT_ID &>/dev/null; then
    echo -e "${YELLOW}⚠️  Subscription 'nba-phase3-analytics-sub' already exists, skipping...${NC}"
else
    gcloud pubsub subscriptions create nba-phase3-analytics-sub \
        --project=$PROJECT_ID \
        --topic=nba-phase2-raw-complete \
        --push-endpoint="${ANALYTICS_SERVICE_URL}/process" \
        --ack-deadline=600 \
        --message-retention-duration=7d \
        --dead-letter-topic=nba-phase2-raw-complete-dlq \
        --max-delivery-attempts=5 \
        --labels=phase=3,type=event-driven,environment=production

    echo -e "${GREEN}✅ Created subscription: nba-phase3-analytics-sub${NC}"
fi

echo ""

# ==============================================================================
# Step 5: Create DLQ Subscription (for monitoring failed messages)
# ==============================================================================
echo -e "${YELLOW}Step 5: Creating DLQ subscription (for monitoring)...${NC}"

if gcloud pubsub subscriptions describe nba-phase2-raw-complete-dlq-sub --project=$PROJECT_ID &>/dev/null; then
    echo -e "${YELLOW}⚠️  DLQ subscription already exists, skipping...${NC}"
else
    gcloud pubsub subscriptions create nba-phase2-raw-complete-dlq-sub \
        --project=$PROJECT_ID \
        --topic=nba-phase2-raw-complete-dlq \
        --ack-deadline=600 \
        --message-retention-duration=7d \
        --labels=phase=2,type=dlq-monitoring,environment=production

    echo -e "${GREEN}✅ Created DLQ subscription: nba-phase2-raw-complete-dlq-sub${NC}"
fi

echo ""

# ==============================================================================
# Step 6: Create Fallback Subscription (Time-based)
# ==============================================================================
echo -e "${YELLOW}Step 6: Creating fallback subscription (time-based)...${NC}"

if gcloud pubsub subscriptions describe nba-phase3-fallback-sub --project=$PROJECT_ID &>/dev/null; then
    echo -e "${YELLOW}⚠️  Fallback subscription already exists, skipping...${NC}"
else
    gcloud pubsub subscriptions create nba-phase3-fallback-sub \
        --project=$PROJECT_ID \
        --topic=nba-phase3-fallback-trigger \
        --push-endpoint="${ANALYTICS_SERVICE_URL}/process" \
        --ack-deadline=600 \
        --message-retention-duration=1d \
        --labels=phase=3,type=fallback,environment=production

    echo -e "${GREEN}✅ Created fallback subscription: nba-phase3-fallback-sub${NC}"
fi

echo ""

# ==============================================================================
# Summary
# ==============================================================================
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${GREEN}✅ Topics created:${NC}"
echo "   - nba-phase2-raw-complete"
echo "   - nba-phase2-raw-complete-dlq"
echo "   - nba-phase2-fallback-trigger (triggers Phase 2)"
echo "   - nba-phase3-fallback-trigger (triggers Phase 3)"
echo ""
echo -e "${GREEN}✅ Subscriptions created:${NC}"
echo "   - nba-phase3-analytics-sub (push to analytics service)"
echo "   - nba-phase2-raw-complete-dlq-sub (pull, for monitoring)"
echo "   - nba-phase3-fallback-sub (time-based trigger)"
echo ""
echo -e "${BLUE}Next Steps:${NC}"
echo "1. Update Phase 2 processors to publish to nba-phase2-raw-complete"
echo "2. Test with mock message:"
echo "   gcloud pubsub topics publish nba-phase2-raw-complete \\"
echo "     --message='{\"event_type\":\"raw_data_loaded\",\"source_table\":\"test\",\"game_date\":\"2024-11-14\"}'"
echo "3. Monitor DLQ for failures:"
echo "   gcloud pubsub subscriptions pull nba-phase2-raw-complete-dlq-sub --limit=10"
echo ""
echo -e "${GREEN}✅ Phase 2→3 infrastructure ready!${NC}"
