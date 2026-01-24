#!/bin/bash
# Clear all messages from the Dead Letter Queue
# Use this AFTER verifying data coverage is complete

set -euo pipefail

DLQ_SUB="nba-phase1-scrapers-complete-dlq-sub"

echo "=================================="
echo "DLQ Cleanup"
echo "=================================="
echo ""

# Check count
COUNT=$(gcloud pubsub subscriptions describe "$DLQ_SUB" \
  --format="value(numUndeliveredMessages)" 2>/dev/null || echo "0")

echo "Messages in DLQ: $COUNT"

if [ "$COUNT" -eq 0 ]; then
  echo "✅ DLQ is already empty"
  exit 0
fi

echo ""
echo "⚠️  WARNING: This will permanently delete all DLQ messages"
echo ""
echo "Before proceeding, ensure you have:"
echo "  1. Checked data coverage (./bin/recovery/find_data_gaps.sh)"
echo "  2. Triggered recovery for any missing data"
echo "  3. Verified recovery completed successfully"
echo ""

read -p "Continue with DLQ cleanup? (y/n) " -n 1 -r
echo
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Cancelled"
  exit 0
fi

echo "Clearing DLQ..."
echo ""

DELETED=0
BATCH=1

while true; do
  # Pull and auto-acknowledge (deletes messages)
  RESULT=$(gcloud pubsub subscriptions pull "$DLQ_SUB" \
    --limit=100 \
    --auto-ack \
    --format=json 2>&1)

  BATCH_COUNT=$(echo "$RESULT" | jq '. | length' 2>/dev/null || echo "0")

  if [ "$BATCH_COUNT" -eq 0 ]; then
    break
  fi

  DELETED=$((DELETED + BATCH_COUNT))
  echo "  Batch $BATCH: Deleted $BATCH_COUNT messages (total: $DELETED)"
  BATCH=$((BATCH + 1))

  sleep 1  # Rate limit
done

echo ""
echo "✅ Cleared $DELETED messages from DLQ"
echo ""
echo "Verification:"
FINAL_COUNT=$(gcloud pubsub subscriptions describe "$DLQ_SUB" \
  --format="value(numUndeliveredMessages)" 2>/dev/null || echo "0")
echo "  Remaining messages: $FINAL_COUNT"
