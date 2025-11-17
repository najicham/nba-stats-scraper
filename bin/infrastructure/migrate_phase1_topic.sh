#!/bin/bash
# ==============================================================================
# Migrate Phase 1 Topic: nba-scraper-complete → nba-phase1-scrapers-complete
# ==============================================================================
#
# This script safely migrates the Phase 1 topic name for consistency with the
# new naming convention (nba-phase{N}-{content}-complete).
#
# Migration Strategy:
#   1. Create new topic (nba-phase1-scrapers-complete)
#   2. Create new DLQ topic
#   3. Create dual subscriptions (old and new topics)
#   4. Update Phase 1 scrapers to publish to BOTH topics (transition period)
#   5. Verify both topics receiving messages
#   6. Update Phase 2 to subscribe to new topic only
#   7. Disable old topic publishing after 24 hours
#   8. Delete old topic after 7 days (safety period)
#
# Prerequisites:
#   - gcloud CLI authenticated
#   - Project: nba-props-platform
#   - Phase 1 scrapers currently working
#
# Usage:
#   # Step 1: Create new infrastructure (safe, no changes to existing)
#   ./bin/infrastructure/migrate_phase1_topic.sh create
#
#   # Step 2: Verify dual publishing (after deploying updated scrapers)
#   ./bin/infrastructure/migrate_phase1_topic.sh verify
#
#   # Step 3: Complete migration (after 24hrs of dual publishing)
#   ./bin/infrastructure/migrate_phase1_topic.sh finalize
#
# Created: 2025-11-16
# ==============================================================================

set -euo pipefail

# Configuration
PROJECT_ID="nba-props-platform"
REGION="us-west2"
PROCESSORS_SERVICE_URL="https://nba-processors-f7p3g7f6ya-wl.a.run.app"
SERVICE_ACCOUNT="nba-pipeline@nba-props-platform.iam.gserviceaccount.com"

# Topic names
OLD_TOPIC="nba-scraper-complete"
OLD_DLQ="nba-scraper-complete-dlq"
NEW_TOPIC="nba-phase1-scrapers-complete"
NEW_DLQ="nba-phase1-scrapers-complete-dlq"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# ==============================================================================
# Helper Functions
# ==============================================================================

print_header() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
}

print_step() {
    echo -e "${YELLOW}$1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# ==============================================================================
# Step 1: Create New Infrastructure
# ==============================================================================

create_new_infrastructure() {
    print_header "Step 1: Create New Infrastructure"

    # Create new main topic
    print_step "Creating new topic: $NEW_TOPIC"
    if gcloud pubsub topics describe $NEW_TOPIC --project=$PROJECT_ID &>/dev/null; then
        print_warning "Topic '$NEW_TOPIC' already exists"
    else
        gcloud pubsub topics create $NEW_TOPIC \
            --project=$PROJECT_ID \
            --labels=phase=1,destination=phase2,environment=production,content=scrapers \
            --message-retention-duration=7d
        print_success "Created topic: $NEW_TOPIC"
    fi

    # Create new DLQ topic
    print_step "Creating new DLQ topic: $NEW_DLQ"
    if gcloud pubsub topics describe $NEW_DLQ --project=$PROJECT_ID &>/dev/null; then
        print_warning "DLQ topic '$NEW_DLQ' already exists"
    else
        gcloud pubsub topics create $NEW_DLQ \
            --project=$PROJECT_ID \
            --labels=phase=1,destination=phase2,type=dlq,environment=production \
            --message-retention-duration=7d
        print_success "Created DLQ topic: $NEW_DLQ"
    fi

    # Create new subscription (Phase 2 listens to new topic)
    print_step "Creating new subscription: nba-processors-sub-v2"
    if gcloud pubsub subscriptions describe nba-processors-sub-v2 --project=$PROJECT_ID &>/dev/null; then
        print_warning "Subscription 'nba-processors-sub-v2' already exists"
    else
        gcloud pubsub subscriptions create nba-processors-sub-v2 \
            --project=$PROJECT_ID \
            --topic=$NEW_TOPIC \
            --push-endpoint="${PROCESSORS_SERVICE_URL}/process" \
            --ack-deadline=600 \
            --message-retention-duration=7d \
            --dead-letter-topic=$NEW_DLQ \
            --max-delivery-attempts=5 \
            --labels=phase=2,type=event-driven,version=v2,environment=production
        print_success "Created subscription: nba-processors-sub-v2"
    fi

    # Create new DLQ subscription
    print_step "Creating new DLQ subscription: $NEW_DLQ-sub"
    if gcloud pubsub subscriptions describe ${NEW_DLQ}-sub --project=$PROJECT_ID &>/dev/null; then
        print_warning "DLQ subscription already exists"
    else
        gcloud pubsub subscriptions create ${NEW_DLQ}-sub \
            --project=$PROJECT_ID \
            --topic=$NEW_DLQ \
            --ack-deadline=600 \
            --message-retention-duration=7d \
            --labels=phase=1,type=dlq-monitoring,environment=production
        print_success "Created DLQ subscription: ${NEW_DLQ}-sub"
    fi

    print_header "Step 1 Complete"
    print_success "New infrastructure created successfully"
    echo ""
    echo -e "${BLUE}Next Steps:${NC}"
    echo "1. Update scrapers/utils/pubsub_utils.py to publish to BOTH topics:"
    echo "   - $OLD_TOPIC (existing)"
    echo "   - $NEW_TOPIC (new)"
    echo "2. Deploy updated scrapers"
    echo "3. Run: ./bin/infrastructure/migrate_phase1_topic.sh verify"
    echo ""
}

# ==============================================================================
# Step 2: Verify Dual Publishing
# ==============================================================================

verify_dual_publishing() {
    print_header "Step 2: Verify Dual Publishing"

    echo "Checking message counts in both topics..."
    echo ""

    # Check old topic
    print_step "Checking old topic: $OLD_TOPIC"
    OLD_COUNT=$(gcloud pubsub subscriptions describe nba-processors-sub --project=$PROJECT_ID --format="value(numUndeliveredMessages)" 2>/dev/null || echo "0")
    echo "  Undelivered messages: $OLD_COUNT"

    # Check new topic
    print_step "Checking new topic: $NEW_TOPIC"
    NEW_COUNT=$(gcloud pubsub subscriptions describe nba-processors-sub-v2 --project=$PROJECT_ID --format="value(numUndeliveredMessages)" 2>/dev/null || echo "0")
    echo "  Undelivered messages: $NEW_COUNT"

    echo ""

    # Pull sample message from each
    print_step "Pulling sample message from old topic..."
    gcloud pubsub subscriptions pull nba-processors-sub --project=$PROJECT_ID --limit=1 --auto-ack 2>/dev/null || echo "  No messages available"

    echo ""

    print_step "Pulling sample message from new topic..."
    gcloud pubsub subscriptions pull nba-processors-sub-v2 --project=$PROJECT_ID --limit=1 --auto-ack 2>/dev/null || echo "  No messages available"

    echo ""
    print_header "Verification Tips"
    echo "✓ Both topics should be receiving messages"
    echo "✓ Message format should be identical"
    echo "✓ Monitor for 24 hours before finalizing migration"
    echo ""
    echo "To finalize migration after 24 hours:"
    echo "  ./bin/infrastructure/migrate_phase1_topic.sh finalize"
    echo ""
}

# ==============================================================================
# Step 3: Finalize Migration
# ==============================================================================

finalize_migration() {
    print_header "Step 3: Finalize Migration"

    print_warning "This will:"
    echo "  1. Update Phase 2 to use new topic only"
    echo "  2. Mark old topic for deletion in 7 days"
    echo ""

    read -p "Have you verified dual publishing for 24+ hours? (yes/no): " confirm
    if [[ "$confirm" != "yes" ]]; then
        print_error "Migration cancelled. Verify dual publishing first."
        exit 1
    fi

    print_step "Step 3.1: Update scrapers to publish to new topic only"
    echo "  Manual step: Update scrapers/utils/pubsub_utils.py"
    echo "  Remove: $OLD_TOPIC"
    echo "  Keep only: $NEW_TOPIC"
    echo ""
    read -p "Have you updated and deployed scrapers? (yes/no): " scrapers_updated
    if [[ "$scrapers_updated" != "yes" ]]; then
        print_error "Please update scrapers first, then re-run finalize"
        exit 1
    fi

    print_step "Step 3.2: Delete old subscription (Phase 2 uses new one)"
    read -p "Delete old subscription 'nba-processors-sub'? (yes/no): " delete_old_sub
    if [[ "$delete_old_sub" == "yes" ]]; then
        gcloud pubsub subscriptions delete nba-processors-sub --project=$PROJECT_ID --quiet
        print_success "Deleted old subscription: nba-processors-sub"
    else
        print_warning "Keeping old subscription (will be deleted manually)"
    fi

    echo ""
    print_step "Step 3.3: Mark old topics for deletion"
    echo "  $OLD_TOPIC will be deleted in 7 days (safety period)"
    echo "  $OLD_DLQ will be deleted in 7 days"
    echo ""
    echo "  Schedule deletion with:"
    echo "    gcloud pubsub topics delete $OLD_TOPIC --project=$PROJECT_ID"
    echo "    gcloud pubsub topics delete $OLD_DLQ --project=$PROJECT_ID"
    echo ""

    print_header "Migration Complete"
    print_success "Phase 1 now using: $NEW_TOPIC"
    print_success "Phase 2 now listening to: $NEW_TOPIC"
    echo ""
    echo -e "${BLUE}Final cleanup (in 7 days):${NC}"
    echo "  gcloud pubsub topics delete $OLD_TOPIC --project=$PROJECT_ID"
    echo "  gcloud pubsub topics delete $OLD_DLQ --project=$PROJECT_ID"
    echo ""
}

# ==============================================================================
# Main Script
# ==============================================================================

print_header "Phase 1 Topic Migration Tool"

case "${1:-}" in
    create)
        create_new_infrastructure
        ;;
    verify)
        verify_dual_publishing
        ;;
    finalize)
        finalize_migration
        ;;
    *)
        echo "Usage: $0 {create|verify|finalize}"
        echo ""
        echo "Steps:"
        echo "  1. create   - Create new topic infrastructure (safe, no changes to existing)"
        echo "  2. verify   - Verify dual publishing is working"
        echo "  3. finalize - Complete migration (after 24hrs of verification)"
        echo ""
        echo "Example:"
        echo "  $0 create"
        exit 1
        ;;
esac
