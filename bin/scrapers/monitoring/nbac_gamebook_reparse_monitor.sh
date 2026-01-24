#!/bin/bash
# FILE: bin/backfill/nbac_gamebook_reparse_monitor.sh
#
# Monitor NBA Gamebook Reparse job progress and status
# Based on existing monitor patterns for consistency

set -euo pipefail

JOB_NAME="nbac-gamebook-reparse"
REGION="${REGION:-us-west2}"
PROJECT_ID="${PROJECT_ID:-nba-props-platform}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

usage() {
    echo "Usage: $0 [quick|logs|status|executions]"
    echo ""
    echo "Commands:"
    echo "  quick       Show current job status and latest logs"
    echo "  logs        Show recent logs from latest execution"  
    echo "  status      Show detailed job status"
    echo "  executions  Show recent job executions"
    echo ""
    echo "Examples:"
    echo "  $0 quick"
    echo "  $0 logs"
    exit 1
}

get_latest_execution() {
    gcloud run jobs executions list \
        --job="$JOB_NAME" \
        --region="$REGION" \
        --limit=1 \
        --format="value(metadata.name)" \
        --quiet 2>/dev/null || echo ""
}

show_quick_status() {
    echo -e "${BLUE}🔍 NBA Gamebook Reparse Job - Quick Status${NC}"
    echo "=========================================="
    
    # Get latest execution
    latest_execution=$(get_latest_execution)
    
    if [[ -z "$latest_execution" ]]; then
        echo -e "${YELLOW}⚠️  No executions found${NC}"
        return 1
    fi
    
    echo -e "${GREEN}📊 Latest Execution:${NC} $latest_execution"
    
    # Get execution status
    status=$(gcloud run jobs executions describe "$latest_execution" \
        --region="$REGION" \
        --format="value(status.conditions[0].type,status.conditions[0].status)" \
        --quiet 2>/dev/null || echo "Unknown Unknown")
    
    condition_type=$(echo "$status" | cut -d' ' -f1)
    condition_status=$(echo "$status" | cut -d' ' -f2)
    
    if [[ "$condition_type" == "Completed" && "$condition_status" == "True" ]]; then
        echo -e "${GREEN}✅ Status: Completed Successfully${NC}"
    elif [[ "$condition_type" == "Running" ]]; then
        echo -e "${YELLOW}🔄 Status: Running${NC}"
    else
        echo -e "${RED}❌ Status: Failed or Unknown${NC}"
    fi
    
    # Show recent progress logs
    echo ""
    echo -e "${BLUE}📝 Recent Progress Logs:${NC}"
    gcloud logging read "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$JOB_NAME\" AND labels.\"run.googleapis.com/execution_name\"=\"$latest_execution\"" \
        --format="value(textPayload)" \
        --limit=10 \
        --order="desc" \
        --quiet 2>/dev/null | grep -E "(Progress:|Successfully|Failed|Complete)" | head -5 || echo "No progress logs found"
    
    echo ""
    echo -e "${BLUE}💡 Next Steps:${NC}"
    echo "  Monitor logs: $0 logs"
    echo "  Full status:  $0 status"
}

show_logs() {
    echo -e "${BLUE}📝 NBA Gamebook Reparse Job - Recent Logs${NC}"
    echo "=========================================="
    
    latest_execution=$(get_latest_execution)
    
    if [[ -z "$latest_execution" ]]; then
        echo -e "${YELLOW}⚠️  No executions found${NC}"
        return 1
    fi
    
    echo -e "${GREEN}Showing logs for:${NC} $latest_execution"
    echo ""
    
    gcloud logging read "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$JOB_NAME\" AND labels.\"run.googleapis.com/execution_name\"=\"$latest_execution\"" \
        --format="value(textPayload)" \
        --limit=20 \
        --order="desc" \
        --quiet || echo "No logs found"
}

show_status() {
    echo -e "${BLUE}📊 NBA Gamebook Reparse Job - Detailed Status${NC}"
    echo "=============================================="
    
    # Job configuration
    echo -e "${GREEN}Job Configuration:${NC}"
    gcloud run jobs describe "$JOB_NAME" \
        --region="$REGION" \
        --format="table(metadata.name,spec.template.spec.template.spec.containers[0].image,spec.template.spec.template.spec.containers[0].resources.limits.memory,spec.template.spec.timeoutSeconds)" \
        --quiet 2>/dev/null || echo "Could not get job details"
    
    echo ""
    
    # Latest execution details
    latest_execution=$(get_latest_execution)
    if [[ -n "$latest_execution" ]]; then
        echo -e "${GREEN}Latest Execution Details:${NC}"
        gcloud run jobs executions describe "$latest_execution" \
            --region="$REGION" \
            --format="table(metadata.name,status.conditions[0].type,status.conditions[0].status,status.startTime,status.completionTime)" \
            --quiet 2>/dev/null || echo "Could not get execution details"
    fi
}

show_executions() {
    echo -e "${BLUE}🏃 NBA Gamebook Reparse Job - Recent Executions${NC}"
    echo "=============================================="
    
    gcloud run jobs executions list \
        --job="$JOB_NAME" \
        --region="$REGION" \
        --limit=10 \
        --format="table(metadata.name,status.conditions[0].type,status.conditions[0].status,status.startTime,status.completionTime)" \
        --quiet || echo "No executions found"
}

# Main command processing
case "${1:-quick}" in
    quick)
        show_quick_status
        ;;
    logs)
        show_logs
        ;;
    status)
        show_status
        ;;
    executions)
        show_executions
        ;;
    *)
        usage
        ;;
esac