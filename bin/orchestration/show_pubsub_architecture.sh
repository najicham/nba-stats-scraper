#!/bin/bash
set -euo pipefail
# Show complete Pub/Sub architecture
# Path: bin/orchestration/show_pubsub_architecture.sh

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Complete Pub/Sub Architecture"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Get all topics
echo "📌 Topics:"
TOPICS=$(gcloud pubsub topics list --format="value(name)")
if [ -z "$TOPICS" ]; then
    echo "   No topics found"
else
    for TOPIC in $TOPICS; do
        TOPIC_NAME=$(basename $TOPIC)
        echo "   • $TOPIC_NAME"
    done
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📨 Subscriptions:"
echo ""

SUBSCRIPTIONS=$(gcloud pubsub subscriptions list --format="value(name)")

if [ -z "$SUBSCRIPTIONS" ]; then
    echo "   No subscriptions found"
else
    for SUB in $SUBSCRIPTIONS; do
        SUB_NAME=$(basename $SUB)
        
        # Get subscription details
        DETAILS=$(gcloud pubsub subscriptions describe $SUB --format="json")
        
        TOPIC=$(echo "$DETAILS" | jq -r '.topic' | xargs basename)
        PUSH_ENDPOINT=$(echo "$DETAILS" | jq -r '.pushConfig.pushEndpoint // "PULL"')
        DLQ_TOPIC=$(echo "$DETAILS" | jq -r '.deadLetterPolicy.deadLetterTopic // "none"' | xargs basename)
        MAX_DELIVERY=$(echo "$DETAILS" | jq -r '.deadLetterPolicy.maxDeliveryAttempts // "none"')
        
        echo "   📬 $SUB_NAME"
        echo "      ├─ Reads from: $TOPIC"
        echo "      ├─ Delivers to: $PUSH_ENDPOINT"
        
        if [ "$DLQ_TOPIC" != "none" ] && [ "$DLQ_TOPIC" != "null" ]; then
            echo "      └─ Dead letter: $DLQ_TOPIC (after $MAX_DELIVERY attempts)"
        else
            echo "      └─ No dead letter queue"
        fi
        echo ""
    done
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔄 Data Flow:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Phase 1 Scrapers"
echo "   ↓ (publish)"
echo "Topic: nba-scraper-complete"
echo "   ↓ (subscribe)"
echo "Subscription: nba-processors-sub"
echo "   ↓ (HTTP push)"
echo "Service: nba-processors → /process"
echo "   ↓ (on failure × 5)"
echo "Topic: nba-scraper-complete-dlq"
echo "   ↓ (subscribe)"
echo "Subscription: nba-scraper-complete-dlq-sub (PULL)"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
