#!/bin/bash
# bin/whats-deployed.sh
#
# Quick check: What commit is deployed vs what's in the repo?
#
# Usage:
#   ./bin/whats-deployed.sh                    # Check all key services
#   ./bin/whats-deployed.sh prediction-worker  # Check specific service
#   ./bin/whats-deployed.sh --diff             # Show what changes are NOT deployed
#
# This answers: "Is my recent fix actually running in production?"

set -e

PROJECT_ID="nba-props-platform"
REGION="us-west2"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Key services to check (most commonly deployed)
KEY_SERVICES=(
    "prediction-worker"
    "prediction-coordinator"
    "nba-phase3-analytics-processors"
    "nba-phase4-precompute-processors"
    "nba-scrapers"
)

show_diff=false
specific_service=""

# Parse arguments
for arg in "$@"; do
    case $arg in
        --diff)
            show_diff=true
            ;;
        --help|-h)
            echo "Usage: $0 [service-name] [--diff]"
            echo ""
            echo "Options:"
            echo "  service-name  Check specific service (default: all key services)"
            echo "  --diff        Show commits NOT yet deployed"
            echo ""
            echo "Examples:"
            echo "  $0                           # Quick status of all services"
            echo "  $0 prediction-worker         # Check prediction-worker"
            echo "  $0 prediction-worker --diff  # Show undeployed changes"
            exit 0
            ;;
        *)
            specific_service="$arg"
            ;;
    esac
done

# Get current repo state
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$REPO_ROOT"

CURRENT_COMMIT=$(git rev-parse --short HEAD)
CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "detached")

echo -e "${BLUE}=== Deployment Status ===${NC}"
echo "Repo: $CURRENT_BRANCH @ $CURRENT_COMMIT"
echo ""

check_service() {
    local service=$1

    # Get deployed commit from Cloud Run labels
    local deployed_commit=$(gcloud run services describe "$service" --region="$REGION" \
        --format="value(metadata.labels.commit-sha)" 2>/dev/null || echo "")

    # Fallback: check BUILD_COMMIT env var if no label
    if [[ -z "$deployed_commit" ]]; then
        deployed_commit=$(gcloud run services describe "$service" --region="$REGION" \
            --format="json" 2>/dev/null | jq -r '.spec.template.spec.containers[0].env[] | select(.name=="BUILD_COMMIT") | .value // empty' 2>/dev/null || echo "")
    fi

    local deployed_at=$(gcloud run revisions list --service="$service" --region="$REGION" \
        --limit=1 --format="value(metadata.creationTimestamp)" 2>/dev/null || echo "")

    if [[ -z "$deployed_commit" ]]; then
        echo -e "${YELLOW}?  $service${NC}"
        echo "   No commit-sha label or BUILD_COMMIT env var"
        echo "   Deploy with: ./bin/deploy-service.sh $service"
        return
    fi

    # Format deployment time
    local deployed_date=""
    if [[ -n "$deployed_at" ]]; then
        deployed_date=$(date -d "$deployed_at" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "$deployed_at")
    fi

    # Check if deployed commit is in history
    local commits_behind=0
    if git merge-base --is-ancestor "$deployed_commit" HEAD 2>/dev/null; then
        commits_behind=$(git rev-list --count "${deployed_commit}..HEAD" 2>/dev/null || echo "?")
    fi

    # Compare to current
    if [[ "${deployed_commit:0:8}" == "${CURRENT_COMMIT:0:8}" ]]; then
        echo -e "${GREEN}✓  $service${NC} - Up to date"
        echo "   Deployed: $deployed_commit @ $deployed_date"
    elif [[ "$commits_behind" == "0" ]]; then
        echo -e "${GREEN}✓  $service${NC} - Up to date"
        echo "   Deployed: $deployed_commit @ $deployed_date"
    else
        echo -e "${RED}✗  $service${NC} - $commits_behind commits behind"
        echo "   Deployed: $deployed_commit @ $deployed_date"
        echo "   Current:  $CURRENT_COMMIT"

        if $show_diff; then
            echo ""
            echo "   Undeployed commits:"
            git log --oneline "${deployed_commit}..HEAD" 2>/dev/null | head -10 | sed 's/^/      /'
            local total=$(git rev-list --count "${deployed_commit}..HEAD" 2>/dev/null || echo "0")
            if [[ "$total" -gt 10 ]]; then
                echo "      ... and $((total - 10)) more"
            fi
        fi
    fi
    echo ""
}

# Check services
if [[ -n "$specific_service" ]]; then
    check_service "$specific_service"
else
    for service in "${KEY_SERVICES[@]}"; do
        check_service "$service"
    done
fi

# Summary hint
if ! $show_diff; then
    echo -e "${CYAN}Tip: Use --diff to see undeployed commits${NC}"
fi
