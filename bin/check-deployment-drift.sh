#!/bin/bash
# bin/check-deployment-drift.sh
#
# Check for deployment drift - services that may have stale code deployed
#
# Usage:
#   ./bin/check-deployment-drift.sh              # Check all services
#   ./bin/check-deployment-drift.sh --verbose    # Include git history details
#
# This script compares:
#   1. When each Cloud Run service was last deployed
#   2. When the source code for that service was last modified
#   3. Reports services that may need redeployment

set -e

PROJECT_ID="nba-props-platform"
REGION="us-west2"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

VERBOSE="${1:-}"

# Map services to their source directories
# Add new services here as they're created
declare -A SERVICE_SOURCES=(
    # Predictions
    ["prediction-worker"]="predictions/worker shared"
    ["prediction-coordinator"]="predictions/coordinator shared"

    # NBA Processing
    ["nba-phase1-scrapers"]="scrapers"
    ["nba-phase2-raw-processors"]="data_processors/phase2"
    ["nba-phase3-analytics-processors"]="data_processors/phase3 shared"
    ["nba-phase4-precompute-processors"]="data_processors/phase4 shared"

    # Grading
    ["nba-grading-service"]="data_processors/grading/nba shared predictions/shared"

    # Orchestration
    ["phase3-to-phase4-orchestrator"]="orchestration/phase3_to_phase4"
    ["phase4-to-phase5-orchestrator"]="orchestration/phase4_to_phase5"

    # Admin
    ["nba-admin-dashboard"]="admin_dashboard"
)

echo -e "${BLUE}=== Deployment Drift Check ===${NC}"
echo "Project: $PROJECT_ID | Region: $REGION"
echo "Checking $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo ""

# Get git repo root
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
cd "$REPO_ROOT"

drift_found=0
total_checked=0

for service in "${!SERVICE_SOURCES[@]}"; do
    source_dirs="${SERVICE_SOURCES[$service]}"

    # Get deployment timestamp
    deploy_info=$(gcloud run revisions list --service="$service" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --limit=1 \
        --format='value(metadata.creationTimestamp)' 2>/dev/null || echo "NOT_FOUND")

    if [ "$deploy_info" = "NOT_FOUND" ] || [ -z "$deploy_info" ]; then
        echo -e "${YELLOW}⚠️  $service: Service not found or no revisions${NC}"
        continue
    fi

    # Convert deployment timestamp to epoch
    deploy_epoch=$(date -d "$deploy_info" +%s 2>/dev/null || echo "0")
    deploy_date=$(date -d "@$deploy_epoch" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "unknown")

    # Get latest commit timestamp affecting the source directories
    latest_commit=""
    latest_commit_epoch=0

    for dir in $source_dirs; do
        if [ -d "$dir" ]; then
            commit_info=$(git log -1 --format="%H %at %s" -- "$dir" 2>/dev/null || echo "")
            if [ -n "$commit_info" ]; then
                commit_epoch=$(echo "$commit_info" | cut -d' ' -f2)
                if [ "$commit_epoch" -gt "$latest_commit_epoch" ]; then
                    latest_commit_epoch=$commit_epoch
                    latest_commit=$(echo "$commit_info" | cut -d' ' -f1)
                fi
            fi
        fi
    done

    if [ "$latest_commit_epoch" = "0" ]; then
        echo -e "${YELLOW}⚠️  $service: Could not determine source code timestamps${NC}"
        continue
    fi

    latest_commit_date=$(date -d "@$latest_commit_epoch" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "unknown")

    total_checked=$((total_checked + 1))

    # Compare timestamps - if code is newer than deployment, flag it
    if [ "$latest_commit_epoch" -gt "$deploy_epoch" ]; then
        drift_found=$((drift_found + 1))
        echo -e "${RED}❌ $service: STALE DEPLOYMENT${NC}"
        echo "   Deployed:    $deploy_date"
        echo "   Code changed: $latest_commit_date"

        if [ "$VERBOSE" = "--verbose" ]; then
            # Show commits since deployment
            echo "   Recent commits:"
            git log --oneline --since="@$deploy_epoch" -- $source_dirs 2>/dev/null | head -5 | sed 's/^/      /'
        fi
        echo ""
    else
        echo -e "${GREEN}✓ $service: Up to date${NC} (deployed $deploy_date)"
    fi
done

echo ""
echo "=== Summary ==="
echo "Services checked: $total_checked"
if [ "$drift_found" -gt 0 ]; then
    echo -e "${RED}Services with drift: $drift_found${NC}"
    echo ""
    echo "Run the following to see what changed:"
    echo "  git log --oneline --since='2 days ago' -- <source_dir>"
    exit 1
else
    echo -e "${GREEN}All services up to date!${NC}"
    exit 0
fi
