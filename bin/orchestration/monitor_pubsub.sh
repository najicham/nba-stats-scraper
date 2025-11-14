#!/bin/bash
# Monitor Pub/Sub queues for stuck/failing messages
# Path: bin/orchestration/monitor_pubsub.sh

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Pub/Sub Queue Health Check"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Get all subscriptions
SUBSCRIPTIONS=$(gcloud pubsub subscriptions list --format="value(name)")

if [ -z "$SUBSCRIPTIONS" ]; then
    echo "No subscriptions found"
    exit 0
fi

echo "Checking $(echo "$SUBSCRIPTIONS" | wc -l) subscription(s)..."
echo ""

# Track if any issues found
ISSUES_FOUND=0

for SUB in $SUBSCRIPTIONS; do
    SUB_NAME=$(basename $SUB)
    
    # Get subscription details
    DETAILS=$(gcloud pubsub subscriptions describe $SUB --format="json")
    
    UNDELIVERED=$(echo "$DETAILS" | jq -r '.numUndeliveredMessages // 0')
    TOPIC=$(echo "$DETAILS" | jq -r '.topic' | xargs basename)
    ACK_DEADLINE=$(echo "$DETAILS" | jq -r '.ackDeadlineSeconds')
    PUSH_ENDPOINT=$(echo "$DETAILS" | jq -r '.pushConfig.pushEndpoint // "PULL"')
    
    # Get oldest unacked message age (handle empty/null values)
    OLDEST_AGE=$(gcloud pubsub subscriptions describe $SUB \
        --format="value(oldestUnackedMessageAge)" 2>/dev/null)
    
    # Default to 0 if empty or null
    if [ -z "$OLDEST_AGE" ] || [ "$OLDEST_AGE" = "null" ]; then
        OLDEST_AGE=0
    fi
    
    # Determine status
    STATUS="✅"
    ALERT=""
    
    if [ "$UNDELIVERED" -gt 1000 ]; then
        STATUS="🚨"
        ALERT="CRITICAL: $UNDELIVERED messages stuck!"
        ISSUES_FOUND=$((ISSUES_FOUND + 1))
    elif [ "$UNDELIVERED" -gt 100 ]; then
        STATUS="⚠️ "
        ALERT="WARNING: $UNDELIVERED messages queued"
        ISSUES_FOUND=$((ISSUES_FOUND + 1))
    elif [ "$UNDELIVERED" -gt 10 ]; then
        STATUS="ℹ️ "
        ALERT="$UNDELIVERED messages (normal backlog)"
    else
        ALERT="Healthy"
    fi
    
    # Check message age (convert seconds to hours) - only if greater than 0
    if [ "$OLDEST_AGE" -gt 3600 ] 2>/dev/null; then
        HOURS=$((OLDEST_AGE / 3600))
        STATUS="⚠️ "
        ALERT="$ALERT | Oldest message: ${HOURS}h old"
        ISSUES_FOUND=$((ISSUES_FOUND + 1))
    fi
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "$STATUS Subscription: $SUB_NAME"
    echo "   Topic: $TOPIC"
    echo "   Undelivered: $UNDELIVERED messages"
    
    # Only show age if it's greater than 0
    if [ "$OLDEST_AGE" -gt 0 ] 2>/dev/null; then
        echo "   Oldest message: $((OLDEST_AGE / 60)) minutes"
    fi
    
    echo "   ACK deadline: ${ACK_DEADLINE}s"
    echo "   Push endpoint: $PUSH_ENDPOINT"
    echo "   Status: $ALERT"
    echo ""
done

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ $ISSUES_FOUND -eq 0 ]; then
    echo "✅ All queues healthy!"
else
    echo "⚠️  Found $ISSUES_FOUND subscription(s) with issues"
    echo ""
    echo "Actions you can take:"
    echo "  1. Purge old messages:"
    echo "     gcloud pubsub subscriptions seek <SUBSCRIPTION> --time=\$(date --iso-8601=seconds)"
    echo ""
    echo "  2. Check dead letter queue:"
    echo "     ./bin/orchestration/check_dead_letter_queue.sh"
    echo ""
    echo "  3. View recent errors:"
    echo "     gcloud logging read 'resource.type=cloud_run_revision' --limit=50"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
