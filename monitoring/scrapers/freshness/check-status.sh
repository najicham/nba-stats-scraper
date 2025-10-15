#!/bin/bash
# File: monitoring/scrapers/freshness/check-status.sh
#
# Quick status check for freshness monitoring system

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}Freshness Monitor Status${NC}"
echo -e "${BLUE}================================${NC}"

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../../" && pwd)"

# Load environment
if [ -f "${PROJECT_ROOT}/.env" ]; then
    set -a
    source "${PROJECT_ROOT}/.env"
    set +a
fi

if [ -f "${SCRIPT_DIR}/job-config.env" ]; then
    set -a
    source "${SCRIPT_DIR}/job-config.env"
    set +a
fi

REGION="${REGION:-us-west2}"
SERVICE_NAME="${SERVICE_NAME:-freshness-monitor}"
SCHEDULER_NAME="${SCHEDULER_NAME:-freshness-monitor-hourly}"

echo ""
echo -e "${YELLOW}1. Cloud Run Job Status${NC}"

# Check if job exists
if gcloud run jobs describe "${SERVICE_NAME}" --region="${REGION}" --project="${GCP_PROJECT_ID}" &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Job exists: ${SERVICE_NAME}"
    
    # Get last execution
    LAST_EXECUTION=$(gcloud run jobs executions list "${SERVICE_NAME}" \
        --region="${REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --limit=1 \
        --format='value(metadata.name)' 2>/dev/null)
    
    if [ -n "${LAST_EXECUTION}" ]; then
        echo -e "  ${GREEN}✓${NC} Last execution: ${LAST_EXECUTION}"
        
        # Get execution status
        STATUS=$(gcloud run jobs executions describe "${LAST_EXECUTION}" \
            --region="${REGION}" \
            --project="${GCP_PROJECT_ID}" \
            --format='value(status.conditions[0].status)' 2>/dev/null)
        
        if [ "${STATUS}" = "True" ]; then
            echo -e "  ${GREEN}✓${NC} Status: Success"
        else
            echo -e "  ${RED}✗${NC} Status: Failed"
        fi
    else
        echo -e "  ${YELLOW}!${NC} No executions found"
    fi
else
    echo -e "  ${RED}✗${NC} Job not found: ${SERVICE_NAME}"
fi

echo ""
echo -e "${YELLOW}2. Cloud Scheduler Status${NC}"

# Check scheduler
if gcloud scheduler jobs describe "${SCHEDULER_NAME}" --location="${REGION}" --project="${GCP_PROJECT_ID}" &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Scheduler exists: ${SCHEDULER_NAME}"
    
    # Get schedule
    SCHEDULE=$(gcloud scheduler jobs describe "${SCHEDULER_NAME}" \
        --location="${REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --format='value(schedule)' 2>/dev/null)
    
    echo -e "  ${GREEN}✓${NC} Schedule: ${SCHEDULE}"
    
    # Get state
    STATE=$(gcloud scheduler jobs describe "${SCHEDULER_NAME}" \
        --location="${REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --format='value(state)' 2>/dev/null)
    
    if [ "${STATE}" = "ENABLED" ]; then
        echo -e "  ${GREEN}✓${NC} State: Enabled"
    else
        echo -e "  ${YELLOW}!${NC} State: ${STATE}"
    fi
else
    echo -e "  ${RED}✗${NC} Scheduler not found: ${SCHEDULER_NAME}"
fi

echo ""
echo -e "${YELLOW}3. Recent Logs (last 5)${NC}"

gcloud logging read \
    "resource.type=cloud_run_job AND resource.labels.job_name=${SERVICE_NAME}" \
    --limit=5 \
    --project="${GCP_PROJECT_ID}" \
    --format='table(timestamp,severity,jsonPayload.message)' 2>/dev/null || echo "  No logs found"

echo ""
echo -e "${YELLOW}4. Configuration Files${NC}"

# Check config files
if [ -f "${SCRIPT_DIR}/config/monitoring_config.yaml" ]; then
    SCRAPER_COUNT=$(grep -c "^  [a-z_]" "${SCRIPT_DIR}/config/monitoring_config.yaml" || echo "0")
    echo -e "  ${GREEN}✓${NC} monitoring_config.yaml (${SCRAPER_COUNT} scrapers)"
else
    echo -e "  ${RED}✗${NC} monitoring_config.yaml not found"
fi

if [ -f "${SCRIPT_DIR}/config/nba_schedule_config.yaml" ]; then
    echo -e "  ${GREEN}✓${NC} nba_schedule_config.yaml"
else
    echo -e "  ${RED}✗${NC} nba_schedule_config.yaml not found"
fi

echo ""
echo -e "${YELLOW}5. Environment Variables${NC}"

if [ -f "${PROJECT_ROOT}/.env" ]; then
    echo -e "  ${GREEN}✓${NC} .env file found"
    
    # Check key variables
    if [ -n "${SLACK_WEBHOOK_URL}" ]; then
        echo -e "  ${GREEN}✓${NC} Slack webhook configured"
    else
        echo -e "  ${YELLOW}!${NC} Slack webhook not configured"
    fi
    
    if [ -n "${EMAIL_ALERTS_TO}" ]; then
        echo -e "  ${GREEN}✓${NC} Email alerts configured"
    else
        echo -e "  ${YELLOW}!${NC} Email alerts not configured"
    fi
    
    if [ -n "${BALL_DONT_LIE_API_KEY}" ]; then
        echo -e "  ${GREEN}✓${NC} Ball Don't Lie API key configured"
    else
        echo -e "  ${YELLOW}!${NC} Ball Don't Lie API key not configured"
    fi
else
    echo -e "  ${RED}✗${NC} .env file not found"
fi

echo ""
echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}Commands${NC}"
echo -e "${BLUE}================================${NC}"
echo ""
echo "Manually trigger job:"
echo "  gcloud run jobs execute ${SERVICE_NAME} --region=${REGION}"
echo ""
echo "View detailed logs:"
echo "  gcloud logging read \"resource.type=cloud_run_job\" --limit=50"
echo ""
echo "Pause scheduler:"
echo "  gcloud scheduler jobs pause ${SCHEDULER_NAME} --location=${REGION}"
echo ""
echo "Resume scheduler:"
echo "  gcloud scheduler jobs resume ${SCHEDULER_NAME} --location=${REGION}"
echo ""
