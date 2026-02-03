#!/bin/bash
# bin/is-feature-deployed.sh
#
# Check if a specific feature/commit is deployed to a service.
#
# Usage:
#   ./bin/is-feature-deployed.sh prediction-worker "model attribution"
#   ./bin/is-feature-deployed.sh prediction-worker --file predictions/worker/prediction_systems/catboost_v9.py
#   ./bin/is-feature-deployed.sh prediction-worker --commit abc1234
#
# This answers: "Is the model attribution feature actually running in production?"

set -e

REGION="us-west2"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <service> <search-term|--file path|--commit sha>"
    echo ""
    echo "Examples:"
    echo "  $0 prediction-worker 'model attribution'    # Search commit messages"
    echo "  $0 prediction-worker 'Session 84'           # Search for session"
    echo "  $0 prediction-worker --file catboost_v9.py  # Check if file change deployed"
    echo "  $0 prediction-worker --commit abc1234       # Check specific commit"
    exit 1
fi

SERVICE=$1
shift

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$REPO_ROOT"

# Get deployed commit from labels
DEPLOYED_COMMIT=$(gcloud run services describe "$SERVICE" --region="$REGION" \
    --format="value(metadata.labels.commit-sha)" 2>/dev/null || echo "")

# Fallback: check BUILD_COMMIT env var if no label
if [[ -z "$DEPLOYED_COMMIT" ]]; then
    DEPLOYED_COMMIT=$(gcloud run services describe "$SERVICE" --region="$REGION" \
        --format="json" 2>/dev/null | jq -r '.spec.template.spec.containers[0].env[] | select(.name=="BUILD_COMMIT") | .value // empty' 2>/dev/null || echo "")
fi

if [[ -z "$DEPLOYED_COMMIT" ]]; then
    echo -e "${YELLOW}Warning: No commit-sha label or BUILD_COMMIT on $SERVICE${NC}"
    echo "Cannot verify if feature is deployed."
    echo ""
    echo "Deploy with: ./bin/deploy-service.sh $SERVICE"
    exit 1
fi

echo "Service: $SERVICE"
echo "Deployed commit: $DEPLOYED_COMMIT"
echo ""

# Parse mode
mode="search"
search_term=""
target_commit=""
target_file=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --commit)
            mode="commit"
            target_commit=$2
            shift 2
            ;;
        --file)
            mode="file"
            target_file=$2
            shift 2
            ;;
        *)
            search_term="$1"
            shift
            ;;
    esac
done

case $mode in
    search)
        # Find commits matching search term
        echo "Searching for commits matching: '$search_term'"
        echo ""

        # Find the most recent matching commit
        MATCHING_COMMIT=$(git log --oneline --grep="$search_term" -1 --format="%H" 2>/dev/null || echo "")

        if [[ -z "$MATCHING_COMMIT" ]]; then
            echo -e "${YELLOW}No commits found matching '$search_term'${NC}"
            exit 1
        fi

        MATCHING_SHORT=$(git rev-parse --short "$MATCHING_COMMIT")
        MATCHING_MSG=$(git log --oneline -1 "$MATCHING_COMMIT")

        echo "Found: $MATCHING_MSG"
        echo ""

        # Check if deployed commit includes or is after the matching commit
        if git merge-base --is-ancestor "$MATCHING_COMMIT" "$DEPLOYED_COMMIT" 2>/dev/null; then
            echo -e "${GREEN}✓ DEPLOYED${NC}"
            echo "  Commit $MATCHING_SHORT is included in deployed version $DEPLOYED_COMMIT"
        else
            echo -e "${RED}✗ NOT DEPLOYED${NC}"
            echo "  Commit $MATCHING_SHORT is NOT in deployed version $DEPLOYED_COMMIT"
            echo ""
            echo "  To deploy: ./bin/deploy-service.sh $SERVICE"
        fi
        ;;

    commit)
        echo "Checking if commit $target_commit is deployed..."
        echo ""

        if git merge-base --is-ancestor "$target_commit" "$DEPLOYED_COMMIT" 2>/dev/null; then
            echo -e "${GREEN}✓ DEPLOYED${NC}"
            echo "  Commit $target_commit is included in deployed version"
        else
            echo -e "${RED}✗ NOT DEPLOYED${NC}"
            echo "  Commit $target_commit is NOT in deployed version"
            echo ""
            echo "  To deploy: ./bin/deploy-service.sh $SERVICE"
        fi
        ;;

    file)
        echo "Checking last change to $target_file..."
        echo ""

        # Get most recent commit affecting this file
        LAST_FILE_COMMIT=$(git log -1 --format="%H" -- "$target_file" 2>/dev/null || echo "")

        if [[ -z "$LAST_FILE_COMMIT" ]]; then
            echo -e "${YELLOW}No commits found for file $target_file${NC}"
            exit 1
        fi

        LAST_FILE_SHORT=$(git rev-parse --short "$LAST_FILE_COMMIT")
        LAST_FILE_MSG=$(git log --oneline -1 "$LAST_FILE_COMMIT")

        echo "Last change: $LAST_FILE_MSG"
        echo ""

        if git merge-base --is-ancestor "$LAST_FILE_COMMIT" "$DEPLOYED_COMMIT" 2>/dev/null; then
            echo -e "${GREEN}✓ DEPLOYED${NC}"
            echo "  Latest change to $target_file is deployed"
        else
            echo -e "${RED}✗ NOT DEPLOYED${NC}"
            echo "  Latest change to $target_file ($LAST_FILE_SHORT) is NOT deployed"
            echo "  Deployed version: $DEPLOYED_COMMIT"
            echo ""
            echo "  Undeployed changes to this file:"
            git log --oneline "${DEPLOYED_COMMIT}..HEAD" -- "$target_file" 2>/dev/null | sed 's/^/    /'
            echo ""
            echo "  To deploy: ./bin/deploy-service.sh $SERVICE"
        fi
        ;;
esac
