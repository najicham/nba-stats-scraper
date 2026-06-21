#!/bin/bash
set -euo pipefail
# Continuously monitor Pub/Sub queues
# Path: bin/orchestration/watch_queues.sh

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "👁️  Pub/Sub Queue Monitor (Ctrl+C to stop)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

while true; do
    clear
    echo "⏰ $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""

    # Quick summary
    echo "📊 Queue Summary:"
    gcloud pubsub subscriptions list --format="table(
        name.basename():label='Subscription',
        topic.basename():label='Topic',
        numUndeliveredMessages:label='Queued',
        pushConfig.pushEndpoint.basename():label='Endpoint'
    )"

    echo ""
    echo "Refreshing in 30 seconds... (Ctrl+C to stop)"
    sleep 30
done
