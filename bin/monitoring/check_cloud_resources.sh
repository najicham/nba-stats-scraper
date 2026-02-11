#!/bin/bash
# Check Cloud Function and Cloud Run resource allocations
#
# This script monitors memory usage and alerts on potential issues:
# - Functions running close to memory limits (>80% usage in logs)
# - Memory allocations below recommended minimums
#
# Usage:
#   ./bin/monitoring/check_cloud_resources.sh
#   ./bin/monitoring/check_cloud_resources.sh --check-logs  # Also check for OOM warnings
#
# Created: 2026-01-25
# Reason: Memory limit exceeded error in # phase2-to-phase3-orchestrator  # REMOVED Session 204 (256MB -> 253MB used)

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
PROJECT_ID="nba-props-platform"
REGION="us-west2"

# Recommended minimum memory allocations by service type
# Orchestrators need 512MB due to BigQuery/Firestore client overhead
# Lightweight monitors can use 256MB
declare -A RECOMMENDED_MEMORY
RECOMMENDED_MEMORY["orchestrator"]=512
RECOMMENDED_MEMORY["monitor"]=256
RECOMMENDED_MEMORY["processor"]=1024
RECOMMENDED_MEMORY["worker"]=2048
RECOMMENDED_MEMORY["default"]=512

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}Cloud Resource Allocation Check${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""

# Function to parse memory string to MB
parse_memory_mb() {
    local mem="$1"
    if [[ "$mem" =~ ([0-9]+)Gi ]]; then
        echo $((${BASH_REMATCH[1]} * 1024))
    elif [[ "$mem" =~ ([0-9]+)G ]]; then
        echo $((${BASH_REMATCH[1]} * 1024))
    elif [[ "$mem" =~ ([0-9]+)Mi ]]; then
        echo ${BASH_REMATCH[1]}
    elif [[ "$mem" =~ ([0-9]+)M ]]; then
        echo ${BASH_REMATCH[1]}
    else
        echo 0
    fi
}

# Function to get recommended memory for a service
get_recommended_memory() {
    local name="$1"
    if [[ "$name" == *"orchestrator"* ]]; then
        echo ${RECOMMENDED_MEMORY["orchestrator"]}
    elif [[ "$name" == *"monitor"* ]] || [[ "$name" == *"alert"* ]] || [[ "$name" == *"check"* ]]; then
        echo ${RECOMMENDED_MEMORY["monitor"]}
    elif [[ "$name" == *"processor"* ]]; then
        echo ${RECOMMENDED_MEMORY["processor"]}
    elif [[ "$name" == *"worker"* ]]; then
        echo ${RECOMMENDED_MEMORY["worker"]}
    else
        echo ${RECOMMENDED_MEMORY["default"]}
    fi
}

echo -e "${YELLOW}Cloud Functions Memory Analysis:${NC}"
echo ""

# Get all Cloud Run services (Cloud Functions Gen2 are Cloud Run services)
services_output=$(gcloud run services list --region=$REGION --format="csv[no-heading](metadata.name,spec.template.spec.containers[0].resources.limits.memory,spec.template.spec.containers[0].resources.limits.cpu)" 2>/dev/null || echo "")

if [ -z "$services_output" ]; then
    echo -e "${RED}Failed to list Cloud Run services${NC}"
    exit 1
fi

# Track issues
issues_found=0
low_memory_services=()

printf "%-45s %10s %10s %s\n" "SERVICE" "MEMORY" "REC" "STATUS"
printf "%-45s %10s %10s %s\n" "-------" "------" "---" "------"

while IFS=',' read -r name memory cpu; do
    if [ -z "$name" ]; then continue; fi

    memory_mb=$(parse_memory_mb "$memory")
    recommended=$(get_recommended_memory "$name")

    # Determine status
    if [ "$memory_mb" -lt "$recommended" ]; then
        status="${YELLOW}⚠ LOW${NC}"
        issues_found=$((issues_found + 1))
        low_memory_services+=("$name:${memory_mb}MB<${recommended}MB")
    else
        status="${GREEN}✓${NC}"
    fi

    printf "%-45s %10s %8sMB %b\n" "$name" "$memory" "$recommended" "$status"
done <<< "$services_output"

echo ""

# Check for OOM warnings in logs if requested
if [[ "$1" == "--check-logs" ]]; then
    echo -e "${YELLOW}Checking for memory warnings in recent logs (last 1 hour)...${NC}"
    echo ""

    # List of orchestrators to check
    orchestrators=(
        "# phase2-to-phase3-orchestrator  # REMOVED Session 204"
        "phase3-to-phase4-orchestrator"
        "phase4-to-phase5-orchestrator"
        "phase5-to-phase6-orchestrator"
    )

    for orch in "${orchestrators[@]}"; do
        oom_count=$(gcloud functions logs read "$orch" --region=$REGION --limit=100 2>/dev/null | grep -c "Memory limit.*exceeded" || echo "0")

        if [ "$oom_count" -gt "0" ]; then
            echo -e "${RED}$orch: $oom_count memory warnings${NC}"
            issues_found=$((issues_found + 1))
        else
            echo -e "${GREEN}$orch: No memory warnings${NC}"
        fi
    done
    echo ""
fi

# Summary
echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}Summary${NC}"
echo -e "${BLUE}================================================${NC}"

if [ $issues_found -gt 0 ]; then
    echo -e "${YELLOW}Found $issues_found potential issues:${NC}"
    for svc in "${low_memory_services[@]}"; do
        echo -e "  ${YELLOW}• $svc${NC}"
    done
    echo ""
    echo -e "${YELLOW}Recommended actions:${NC}"
    echo "  1. Update memory in deploy scripts (bin/orchestrators/deploy_*.sh)"
    echo "  2. Redeploy affected services"
    echo "  3. Monitor for OOM errors after deployment"
    echo ""
    echo -e "${YELLOW}Quick fix for orchestrators:${NC}"
    echo '  sed -i '\''s/MEMORY="256MB"/MEMORY="512MB"/g'\'' bin/orchestrators/deploy_*.sh'
else
    echo -e "${GREEN}All services have adequate memory allocation.${NC}"
fi

echo ""
echo -e "${BLUE}Memory Allocation Guidelines:${NC}"
echo "  • Orchestrators: 512MB minimum (BigQuery/Firestore clients)"
echo "  • Monitors/Alerts: 256MB minimum (lightweight)"
echo "  • Processors: 1GB+ (data processing)"
echo "  • Workers: 2GB+ (ML workloads)"
echo ""
