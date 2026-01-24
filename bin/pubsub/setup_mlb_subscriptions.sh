#!/bin/bash
# bin/pubsub/setup_mlb_subscriptions.sh
#
# Create Pub/Sub push subscriptions for MLB pipeline automation.
# This connects each phase to the next via push subscriptions.
#
# Flow:
#   Phase 1 (Scrapers) -> GCS -> Phase 2 (Raw Processors)
#   Phase 2 -> mlb-phase2-raw-complete -> Phase 3 (Analytics)
#   Phase 3 -> mlb-phase3-analytics-complete -> Phase 4 (Precompute)
#   Phase 4 -> mlb-phase4-precompute-complete -> Phase 5 (Predictions)
#   Phase 5 -> mlb-phase5-predictions-complete -> Phase 6 (Grading)
#
# Created: 2026-01-07

set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"
REGION="us-west2"

# Service URLs
PHASE3_URL="https://mlb-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app"
PHASE4_URL="https://mlb-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app"
PHASE5_URL="https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app"
PHASE6_URL="https://mlb-phase6-grading-f7p3g7f6ya-wl.a.run.app"

# Common subscription settings
ACK_DEADLINE=600
RETENTION="1h"
MAX_RETRIES=5

echo "=============================================="
echo "  MLB Pub/Sub Subscription Setup"
echo "=============================================="
echo "Project: $PROJECT_ID"
echo ""

create_subscription() {
    local SUB_NAME=$1
    local TOPIC=$2
    local ENDPOINT=$3
    local DLQ_TOPIC=$4

    echo -n "Creating $SUB_NAME... "

    # Check if exists
    if gcloud pubsub subscriptions describe "$SUB_NAME" --project="$PROJECT_ID" &>/dev/null; then
        echo "already exists"
        return 0
    fi

    # Build command
    CMD="gcloud pubsub subscriptions create $SUB_NAME \
        --topic=$TOPIC \
        --push-endpoint=$ENDPOINT \
        --ack-deadline=$ACK_DEADLINE \
        --message-retention-duration=$RETENTION \
        --project=$PROJECT_ID"

    # Add DLQ if provided
    if [[ -n "$DLQ_TOPIC" ]]; then
        CMD="$CMD --dead-letter-topic=$DLQ_TOPIC --max-delivery-attempts=$MAX_RETRIES"
    fi

    eval $CMD 2>/dev/null && echo "created ✓" || echo "FAILED"
}

# Phase 2 -> Phase 3: Raw completion triggers Analytics
create_subscription \
    "mlb-phase3-analytics-sub" \
    "mlb-phase2-raw-complete" \
    "$PHASE3_URL/process" \
    "mlb-phase2-raw-complete-dlq"

# Phase 3 -> Phase 4: Analytics completion triggers Precompute
create_subscription \
    "mlb-phase4-precompute-sub" \
    "mlb-phase3-analytics-complete" \
    "$PHASE4_URL/process" \
    ""

# Phase 4 -> Phase 5: Precompute completion triggers Predictions
create_subscription \
    "mlb-phase5-predictions-sub" \
    "mlb-phase4-precompute-complete" \
    "$PHASE5_URL/pubsub" \
    ""

# Phase 5 -> Phase 6: Predictions completion triggers Grading
create_subscription \
    "mlb-phase6-grading-sub" \
    "mlb-phase5-predictions-complete" \
    "$PHASE6_URL/grade" \
    ""

echo ""
echo "=============================================="
echo "  Subscription Setup Complete"
echo "=============================================="
echo ""
echo "Subscriptions created:"
echo "  mlb-phase3-analytics-sub     (Phase 2 -> Phase 3)"
echo "  mlb-phase4-precompute-sub    (Phase 3 -> Phase 4)"
echo "  mlb-phase5-predictions-sub   (Phase 4 -> Phase 5)"
echo "  mlb-phase6-grading-sub       (Phase 5 -> Phase 6)"
echo ""
echo "To verify subscriptions:"
echo "  gcloud pubsub subscriptions list --filter='name ~ mlb'"
echo ""
echo "To delete subscriptions (if needed):"
echo "  gcloud pubsub subscriptions delete mlb-phase3-analytics-sub"
echo "  gcloud pubsub subscriptions delete mlb-phase4-precompute-sub"
echo "  gcloud pubsub subscriptions delete mlb-phase5-predictions-sub"
echo "  gcloud pubsub subscriptions delete mlb-phase6-grading-sub"
