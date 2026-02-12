#!/bin/bash
# Post-deploy check: Detect duplicate Pub/Sub subscriptions on a topic
#
# Usage:
#   ./bin/orchestrators/check_duplicate_subscriptions.sh <topic_name> [expected_push_count]
#
# Examples:
#   ./bin/orchestrators/check_duplicate_subscriptions.sh nba-phase4-precompute-complete 1
#   ./bin/orchestrators/check_duplicate_subscriptions.sh nba-phase3-analytics-complete 2
#
# Why this exists (Session 211):
#   gcloud functions deploy with Eventarc creates new triggers but does NOT
#   clean up old ones when a function is renamed (e.g., phase4-to-phase5 →
#   phase4-to-phase5-orchestrator). This leaves orphan subscriptions that
#   cause duplicate processing, race conditions, and wasted compute.
#
#   Session 210: Duplicate Phase 5→6 subscriptions caused GCS 409 race conditions
#   Session 211: Found 4 more orphans across 3 topics (Phase 3→4, 4→5, grading)

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

TOPIC="${1:?Usage: $0 <topic_name> [expected_push_count]}"
EXPECTED="${2:-1}"
PROJECT="nba-props-platform"

echo -e "${YELLOW}Checking for duplicate subscriptions on topic: ${TOPIC}${NC}"

# Get all push subscriptions on this topic (exclude DLQ topics)
PUSH_SUBS=$(gcloud pubsub subscriptions list \
  --project="$PROJECT" \
  --filter="topic:projects/${PROJECT}/topics/${TOPIC}" \
  --format="table(name.basename(),pushConfig.pushEndpoint)" 2>/dev/null \
  | tail -n +2 \
  | grep -v "^$" \
  | grep -v "dlq" \
  || true)

# Count push subscriptions (those with a non-empty endpoint)
PUSH_COUNT=0
while IFS= read -r line; do
  endpoint=$(echo "$line" | awk '{print $2}')
  if [ -n "$endpoint" ] && [ "$endpoint" != "" ]; then
    PUSH_COUNT=$((PUSH_COUNT + 1))
  fi
done <<< "$PUSH_SUBS"

if [ "$PUSH_COUNT" -le "$EXPECTED" ]; then
  echo -e "${GREEN}✓ Topic ${TOPIC}: ${PUSH_COUNT} push subscription(s) (expected ≤${EXPECTED})${NC}"
  exit 0
else
  echo -e "${RED}⚠️  DUPLICATE SUBSCRIPTIONS DETECTED on ${TOPIC}!${NC}"
  echo -e "${RED}   Found ${PUSH_COUNT} push subscriptions (expected ≤${EXPECTED})${NC}"
  echo ""
  echo "Current subscriptions:"
  echo "$PUSH_SUBS" | while IFS= read -r line; do
    echo "  $line"
  done
  echo ""
  echo -e "${YELLOW}To investigate:${NC}"
  echo "  gcloud eventarc triggers list --location=us-west2 --project=${PROJECT} --filter=\"transport.pubsub.topic:${TOPIC}\""
  echo ""
  echo -e "${YELLOW}To fix (delete orphan trigger):${NC}"
  echo "  gcloud eventarc triggers delete TRIGGER_NAME --location=LOCATION --project=${PROJECT}"
  echo ""
  echo -e "${RED}WARNING: Duplicate subscriptions cause each message to be processed multiple times.${NC}"
  echo -e "${RED}This can lead to race conditions, duplicate writes, and wasted compute.${NC}"
  exit 1
fi
