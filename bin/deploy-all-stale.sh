#!/bin/bash
# Deploy all stale services in dependency order
# Usage: ./bin/deploy-all-stale.sh [--dry-run]

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT="nba-props-platform"
REGION="us-west2"
REGISTRY="us-west2-docker.pkg.dev/$PROJECT/nba-props"

DRY_RUN=false
if [[ "$1" == "--dry-run" ]]; then
    DRY_RUN=true
    echo -e "${YELLOW}DRY RUN MODE - No actual deployments will be made${NC}"
fi

echo -e "${BLUE}=== Checking for Stale Services ===${NC}"

# Services in dependency order
declare -A SERVICES=(
    ["nba-phase1-scrapers"]="scrapers"
    ["nba-phase2-raw-processors"]="data_processors/raw"
    ["nba-phase3-analytics-processors"]="data_processors/analytics"
    ["nba-phase4-precompute-processors"]="data_processors/precompute"
    ["prediction-coordinator"]="predictions/coordinator"
    ["prediction-worker"]="predictions/worker"
)

# Order matters for dependencies
SERVICE_ORDER=(
    "nba-phase1-scrapers"
    "nba-phase2-raw-processors"
    "nba-phase3-analytics-processors"
    "nba-phase4-precompute-processors"
    "prediction-coordinator"
    "prediction-worker"
)

STALE_SERVICES=()
DEPLOYED=0
FAILED=0

# Check each service for staleness
for service in "${SERVICE_ORDER[@]}"; do
    source_dir="${SERVICES[$service]}"
    
    # Get deployment time
    deploy_time=$(gcloud run services describe "$service" --region="$REGION" \
        --format="value(status.conditions[0].lastTransitionTime)" 2>/dev/null || echo "")
    
    if [[ -z "$deploy_time" ]]; then
        echo -e "${YELLOW}⚠️  $service: Could not get deployment time${NC}"
        continue
    fi
    
    # Get latest code change time
    code_time=$(git log -1 --format="%ci" -- "$source_dir" 2>/dev/null || echo "")
    
    if [[ -z "$code_time" ]]; then
        echo -e "${YELLOW}⚠️  $service: Could not get code change time${NC}"
        continue
    fi
    
    # Compare times
    deploy_epoch=$(date -d "$deploy_time" +%s 2>/dev/null || echo "0")
    code_epoch=$(date -d "$code_time" +%s 2>/dev/null || echo "0")
    
    if [[ "$code_epoch" -gt "$deploy_epoch" ]]; then
        echo -e "${RED}❌ $service: STALE${NC}"
        echo "   Deployed: $deploy_time"
        echo "   Code changed: $code_time"
        STALE_SERVICES+=("$service")
    else
        echo -e "${GREEN}✅ $service: Up to date${NC}"
    fi
done

echo ""

if [[ ${#STALE_SERVICES[@]} -eq 0 ]]; then
    echo -e "${GREEN}All services are up to date!${NC}"
    exit 0
fi

echo -e "${BLUE}=== Deploying ${#STALE_SERVICES[@]} Stale Services ===${NC}"
echo ""

for service in "${STALE_SERVICES[@]}"; do
    echo -e "${BLUE}Deploying $service...${NC}"
    
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "  [DRY RUN] Would run: gcloud run deploy $service --image=$REGISTRY/$service:latest --region=$REGION"
        continue
    fi
    
    if gcloud run deploy "$service" \
        --image="$REGISTRY/$service:latest" \
        --region="$REGION" \
        --quiet; then
        echo -e "${GREEN}✅ $service deployed successfully${NC}"
        ((DEPLOYED++))
    else
        echo -e "${RED}❌ $service deployment failed${NC}"
        ((FAILED++))
    fi
    echo ""
done

echo -e "${BLUE}=== Deployment Summary ===${NC}"
echo -e "Deployed: ${GREEN}$DEPLOYED${NC}"
echo -e "Failed: ${RED}$FAILED${NC}"
echo -e "Skipped: $((${#STALE_SERVICES[@]} - DEPLOYED - FAILED))"

if [[ $FAILED -gt 0 ]]; then
    exit 1
fi
