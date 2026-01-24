#!/bin/bash
set -euo pipefail
# Check Dead Letter Queue for failed messages
# Path: bin/orchestration/check_dead_letter_queue.sh

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚨 Dead Letter Queue Analysis"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

DLQ_SUB="nba-scraper-complete-dlq-sub"

# Check if DLQ subscription exists
if ! gcloud pubsub subscriptions describe $DLQ_SUB &>/dev/null; then
    echo "❌ Dead letter queue subscription not found: $DLQ_SUB"
    exit 1
fi

# Get DLQ stats (handle empty values)
UNDELIVERED=$(gcloud pubsub subscriptions describe $DLQ_SUB \
    --format="value(numUndeliveredMessages)")

# Default to 0 if empty
if [ -z "$UNDELIVERED" ]; then
    UNDELIVERED=0
fi

echo "📊 Dead Letter Queue Stats:"
echo "   Subscription: $DLQ_SUB"
echo "   Failed messages: $UNDELIVERED"
echo ""

if [ "$UNDELIVERED" -eq 0 ]; then
    echo "✅ No failed messages in dead letter queue"
    exit 0
fi

echo "⚠️  $UNDELIVERED message(s) failed after max retries"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 Sample Messages (pulling up to 5):"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Pull and display sample messages without acking them
gcloud pubsub subscriptions pull $DLQ_SUB \
    --limit=5 \
    --format="table(
        message.data.decode(base64),
        message.attributes,
        message.publishTime
    )"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔧 Actions:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "1. Investigate why these messages failed"
echo "   (Check Phase 2 processor logs)"
echo ""
echo "2. Purge DLQ if messages are invalid/old:"
echo "   gcloud pubsub subscriptions seek $DLQ_SUB --time=\$(date --iso-8601=seconds)"
echo ""
echo "3. Reprocess specific message manually:"
echo "   gcloud pubsub subscriptions pull $DLQ_SUB --limit=1 --auto-ack"
echo ""
