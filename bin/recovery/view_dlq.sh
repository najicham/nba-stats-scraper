#!/bin/bash
# View all messages currently in the Dead Letter Queue
# This helps you understand what processing failures occurred

set -euo pipefail

DLQ_SUB="nba-phase1-scrapers-complete-dlq-sub"
MAX_MESSAGES=${1:-50}

echo "=================================="
echo "DLQ Messages (Phase 1 → 2 failures)"
echo "=================================="
echo ""

# Check count first
COUNT=$(gcloud pubsub subscriptions describe "$DLQ_SUB" \
  --format="value(numUndeliveredMessages)" 2>/dev/null || echo "0")

echo "Total messages in DLQ: $COUNT"

if [ "$COUNT" -eq 0 ]; then
  echo "✅ DLQ is empty - no failures to review"
  exit 0
fi

echo ""
echo "Pulling up to $MAX_MESSAGES messages for review..."
echo ""

# Pull messages (but don't acknowledge - leaves them in DLQ)
gcloud pubsub subscriptions pull "$DLQ_SUB" \
  --limit=$MAX_MESSAGES \
  --format=json > /tmp/dlq_view.json

MESSAGE_COUNT=$(cat /tmp/dlq_view.json | jq '. | length')

if [ "$MESSAGE_COUNT" -eq 0 ]; then
  echo "No messages available to pull"
  exit 0
fi

echo "Displaying $MESSAGE_COUNT messages:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Display each message
cat /tmp/dlq_view.json | jq -r '.[] | .message.data' | while read data; do
  echo "$data" | base64 -d | jq -r '
    "Scraper: \(.scraper_name)" +
    "\n  GCS Path: \(.gcs_path)" +
    "\n  Status: \(.status)" +
    "\n  Records: \(.record_count // "N/A")" +
    "\n  Timestamp: \(.timestamp)" +
    "\n  Execution ID: \(.execution_id)" +
    "\n"
  '
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""
done

echo "Next steps:"
echo "  1. Check data coverage: ./bin/recovery/find_data_gaps.sh"
echo "  2. After verifying data: ./bin/recovery/clear_dlq.sh"
