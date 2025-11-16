#!/bin/bash
# Dead Letter Queue Replay Script
# See docs/architecture/03-pipeline-monitoring-and-error-handling.md for recovery procedures

set -euo pipefail

# Configuration
PROJECT_ID="nba-props-platform"
DLQ_SUBSCRIPTIONS=(
    "nba-scraper-complete-dlq-sub"       # Phase 1 → Phase 2
    "nba-raw-data-complete-dlq-sub"      # Phase 2 → Phase 3
    "nba-analytics-complete-dlq-sub"     # Phase 3 → Phase 4
    "nba-precompute-complete-dlq-sub"    # Phase 4 → Phase 5
    "nba-predictions-complete-dlq-sub"   # Phase 5 → Phase 6
)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to check DLQ message count
check_dlq() {
    local dlq_sub=$1
    echo -e "${YELLOW}Checking DLQ: $dlq_sub${NC}"

    local count=$(gcloud pubsub subscriptions describe "$dlq_sub" \
        --project="$PROJECT_ID" \
        --format="value(numUndeliveredMessages)" 2>/dev/null || echo "0")

    echo -e "  Messages in DLQ: ${count}"
    return $count
}

# Function to pull messages from DLQ (without ack)
pull_dlq_messages() {
    local dlq_sub=$1
    local limit=${2:-10}

    echo -e "${YELLOW}Pulling up to $limit messages from $dlq_sub (not acking)${NC}"

    gcloud pubsub subscriptions pull "$dlq_sub" \
        --project="$PROJECT_ID" \
        --limit="$limit" \
        --auto-ack=false \
        --format="table(message.data,message.attributes,ackId)"
}

# Function to republish message to main topic
republish_message() {
    local topic=$1
    local message_data=$2

    echo -e "${YELLOW}Republishing message to $topic${NC}"

    echo "$message_data" | gcloud pubsub topics publish "$topic" \
        --project="$PROJECT_ID" \
        --message=-
}

# Main script
main() {
    echo -e "${GREEN}=== DLQ Health Check ===${NC}"
    echo ""

    # Check all DLQs
    total_messages=0
    for dlq in "${DLQ_SUBSCRIPTIONS[@]}"; do
        check_dlq "$dlq"
        count=$(gcloud pubsub subscriptions describe "$dlq" \
            --project="$PROJECT_ID" \
            --format="value(numUndeliveredMessages)" 2>/dev/null || echo "0")
        total_messages=$((total_messages + count))
        echo ""
    done

    echo -e "${GREEN}Total messages across all DLQs: $total_messages${NC}"

    if [ "$total_messages" -eq 0 ]; then
        echo -e "${GREEN}✅ All DLQs are empty - system healthy${NC}"
        exit 0
    else
        echo -e "${RED}⚠️  Found $total_messages messages in DLQs - requires investigation${NC}"
        echo ""
        echo "To view messages in a specific DLQ:"
        echo "  ./replay_dlq.sh pull <DLQ_SUBSCRIPTION_NAME> [limit]"
        echo ""
        echo "Example:"
        echo "  ./replay_dlq.sh pull nba-raw-data-complete-dlq-sub 5"
        exit 1
    fi
}

# Command handling
if [ "${1:-}" = "pull" ]; then
    if [ -z "${2:-}" ]; then
        echo -e "${RED}Error: DLQ subscription name required${NC}"
        echo "Usage: $0 pull <DLQ_SUBSCRIPTION_NAME> [limit]"
        exit 1
    fi
    pull_dlq_messages "$2" "${3:-10}"
else
    main
fi
