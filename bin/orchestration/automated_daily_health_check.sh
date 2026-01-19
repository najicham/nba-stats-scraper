#!/bin/bash
#
# Automated Daily Health Check Script
#
# Purpose: Runs every morning at 8 AM ET to validate pipeline health
#
# Checks performed:
# 1. Service health endpoints (all 6 production services)
# 2. Pipeline execution status (Phase 3→4→5 completion)
# 3. Yesterday's grading completeness
# 4. Today's prediction readiness
#
# Exit codes:
#   0 - All checks passed
#   1 - Some checks failed (degraded state)
#   2 - Critical checks failed (unhealthy state)
#
# Usage:
#   ./automated_daily_health_check.sh [--slack-webhook URL]
#
# Environment variables:
#   SLACK_WEBHOOK_URL - Slack webhook for notifications
#   GCP_PROJECT - GCP project ID (default: nba-props-platform)
#
# Created: 2026-01-19
# Part of: Daily Orchestration Improvements - Phase 1

set -euo pipefail

# Configuration
PROJECT_ID="${GCP_PROJECT:-nba-props-platform}"
REGION="us-west2"
SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --slack-webhook)
            SLACK_WEBHOOK_URL="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--slack-webhook URL]"
            exit 1
            ;;
    esac
done

# Initialize result tracking
TOTAL_CHECKS=0
PASSED_CHECKS=0
FAILED_CHECKS=0
WARNINGS=0
CRITICAL_FAILURES=0

declare -a CHECK_RESULTS=()

# Helper function to record check result
record_check() {
    local check_name="$1"
    local status="$2"  # pass, warn, fail, critical
    local message="$3"

    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

    case "$status" in
        pass)
            PASSED_CHECKS=$((PASSED_CHECKS + 1))
            echo -e "${GREEN}✅ PASS${NC}: $check_name - $message"
            ;;
        warn)
            WARNINGS=$((WARNINGS + 1))
            echo -e "${YELLOW}⚠️  WARN${NC}: $check_name - $message"
            ;;
        fail)
            FAILED_CHECKS=$((FAILED_CHECKS + 1))
            echo -e "${RED}❌ FAIL${NC}: $check_name - $message"
            ;;
        critical)
            FAILED_CHECKS=$((FAILED_CHECKS + 1))
            CRITICAL_FAILURES=$((CRITICAL_FAILURES + 1))
            echo -e "${RED}🚨 CRITICAL${NC}: $check_name - $message"
            ;;
    esac

    CHECK_RESULTS+=("$status|$check_name|$message")
}

# ============================================================================
# CHECK 1: Service Health Endpoints
# ============================================================================

echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}CHECK 1: Production Service Health Endpoints${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

SERVICES=(
    "prediction-coordinator"
    "mlb-prediction-worker"
    "prediction-worker"
    "nba-admin-dashboard"
    "analytics-processor"
    "precompute-processor"
)

for service in "${SERVICES[@]}"; do
    echo "Checking $service..."

    url="https://${service}-f7p3g7f6ya-wl.a.run.app"

    # Check /health endpoint
    health_code=$(curl -s -o /dev/null -w "%{http_code}" "$url/health" 2>/dev/null || echo "000")

    # Check /ready endpoint
    ready_code=$(curl -s -o /dev/null -w "%{http_code}" "$url/ready" 2>/dev/null || echo "000")
    ready_body=$(curl -s "$url/ready" 2>/dev/null || echo "{}")

    # Determine health status
    if [ "$health_code" = "200" ]; then
        if [ "$ready_code" = "200" ]; then
            record_check "Service: $service" "pass" "Both /health and /ready endpoints OK"
        elif [ "$ready_code" = "503" ]; then
            # 503 on /ready means degraded (some checks failing)
            record_check "Service: $service" "warn" "/health OK, /ready degraded ($ready_code)"
        else
            record_check "Service: $service" "fail" "/health OK, /ready failed ($ready_code)"
        fi
    else
        record_check "Service: $service" "critical" "Service unreachable or /health failed ($health_code)"
    fi
done

# ============================================================================
# CHECK 2: Pipeline Execution Status
# ============================================================================

echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}CHECK 2: Pipeline Execution Status${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

# Get yesterday's date (game date we should have processed)
yesterday=$(date -d "yesterday" +%Y-%m-%d)
today=$(date +%Y-%m-%d)

echo "Checking Phase 3 completion for $yesterday..."

# Check if Phase 3→4 triggered for yesterday
phase3_check=$(python3 -c "
from google.cloud import firestore
import sys

db = firestore.Client(project='$PROJECT_ID')
doc_ref = db.collection('phase3_completion').document('$yesterday')
doc = doc_ref.get()

if doc.exists:
    data = doc.to_dict()
    triggered = data.get('_triggered', False)
    mode = data.get('_mode', 'unknown')
    completed_count = len([k for k in data.keys() if not k.startswith('_')])

    print(f'triggered={triggered}|mode={mode}|completed={completed_count}')
else:
    print('not_found')
" 2>/dev/null || echo "error")

if [[ "$phase3_check" == *"triggered=True"* ]]; then
    mode=$(echo "$phase3_check" | cut -d'|' -f2 | cut -d'=' -f2)
    completed=$(echo "$phase3_check" | cut -d'|' -f3 | cut -d'=' -f2)
    record_check "Phase 3→4 ($yesterday)" "pass" "Triggered successfully (mode=$mode, processors=$completed)"
elif [[ "$phase3_check" == "not_found" ]]; then
    record_check "Phase 3→4 ($yesterday)" "warn" "No Phase 3 completion document found (no games yesterday?)"
elif [[ "$phase3_check" == *"triggered=False"* ]]; then
    record_check "Phase 3→4 ($yesterday)" "fail" "Phase 3 complete but Phase 4 never triggered"
else
    record_check "Phase 3→4 ($yesterday)" "fail" "Could not check Phase 3 status: $phase3_check"
fi

# Check if Phase 4→5 triggered for yesterday
echo "Checking Phase 4 completion for $yesterday..."

phase4_check=$(python3 -c "
from google.cloud import firestore
import sys

db = firestore.Client(project='$PROJECT_ID')
doc_ref = db.collection('phase4_completion').document('$yesterday')
doc = doc_ref.get()

if doc.exists:
    data = doc.to_dict()
    triggered = data.get('_triggered', False)
    completed_count = len([k for k in data.keys() if not k.startswith('_')])

    print(f'triggered={triggered}|completed={completed_count}')
else:
    print('not_found')
" 2>/dev/null || echo "error")

if [[ "$phase4_check" == *"triggered=True"* ]]; then
    completed=$(echo "$phase4_check" | cut -d'|' -f2 | cut -d'=' -f2)
    record_check "Phase 4→5 ($yesterday)" "pass" "Triggered successfully (processors=$completed)"
elif [[ "$phase4_check" == "not_found" ]]; then
    record_check "Phase 4→5 ($yesterday)" "warn" "No Phase 4 completion document found"
elif [[ "$phase4_check" == *"triggered=False"* ]]; then
    record_check "Phase 4→5 ($yesterday)" "fail" "Phase 4 complete but Phase 5 never triggered"
else
    record_check "Phase 4→5 ($yesterday)" "fail" "Could not check Phase 4 status: $phase4_check"
fi

# ============================================================================
# CHECK 3: Yesterday's Prediction Grading
# ============================================================================

echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}CHECK 3: Yesterday's Prediction Grading${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

echo "Checking grading completeness for $yesterday..."

grading_check=$(gcloud firestore documents describe \
    --collection=grading_status \
    --document="$yesterday" \
    --project="$PROJECT_ID" \
    --format="value(data.grading_complete)" 2>/dev/null || echo "not_found")

if [ "$grading_check" = "true" ]; then
    record_check "Grading ($yesterday)" "pass" "Grading completed successfully"
elif [ "$grading_check" = "false" ]; then
    record_check "Grading ($yesterday)" "warn" "Grading document exists but not complete"
elif [ "$grading_check" = "not_found" ]; then
    record_check "Grading ($yesterday)" "warn" "No grading document found (no games yesterday?)"
else
    record_check "Grading ($yesterday)" "warn" "Could not check grading status"
fi

# ============================================================================
# CHECK 4: Today's Prediction Readiness
# ============================================================================

echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}CHECK 4: Today's Prediction Readiness${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

echo "Checking if predictions exist for $today..."

# Check if predictions table has data for today
predictions_count=$(bq query \
    --project_id="$PROJECT_ID" \
    --use_legacy_sql=false \
    --format=csv \
    "SELECT COUNT(*) as count FROM \`nba_predictions.predictions\` WHERE game_date = '$today'" 2>/dev/null | tail -1 || echo "0")

if [ "$predictions_count" -gt 0 ]; then
    record_check "Predictions ($today)" "pass" "$predictions_count predictions generated"
else
    # It's 8 AM, predictions might not be ready yet if games are later
    record_check "Predictions ($today)" "warn" "No predictions yet (may be normal if games are later)"
fi

# ============================================================================
# SUMMARY & SLACK NOTIFICATION
# ============================================================================

echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}HEALTH CHECK SUMMARY${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

echo "Total Checks: $TOTAL_CHECKS"
echo -e "${GREEN}Passed: $PASSED_CHECKS${NC}"
echo -e "${YELLOW}Warnings: $WARNINGS${NC}"
echo -e "${RED}Failed: $FAILED_CHECKS${NC}"
echo -e "${RED}Critical: $CRITICAL_FAILURES${NC}"

# Determine overall status
if [ $CRITICAL_FAILURES -gt 0 ]; then
    OVERALL_STATUS="🚨 CRITICAL"
    STATUS_COLOR="danger"  # Slack color
    EXIT_CODE=2
elif [ $FAILED_CHECKS -gt 0 ]; then
    OVERALL_STATUS="❌ UNHEALTHY"
    STATUS_COLOR="warning"
    EXIT_CODE=1
elif [ $WARNINGS -gt 0 ]; then
    OVERALL_STATUS="⚠️  DEGRADED"
    STATUS_COLOR="warning"
    EXIT_CODE=0
else
    OVERALL_STATUS="✅ HEALTHY"
    STATUS_COLOR="good"
    EXIT_CODE=0
fi

echo -e "\n${BLUE}Overall Status: $OVERALL_STATUS${NC}\n"

# Send Slack notification if webhook configured
if [ -n "$SLACK_WEBHOOK_URL" ]; then
    echo "Sending Slack notification..."

    # Build check details for Slack
    check_details=""
    for result in "${CHECK_RESULTS[@]}"; do
        status=$(echo "$result" | cut -d'|' -f1)
        name=$(echo "$result" | cut -d'|' -f2)
        message=$(echo "$result" | cut -d'|' -f3)

        case "$status" in
            pass) emoji="✅" ;;
            warn) emoji="⚠️" ;;
            fail) emoji="❌" ;;
            critical) emoji="🚨" ;;
        esac

        check_details="${check_details}${emoji} *${name}*: ${message}\n"
    done

    # Send to Slack
    curl -X POST "$SLACK_WEBHOOK_URL" \
        -H 'Content-Type: application/json' \
        -d @- <<EOF
{
    "attachments": [{
        "color": "$STATUS_COLOR",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Daily Pipeline Health Check",
                    "emoji": true
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Overall Status:* $OVERALL_STATUS"
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": "*Passed:*\n$PASSED_CHECKS"},
                    {"type": "mrkdwn", "text": "*Warnings:*\n$WARNINGS"},
                    {"type": "mrkdwn", "text": "*Failed:*\n$FAILED_CHECKS"},
                    {"type": "mrkdwn", "text": "*Critical:*\n$CRITICAL_FAILURES"}
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Check Results:*\n$check_details"
                }
            },
            {
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": "Automated daily health check - $(date '+%Y-%m-%d %H:%M:%S %Z')"
                }]
            }
        ]
    }]
}
EOF

    echo "Slack notification sent"
fi

echo -e "\n${BLUE}Health check completed. Exit code: $EXIT_CODE${NC}\n"
exit $EXIT_CODE
