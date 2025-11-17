#!/bin/bash
# ==============================================================================
# Create All Fallback Trigger Topics
# ==============================================================================
#
# This script creates time-based fallback triggers for ALL phases.
# These act as safety nets if event-driven flow fails.
#
# Fallback triggers are named for the phase they TRIGGER:
#   - nba-phase2-fallback-trigger → triggers Phase 2 (if Phase 1 events fail)
#   - nba-phase3-fallback-trigger → triggers Phase 3 (if Phase 2 events fail)
#   - etc.
#
# These are published by Cloud Scheduler at specific times:
#   - Phase 2: 1:00 AM ET (after Phase 1 should have completed)
#   - Phase 3: 2:30 AM ET (after Phase 2 should have completed)
#   - Phase 4: 11:00 PM ET (after Phase 3 should have completed)
#   - Phase 5: 6:00 AM ET (after Phase 4 should have completed)
#   - Phase 6: 6:30 AM ET (after Phase 5 should have completed)
#
# Prerequisites:
#   - gcloud CLI authenticated
#   - Project: nba-props-platform
#
# Usage:
#   ./bin/infrastructure/create_all_fallback_triggers.sh
#
# Created: 2025-11-16
# ==============================================================================

set -euo pipefail

# Configuration
PROJECT_ID="nba-props-platform"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Create All Fallback Trigger Topics${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# ==============================================================================
# Create Fallback Trigger Topics
# ==============================================================================

create_fallback_topic() {
    local phase=$1
    local topic_name=$2
    local description=$3
    local trigger_time=$4

    echo -e "${YELLOW}Creating fallback trigger for Phase $phase...${NC}"
    echo "  Topic: $topic_name"
    echo "  Scheduled time: $trigger_time"
    echo "  Purpose: $description"

    if gcloud pubsub topics describe $topic_name --project=$PROJECT_ID &>/dev/null; then
        echo -e "${YELLOW}⚠️  Topic '$topic_name' already exists, skipping...${NC}"
    else
        gcloud pubsub topics create $topic_name \
            --project=$PROJECT_ID \
            --labels=phase=$phase,type=fallback-trigger,environment=production \
            --message-retention-duration=1d

        echo -e "${GREEN}✅ Created: $topic_name${NC}"
    fi
    echo ""
}

# Phase 2 Fallback (triggers Phase 2 if Phase 1 events fail)
create_fallback_topic \
    2 \
    "nba-phase2-fallback-trigger" \
    "Triggers Phase 2 raw processors if Phase 1 scraper events don't arrive" \
    "1:00 AM ET"

# Phase 3 Fallback (triggers Phase 3 if Phase 2 events fail)
create_fallback_topic \
    3 \
    "nba-phase3-fallback-trigger" \
    "Triggers Phase 3 analytics processors if Phase 2 raw data events don't arrive" \
    "2:30 AM ET"

# Phase 4 Fallback (triggers Phase 4 if Phase 3 events fail)
create_fallback_topic \
    4 \
    "nba-phase4-fallback-trigger" \
    "Triggers Phase 4 precompute processors if Phase 3 analytics events don't arrive" \
    "11:00 PM ET"

# Phase 5 Fallback (triggers Phase 5 if Phase 4 events fail)
create_fallback_topic \
    5 \
    "nba-phase5-fallback-trigger" \
    "Triggers Phase 5 prediction processors if Phase 4 precompute events don't arrive" \
    "6:00 AM ET"

# Phase 6 Fallback (triggers Phase 6 if Phase 5 events fail)
create_fallback_topic \
    6 \
    "nba-phase6-fallback-trigger" \
    "Triggers Phase 6 publishing service if Phase 5 prediction events don't arrive" \
    "6:30 AM ET"

# ==============================================================================
# Summary
# ==============================================================================
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${GREEN}✅ Fallback triggers created for all phases${NC}"
echo ""
echo "Next Steps:"
echo ""
echo "1. Create Cloud Scheduler jobs to publish to these topics:"
echo ""
echo "   # Phase 2 Fallback (1:00 AM ET daily)"
echo "   gcloud scheduler jobs create pubsub phase2-fallback-trigger \\"
echo "     --location=us-central1 \\"
echo "     --schedule='0 6 * * *' \\"  # 6 AM UTC = 1 AM ET
echo "     --time-zone='America/New_York' \\"
echo "     --topic=nba-phase2-fallback-trigger \\"
echo "     --message-body='{\"trigger_type\":\"fallback\",\"phase\":2,\"trigger_time\":\"1:00 AM ET\"}'"
echo ""
echo "   # Phase 3 Fallback (2:30 AM ET daily)"
echo "   gcloud scheduler jobs create pubsub phase3-fallback-trigger \\"
echo "     --location=us-central1 \\"
echo "     --schedule='0 7 * * *' \\"  # 7 AM UTC = 2 AM ET (approx)
echo "     --time-zone='America/New_York' \\"
echo "     --topic=nba-phase3-fallback-trigger \\"
echo "     --message-body='{\"trigger_type\":\"fallback\",\"phase\":3,\"trigger_time\":\"2:30 AM ET\"}'"
echo ""
echo "   # (Repeat for Phase 4, 5, 6...)"
echo ""
echo "2. Update processor services to subscribe to fallback triggers"
echo ""
echo "3. Configure processors to handle both event-driven and fallback triggers"
echo ""
echo -e "${GREEN}✅ All fallback triggers ready!${NC}"
