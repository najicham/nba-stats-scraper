#!/bin/bash
# Cleanup Old NBA Platform Resources After Phase-Based Rename
#
# This script deletes old services, topics, and subscriptions after the
# phase-based naming migration is complete and verified.
#
# ONLY RUN THIS AFTER:
# 1. 24+ hours of monitoring new services
# 2. Verification that all traffic flows through new phase-based services
# 3. Confirmation that old services are no longer receiving traffic
#
# Created: 2025-11-16
# Author: Automated migration process

set -e  # Exit on error

PROJECT_ID="nba-props-platform"
REGION="us-west2"

echo "════════════════════════════════════════════════════════════════"
echo "  NBA Platform - Old Resource Cleanup"
echo "  WARNING: This will permanently delete old services and topics"
echo "════════════════════════════════════════════════════════════════"
echo ""

# Safety check
read -p "Have you verified new services are working for 24+ hours? (yes/no): " CONFIRM_MONITORING
if [ "$CONFIRM_MONITORING" != "yes" ]; then
    echo "❌ Aborted. Please monitor new services for at least 24 hours first."
    exit 1
fi

read -p "Are you SURE you want to delete old resources? (yes/no): " CONFIRM_DELETE
if [ "$CONFIRM_DELETE" != "yes" ]; then
    echo "❌ Aborted by user."
    exit 1
fi

echo ""
echo "═══ STEP 1: Deleting Old Cloud Run Services ═══"
echo ""

echo "Deleting nba-scrapers..."
gcloud run services delete nba-scrapers \
    --region=$REGION \
    --project=$PROJECT_ID \
    --quiet || echo "⚠️  Service may not exist"

echo "Deleting nba-processors..."
gcloud run services delete nba-processors \
    --region=$REGION \
    --project=$PROJECT_ID \
    --quiet || echo "⚠️  Service may not exist"

echo "Deleting nba-analytics-processors..."
gcloud run services delete nba-analytics-processors \
    --region=$REGION \
    --project=$PROJECT_ID \
    --quiet || echo "⚠️  Service may not exist"

echo ""
echo "═══ STEP 2: Review Dual Publishing Status ═══"
echo ""
echo "⚠️  MANUAL STEP REQUIRED:"
echo "    Before deleting old topics, ensure dual publishing has ended."
echo "    Check scrapers/utils/pubsub_utils.py for dual publishing code."
echo ""
read -p "Has dual publishing been disabled? (yes/no): " CONFIRM_DUAL_PUB
if [ "$CONFIRM_DUAL_PUB" != "yes" ]; then
    echo "❌ Skipping topic deletion. Disable dual publishing first."
    echo "✅ Old services deleted successfully."
    echo "⏸️  Re-run this script after disabling dual publishing to delete topics."
    exit 0
fi

echo ""
echo "═══ STEP 3: Deleting Old Subscriptions ═══"
echo ""

echo "Deleting nba-processors-sub..."
gcloud pubsub subscriptions delete nba-processors-sub \
    --project=$PROJECT_ID \
    --quiet || echo "⚠️  Subscription may not exist"

echo "Deleting nba-scraper-complete-dlq-sub..."
gcloud pubsub subscriptions delete nba-scraper-complete-dlq-sub \
    --project=$PROJECT_ID \
    --quiet || echo "⚠️  Subscription may not exist"

echo ""
echo "═══ STEP 4: Deleting Old Topics ═══"
echo ""

echo "Deleting nba-scraper-complete..."
gcloud pubsub topics delete nba-scraper-complete \
    --project=$PROJECT_ID \
    --quiet || echo "⚠️  Topic may not exist"

echo "Deleting nba-scraper-complete-dlq..."
gcloud pubsub topics delete nba-scraper-complete-dlq \
    --project=$PROJECT_ID \
    --quiet || echo "⚠️  Topic may not exist"

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  ✅ CLEANUP COMPLETE"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "Deleted resources:"
echo "  Services: nba-scrapers, nba-processors, nba-analytics-processors"
echo "  Subscriptions: nba-processors-sub, nba-scraper-complete-dlq-sub"
echo "  Topics: nba-scraper-complete, nba-scraper-complete-dlq"
echo ""
echo "Active resources (phase-based naming):"
echo "  Services: nba-phase1-scrapers, nba-phase2-raw-processors, nba-phase3-analytics-processors"
echo "  Topics: nba-phase1-scrapers-complete, nba-phase2-raw-complete"
echo "  Subscriptions: nba-phase2-raw-sub, nba-phase3-analytics-sub"
echo ""
echo "Next steps:"
echo "  1. Verify no errors in Cloud Run logs"
echo "  2. Check DLQ depths are still at 0"
echo "  3. Update documentation to reflect cleanup completion"
echo ""
