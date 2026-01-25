#!/bin/bash
#
# Setup Dead Letter Queues for Critical Pub/Sub Topics
#
# Creates DLQ topics and updates subscriptions to use them for all critical
# pipeline topics that don't already have DLQs configured.
#
# Based on FINAL-COMPREHENSIVE-HANDOFF.md lines 269-279:
# - phase-transitions (Critical) - Phase 5 predictions complete
# - processor-completions (Critical) - Grading trigger
# - prediction-requests (High) - Already has DLQ (prediction-request-dlq)
# - grading-requests (High) - Grading complete
# - backfill-requests (Medium) - Auto-retry trigger
#
# Usage:
#   ./bin/orchestrators/setup_dead_letter_queues.sh
#
# Created: 2026-01-25
# Part of: Pipeline Resilience Improvements
# Reference: FINAL-COMPREHENSIVE-HANDOFF.md P1.7

set -e

PROJECT_ID="nba-props-platform"
REGION="us-west2"
MAX_DELIVERY_ATTEMPTS=5

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Dead Letter Queue Setup${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Verify gcloud is authenticated
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" &>/dev/null; then
    echo -e "${RED}ERROR: gcloud is not authenticated${NC}"
    echo "Please run: gcloud auth login"
    exit 1
fi

# Verify project exists
if ! gcloud projects describe "$PROJECT_ID" &>/dev/null; then
    echo -e "${RED}ERROR: Project ${PROJECT_ID} not found${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Authenticated and project verified${NC}"
echo ""

# Function to create DLQ topic and subscription
create_dlq() {
    local main_topic=$1
    local dlq_topic="${main_topic}-dlq"
    local dlq_sub="${main_topic}-dlq-monitor"
    local priority=$2
    local description=$3

    echo -e "${BLUE}[$priority] Processing: ${main_topic}${NC}"
    echo -e "  Description: ${description}"

    # Step 1: Create DLQ topic if it doesn't exist
    if gcloud pubsub topics describe "$dlq_topic" --project=$PROJECT_ID &>/dev/null; then
        echo -e "${YELLOW}  ⚠️  DLQ topic already exists: ${dlq_topic}${NC}"
    else
        echo -e "  Creating DLQ topic: ${dlq_topic}..."
        gcloud pubsub topics create "$dlq_topic" \
            --project=$PROJECT_ID \
            --labels=type=dlq,priority=$priority,environment=production \
            --message-retention-duration=7d
        echo -e "${GREEN}  ✓ Created DLQ topic${NC}"
    fi

    # Step 2: Create DLQ monitoring subscription if it doesn't exist
    if gcloud pubsub subscriptions describe "$dlq_sub" --project=$PROJECT_ID &>/dev/null; then
        echo -e "${YELLOW}  ⚠️  DLQ subscription already exists: ${dlq_sub}${NC}"
    else
        echo -e "  Creating DLQ monitoring subscription: ${dlq_sub}..."
        gcloud pubsub subscriptions create "$dlq_sub" \
            --project=$PROJECT_ID \
            --topic="$dlq_topic" \
            --ack-deadline=600 \
            --message-retention-duration=7d \
            --labels=type=dlq-monitoring,priority=$priority,environment=production
        echo -e "${GREEN}  ✓ Created DLQ monitoring subscription${NC}"
    fi

    # Step 3: Find and update main subscription(s) to use DLQ
    echo -e "  Finding subscriptions for topic: ${main_topic}..."

    # Get all subscriptions for this topic
    local subscriptions=$(gcloud pubsub topics list-subscriptions "$main_topic" \
        --project=$PROJECT_ID \
        --format="value(name)" 2>/dev/null | grep -v "dlq" || true)

    if [ -z "$subscriptions" ]; then
        echo -e "${YELLOW}  ⚠️  No subscriptions found for ${main_topic}${NC}"
        echo -e "${YELLOW}     Manual action needed: Create subscription with DLQ when ready${NC}"
    else
        for sub in $subscriptions; do
            sub_name=$(basename "$sub")

            # Check if subscription already has a DLQ configured
            local current_dlq=$(gcloud pubsub subscriptions describe "$sub_name" \
                --project=$PROJECT_ID \
                --format="value(deadLetterPolicy.deadLetterTopic)" 2>/dev/null || true)

            if [ -n "$current_dlq" ]; then
                echo -e "${YELLOW}  ⚠️  Subscription ${sub_name} already has DLQ: ${current_dlq}${NC}"
            else
                echo -e "  Updating subscription ${sub_name} to use DLQ..."
                gcloud pubsub subscriptions update "$sub_name" \
                    --project=$PROJECT_ID \
                    --dead-letter-topic="$dlq_topic" \
                    --max-delivery-attempts=$MAX_DELIVERY_ATTEMPTS
                echo -e "${GREEN}  ✓ Updated subscription ${sub_name}${NC}"
            fi
        done
    fi

    echo ""
}

# ==============================================================================
# Critical Topics (Priority: Critical)
# ==============================================================================
echo -e "${RED}=== CRITICAL PRIORITY ===${NC}"
echo ""

# Phase 5 predictions complete - Critical for grading pipeline
create_dlq "nba-phase5-predictions-complete" \
    "critical" \
    "Phase 5 completion messages - triggers grading"

# Phase 6 grading trigger - Critical for model evaluation
create_dlq "nba-grading-trigger" \
    "critical" \
    "Grading trigger messages - triggers prediction accuracy evaluation"

# ==============================================================================
# High Priority Topics
# ==============================================================================
echo -e "${YELLOW}=== HIGH PRIORITY ===${NC}"
echo ""

# Grading completion - High priority for tracking
create_dlq "nba-grading-complete" \
    "high" \
    "Grading completion messages - final phase tracking"

# Phase 6 export completion - High priority for data exports
create_dlq "nba-phase6-export-complete" \
    "high" \
    "Phase 6 export completion messages - data export tracking"

# ==============================================================================
# Medium Priority Topics
# ==============================================================================
echo -e "${BLUE}=== MEDIUM PRIORITY ===${NC}"
echo ""

# Auto-retry trigger - Medium priority for retry orchestration
create_dlq "auto-retry-trigger" \
    "medium" \
    "Auto-retry trigger messages - backfill and retry requests"

# Phase 4 processor complete (if exists)
if gcloud pubsub topics describe "nba-phase4-processor-complete" --project=$PROJECT_ID &>/dev/null; then
    create_dlq "nba-phase4-processor-complete" \
        "medium" \
        "Phase 4 individual processor completion tracking"
fi

# ==============================================================================
# Verification
# ==============================================================================
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Verification${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

echo "DLQ Topics Created:"
gcloud pubsub topics list --project=$PROJECT_ID \
    --filter="labels.type=dlq" \
    --format="table(name, labels.priority)" \
    2>/dev/null | grep -v "^NAME$" || echo "No DLQ topics found"

echo ""
echo "Subscriptions with DLQs:"
gcloud pubsub subscriptions list --project=$PROJECT_ID \
    --format="table(name, topic.basename(), deadLetterPolicy.deadLetterTopic.basename(), deadLetterPolicy.maxDeliveryAttempts)" \
    2>/dev/null | grep "dlq\|DeadLetter" || echo "No subscriptions with DLQs found"

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✅ Dead Letter Queue setup complete${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

echo -e "${YELLOW}Next Steps:${NC}"
echo "1. Monitor DLQs for failed messages:"
echo "   gcloud pubsub subscriptions pull nba-phase5-predictions-complete-dlq-monitor --limit=10"
echo ""
echo "2. Set up alerts for DLQ message accumulation:"
echo "   ./bin/monitoring/setup_memory_alerts.sh"
echo ""
echo "3. Create Cloud Function to process DLQ messages (future enhancement)"
echo ""
echo -e "${YELLOW}Manual Actions Needed:${NC}"
echo "• For any topics without subscriptions, create them with DLQ when ready"
echo "• Review and test DLQ behavior with intentional failures"
echo "• Document DLQ monitoring procedures for on-call"
echo ""
