#!/bin/bash
# Create all Pub/Sub topics for event-driven pipeline
#
# Usage: ./bin/pubsub/create_topics.sh

set -euo pipefail

PROJECT_ID="nba-props-platform"

echo "========================================="
echo "Creating Pub/Sub Topics"
echo "========================================="
echo ""

# Function to create topic if doesn't exist
create_topic() {
    local topic=$1
    echo -n "Creating topic: $topic... "

    if gcloud pubsub topics describe "$topic" --project="$PROJECT_ID" &>/dev/null; then
        echo "✅ Already exists"
    else
        gcloud pubsub topics create "$topic" --project="$PROJECT_ID"
        echo "✅ Created"
    fi
}

# Phase 1
create_topic "nba-phase1-scrapers-complete"

# Phase 2
create_topic "nba-phase2-raw-complete"

# Phase 2→3 orchestration
create_topic "nba-phase3-trigger"

# Phase 3
create_topic "nba-phase3-analytics-complete"

# Phase 3→4 orchestration
create_topic "nba-phase4-trigger"

# Phase 4
create_topic "nba-phase4-processor-complete"
create_topic "nba-phase4-precompute-complete"

# Phase 5
create_topic "nba-phase5-predictions-complete"

echo ""
echo "========================================="
echo "✅ All topics created"
echo "========================================="
echo ""
echo "To list all topics:"
echo "  gcloud pubsub topics list --project=$PROJECT_ID"
