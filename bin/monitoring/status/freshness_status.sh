#!/bin/bash
# freshness_status.sh - Quick status check for scraper freshness monitoring
#
# WHAT THIS DOES:
# 1. Checks if Cloud Run job exists and is configured correctly
# 2. Shows recent execution history
# 3. Displays latest health scores
# 4. Shows alert summary
# 5. Verifies Cloud Scheduler is active
#
# USAGE: ./freshness_status.sh

set -euo pipefail

SERVICE_NAME="freshness-monitor"
SCHEDULER_NAME="freshness-monitor-hourly"
REGION="us-west2"
GCP_PROJECT_ID="nba-props-platform"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}Freshness Monitor Status${NC}"
echo -e "${BLUE}================================${NC}"
echo ""

# Check 1: Cloud Run Job Status
echo -e "${CYAN}📦 Cloud Run Job Status${NC}"
echo "------------------------"

if gcloud run jobs describe "${SERVICE_NAME}" --region="${REGION}" --project="${GCP_PROJECT_ID}" &>/dev/null; then
    echo -e "${GREEN}✓${NC} Job exists: ${SERVICE_NAME}"
    
    # Get job details
    IMAGE=$(gcloud run jobs describe "${SERVICE_NAME}" \
        --region="${REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --format='value(template.template.spec.containers[0].image)' 2>/dev/null)
    
    MEMORY=$(gcloud run jobs describe "${SERVICE_NAME}" \
        --region="${REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --format='value(template.template.spec.containers[0].resources.limits.memory)' 2>/dev/null)
    
    CPU=$(gcloud run jobs describe "${SERVICE_NAME}" \
        --region="${REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --format='value(template.template.spec.containers[0].resources.limits.cpu)' 2>/dev/null)
    
    echo -e "${GREEN}✓${NC} Image: ${IMAGE##*/}"
    echo -e "${GREEN}✓${NC} Resources: ${MEMORY} memory, ${CPU} CPU"
else
    echo -e "${RED}✗${NC} Job not found: ${SERVICE_NAME}"
    echo -e "${YELLOW}💡 Deploy with: ./bin/monitoring/deploy/deploy_freshness_monitor.sh${NC}"
    exit 1
fi

echo ""

# Check 2: Recent Executions
echo -e "${CYAN}🏃 Recent Executions (Last 5)${NC}"
echo "----------------------------"

EXECUTIONS=$(gcloud run jobs executions list "${SERVICE_NAME}" \
    --region="${REGION}" \
    --project="${GCP_PROJECT_ID}" \
    --limit=5 \
    --format='table[no-heading](metadata.name,status.completionTime,status.succeededCount,status.failedCount)' 2>/dev/null)

if [ -n "${EXECUTIONS}" ]; then
    echo "${EXECUTIONS}" | while IFS= read -r line; do
        EXEC_NAME=$(echo "$line" | awk '{print $1}')
        COMPLETION_TIME=$(echo "$line" | awk '{print $2}')
        SUCCEEDED=$(echo "$line" | awk '{print $3}')
        FAILED=$(echo "$line" | awk '{print $4}')
        
        if [ "${SUCCEEDED}" = "1" ]; then
            echo -e "${GREEN}✓${NC} ${EXEC_NAME} - ${COMPLETION_TIME}"
        else
            echo -e "${RED}✗${NC} ${EXEC_NAME} - ${COMPLETION_TIME} (FAILED)"
        fi
    done
else
    echo -e "${YELLOW}⚠${NC} No executions found"
fi

echo ""

# Check 3: Latest Health Score
echo -e "${CYAN}💚 Latest Health Score${NC}"
echo "----------------------"

HEALTH_LOG=$(gcloud logging read \
    "resource.type=cloud_run_job AND resource.labels.job_name=${SERVICE_NAME} AND jsonPayload.message:\"Health Score\"" \
    --project="${GCP_PROJECT_ID}" \
    --limit=1 \
    --format='value(timestamp,jsonPayload.summary.health_score,jsonPayload.summary.ok,jsonPayload.summary.warning,jsonPayload.summary.critical)' 2>/dev/null)

if [ -n "${HEALTH_LOG}" ]; then
    TIMESTAMP=$(echo "$HEALTH_LOG" | awk '{print $1, $2}')
    HEALTH_SCORE=$(echo "$HEALTH_LOG" | awk '{print $3}')
    OK_COUNT=$(echo "$HEALTH_LOG" | awk '{print $4}')
    WARNING_COUNT=$(echo "$HEALTH_LOG" | awk '{print $5}')
    CRITICAL_COUNT=$(echo "$HEALTH_LOG" | awk '{print $6}')
    
    # Color code health score
    if (( $(echo "$HEALTH_SCORE >= 90" | bc -l) )); then
        HEALTH_COLOR="${GREEN}"
        HEALTH_ICON="✓"
    elif (( $(echo "$HEALTH_SCORE >= 70" | bc -l) )); then
        HEALTH_COLOR="${YELLOW}"
        HEALTH_ICON="⚠"
    else
        HEALTH_COLOR="${RED}"
        HEALTH_ICON="✗"
    fi
    
    echo -e "${HEALTH_COLOR}${HEALTH_ICON}${NC} Health Score: ${HEALTH_COLOR}${HEALTH_SCORE}%${NC} (${TIMESTAMP})"
    echo -e "  ${GREEN}OK:${NC} ${OK_COUNT}  ${YELLOW}Warnings:${NC} ${WARNING_COUNT}  ${RED}Critical:${NC} ${CRITICAL_COUNT}"
else
    echo -e "${YELLOW}⚠${NC} No health data found (job may not have run yet)"
fi

echo ""

# Check 4: Recent Alerts
echo -e "${CYAN}🚨 Recent Alerts (Last 24h)${NC}"
echo "---------------------------"

ALERT_COUNT=$(gcloud logging read \
    "resource.type=cloud_run_job AND resource.labels.job_name=${SERVICE_NAME} AND (jsonPayload.message:CRITICAL OR jsonPayload.message:WARNING) AND timestamp>=\"$(date -u -d '24 hours ago' '+%Y-%m-%dT%H:%M:%SZ')\"" \
    --project="${GCP_PROJECT_ID}" \
    --format='value(severity)' 2>/dev/null | wc -l)

CRITICAL_COUNT=$(gcloud logging read \
    "resource.type=cloud_run_job AND resource.labels.job_name=${SERVICE_NAME} AND jsonPayload.message:CRITICAL AND timestamp>=\"$(date -u -d '24 hours ago' '+%Y-%m-%dT%H:%M:%SZ')\"" \
    --project="${GCP_PROJECT_ID}" \
    --format='value(severity)' 2>/dev/null | wc -l)

WARNING_COUNT=$(gcloud logging read \
    "resource.type=cloud_run_job AND resource.labels.job_name=${SERVICE_NAME} AND jsonPayload.message:WARNING AND timestamp>=\"$(date -u -d '24 hours ago' '+%Y-%m-%dT%H:%M:%SZ')\"" \
    --project="${GCP_PROJECT_ID}" \
    --format='value(severity)' 2>/dev/null | wc -l)

if [ "$ALERT_COUNT" -eq 0 ]; then
    echo -e "${GREEN}✓${NC} No alerts in last 24 hours"
else
    echo -e "${YELLOW}⚠${NC} Total alerts: ${ALERT_COUNT}"
    echo -e "  ${RED}Critical:${NC} ${CRITICAL_COUNT}"
    echo -e "  ${YELLOW}Warnings:${NC} ${WARNING_COUNT}"
    
    if [ "$CRITICAL_COUNT" -gt 0 ]; then
        echo ""
        echo -e "${RED}Recent Critical Issues:${NC}"
        gcloud logging read \
            "resource.type=cloud_run_job AND resource.labels.job_name=${SERVICE_NAME} AND jsonPayload.message:CRITICAL AND timestamp>=\"$(date -u -d '24 hours ago' '+%Y-%m-%dT%H:%M:%SZ')\"" \
            --project="${GCP_PROJECT_ID}" \
            --limit=3 \
            --format='value(timestamp,jsonPayload.message)' 2>/dev/null | while IFS= read -r line; do
            echo "  • ${line}"
        done
    fi
fi

echo ""

# Check 5: Cloud Scheduler Status
echo -e "${CYAN}⏰ Cloud Scheduler Status${NC}"
echo "-------------------------"

if gcloud scheduler jobs describe "${SCHEDULER_NAME}" --location="${REGION}" --project="${GCP_PROJECT_ID}" &>/dev/null; then
    echo -e "${GREEN}✓${NC} Scheduler exists: ${SCHEDULER_NAME}"
    
    # Get schedule details
    SCHEDULE=$(gcloud scheduler jobs describe "${SCHEDULER_NAME}" \
        --location="${REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --format='value(schedule)' 2>/dev/null)
    
    STATE=$(gcloud scheduler jobs describe "${SCHEDULER_NAME}" \
        --location="${REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --format='value(state)' 2>/dev/null)
    
    LAST_ATTEMPT=$(gcloud scheduler jobs describe "${SCHEDULER_NAME}" \
        --location="${REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --format='value(status.lastAttemptTime)' 2>/dev/null)
    
    echo -e "${GREEN}✓${NC} Schedule: ${SCHEDULE}"
    
    if [ "${STATE}" = "ENABLED" ]; then
        echo -e "${GREEN}✓${NC} State: ${STATE}"
    else
        echo -e "${YELLOW}⚠${NC} State: ${STATE}"
    fi
    
    if [ -n "${LAST_ATTEMPT}" ]; then
        echo -e "${GREEN}✓${NC} Last attempt: ${LAST_ATTEMPT}"
    fi
else
    echo -e "${YELLOW}⚠${NC} Scheduler not found: ${SCHEDULER_NAME}"
    echo -e "${BLUE}💡 Set up with: cd monitoring/scrapers/freshness && ./setup-scheduler.sh${NC}"
fi

echo ""

# Check 6: Configuration Status
echo -e "${CYAN}⚙️  Configuration${NC}"
echo "----------------"

CONFIG_FILE="monitoring/scrapers/freshness/config/monitoring_config.yaml"
if [ -f "${CONFIG_FILE}" ]; then
    SCRAPER_COUNT=$(grep -c "^  [a-z_]" "${CONFIG_FILE}" 2>/dev/null || echo "0")
    echo -e "${GREEN}✓${NC} Config file exists"
    echo -e "${GREEN}✓${NC} Scrapers configured: ${SCRAPER_COUNT}"
else
    echo -e "${RED}✗${NC} Config file not found: ${CONFIG_FILE}"
fi

SCHEDULE_CONFIG="monitoring/scrapers/freshness/config/nba_schedule_config.yaml"
if [ -f "${SCHEDULE_CONFIG}" ]; then
    echo -e "${GREEN}✓${NC} Season config exists"
else
    echo -e "${RED}✗${NC} Season config not found: ${SCHEDULE_CONFIG}"
fi

echo ""

# Summary
echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}Summary${NC}"
echo -e "${BLUE}================================${NC}"

ISSUES=0

# Check for issues
if ! gcloud run jobs describe "${SERVICE_NAME}" --region="${REGION}" --project="${GCP_PROJECT_ID}" &>/dev/null; then
    echo -e "${RED}✗${NC} Job not deployed"
    ISSUES=$((ISSUES + 1))
fi

if ! gcloud scheduler jobs describe "${SCHEDULER_NAME}" --location="${REGION}" --project="${GCP_PROJECT_ID}" &>/dev/null; then
    echo -e "${YELLOW}⚠${NC} Scheduler not configured"
    ISSUES=$((ISSUES + 1))
fi

if [ "${STATE}" != "ENABLED" ] && [ -n "${STATE}" ]; then
    echo -e "${YELLOW}⚠${NC} Scheduler not enabled"
    ISSUES=$((ISSUES + 1))
fi

if [ "${CRITICAL_COUNT}" -gt 0 ]; then
    echo -e "${RED}✗${NC} ${CRITICAL_COUNT} critical issues in last 24h"
    ISSUES=$((ISSUES + 1))
fi

if [ $ISSUES -eq 0 ]; then
    echo -e "${GREEN}✓ All systems operational${NC}"
else
    echo -e "${YELLOW}⚠ ${ISSUES} issue(s) found${NC}"
fi

echo ""

# Quick commands
echo -e "${BLUE}Quick Commands:${NC}"
echo "---------------"
echo "View logs:        gcloud logging read \"resource.type=cloud_run_job\" --limit=20"
echo "Trigger run:      gcloud run jobs execute ${SERVICE_NAME} --region=${REGION}"
echo "Pause scheduler:  gcloud scheduler jobs pause ${SCHEDULER_NAME} --location=${REGION}"
echo "Resume scheduler: gcloud scheduler jobs resume ${SCHEDULER_NAME} --location=${REGION}"
echo "Test scraper:     cd monitoring/scrapers/freshness && ./test-scraper.py <name> --verbose"
echo ""
