#!/bin/bash
# File: bin/monitoring/week_1_daily_checks.sh
# Purpose: Daily monitoring checks for Week 1 dual-write migration
# Timeline: Jan 21 - Feb 5, 2026 (Days 1-15)
# Usage: ./bin/monitoring/week_1_daily_checks.sh
#
# This script runs the 3 critical daily checks and outputs results in a format
# that can be copied directly into the monitoring log.

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SERVICE_URL="https://prediction-coordinator-756957797294.us-west2.run.app"
PROJECT="nba-props-platform"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Week 1 Daily Monitoring Checks${NC}"
echo -e "${BLUE}Date: $(date '+%Y-%m-%d %H:%M:%S %Z')${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Calculate current day
# Deployment was Jan 20, 2026 (Day 0)
# Day 1 starts Jan 21, 2026
DEPLOY_DATE="2026-01-20"
CURRENT_DATE=$(date '+%Y-%m-%d')
DAY_NUM=$(( ( $(date -d "$CURRENT_DATE" +%s) - $(date -d "$DEPLOY_DATE" +%s) ) / 86400 ))

echo -e "${BLUE}Current Day: Day ${DAY_NUM}${NC}"
echo ""

# Function to run a check and display result
run_check() {
    local check_name="$1"
    local command="$2"
    local expected="$3"

    echo -e "${YELLOW}Check: ${check_name}${NC}"
    echo -e "Expected: ${expected}"
    echo -n "Result: "

    # Run command and capture output
    if output=$(eval "$command" 2>&1); then
        echo -e "${GREEN}✅ PASS${NC}"
        echo "$output"
    else
        echo -e "${RED}❌ FAIL${NC}"
        echo "$output"
        return 1
    fi
    echo ""
}

# ============================================================================
# CHECK 1: Service Health
# ============================================================================
echo -e "${BLUE}1. Service Health Check${NC}"
echo "-----------------------------------"

if ! TOKEN=$(gcloud auth print-identity-token 2>/dev/null); then
    echo -e "${RED}❌ Failed to get auth token${NC}"
    echo "Run: gcloud auth login"
    exit 1
fi

HEALTH_CHECK="curl -s -H \"Authorization: Bearer $TOKEN\" $SERVICE_URL/health"

if HEALTH_OUTPUT=$(eval "$HEALTH_CHECK"); then
    if echo "$HEALTH_OUTPUT" | grep -q '"status":"healthy"'; then
        echo -e "${GREEN}✅ Service is healthy${NC}"
        echo "$HEALTH_OUTPUT" | jq . 2>/dev/null || echo "$HEALTH_OUTPUT"
    else
        echo -e "${RED}❌ Service unhealthy${NC}"
        echo "$HEALTH_OUTPUT"
    fi
else
    echo -e "${RED}❌ Health check failed${NC}"
    echo "Service may be down or unreachable"
fi
echo ""

# ============================================================================
# CHECK 2: Consistency Mismatches
# ============================================================================
echo -e "${BLUE}2. Consistency Mismatch Check${NC}"
echo "-----------------------------------"

CONSISTENCY_CMD="gcloud logging read \"severity=WARNING 'CONSISTENCY MISMATCH'\" --limit 50 --freshness=24h --project=$PROJECT --format='table(timestamp,severity,textPayload)' 2>/dev/null"

echo "Checking for consistency mismatches in last 24 hours..."

if CONSISTENCY_OUTPUT=$(eval "$CONSISTENCY_CMD"); then
    # Count non-header lines
    COUNT=$(echo "$CONSISTENCY_OUTPUT" | tail -n +2 | wc -l)

    if [ "$COUNT" -eq 0 ]; then
        echo -e "${GREEN}✅ No consistency mismatches found (0)${NC}"
    else
        echo -e "${RED}❌ Found $COUNT consistency mismatch(es)${NC}"
        echo "$CONSISTENCY_OUTPUT"
        echo ""
        echo -e "${RED}ACTION REQUIRED: Investigate immediately!${NC}"
        echo "See: docs/02-operations/robustness-improvements-runbook.md"
    fi
else
    echo -e "${YELLOW}⚠️  Could not check consistency mismatches${NC}"
fi
echo ""

# ============================================================================
# CHECK 3: Subcollection Errors
# ============================================================================
echo -e "${BLUE}3. Subcollection Error Check${NC}"
echo "-----------------------------------"

SUBCOLL_CMD="gcloud logging read \"severity>=ERROR 'subcollection'\" --limit 50 --freshness=24h --project=$PROJECT --format='table(timestamp,severity,textPayload)' 2>/dev/null"

echo "Checking for subcollection errors in last 24 hours..."

if SUBCOLL_OUTPUT=$(eval "$SUBCOLL_CMD"); then
    # Count non-header lines
    COUNT=$(echo "$SUBCOLL_OUTPUT" | tail -n +2 | wc -l)

    if [ "$COUNT" -eq 0 ]; then
        echo -e "${GREEN}✅ No subcollection errors found (0)${NC}"
    else
        echo -e "${RED}❌ Found $COUNT subcollection error(s)${NC}"
        echo "$SUBCOLL_OUTPUT"
        echo ""
        echo -e "${RED}ACTION REQUIRED: Investigate immediately!${NC}"
        echo "See: docs/02-operations/robustness-improvements-runbook.md"
    fi
else
    echo -e "${YELLOW}⚠️  Could not check subcollection errors${NC}"
fi
echo ""

# ============================================================================
# CHECK 4: Recent Errors (Bonus Check)
# ============================================================================
echo -e "${BLUE}4. Recent Error Check (Bonus)${NC}"
echo "-----------------------------------"

ERRORS_CMD="gcloud logging read \"resource.labels.service_name=prediction-coordinator severity>=ERROR\" --limit 10 --freshness=1h --project=$PROJECT --format='table(timestamp,severity,textPayload)' 2>/dev/null"

echo "Checking for any recent errors in last hour..."

if ERRORS_OUTPUT=$(eval "$ERRORS_CMD"); then
    # Count non-header lines
    COUNT=$(echo "$ERRORS_OUTPUT" | tail -n +2 | wc -l)

    if [ "$COUNT" -eq 0 ]; then
        echo -e "${GREEN}✅ No recent errors found (0)${NC}"
    else
        echo -e "${YELLOW}⚠️  Found $COUNT recent error(s)${NC}"
        echo "Review if any are related to Week 1 migration:"
        echo "$ERRORS_OUTPUT"
    fi
else
    echo -e "${YELLOW}⚠️  Could not check recent errors${NC}"
fi
echo ""

# ============================================================================
# Summary
# ============================================================================
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "Day: ${DAY_NUM} of 15"
echo -e "Date: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo ""
echo "Next Steps:"
echo "1. Document results in: docs/09-handoff/week-1-monitoring-log.md"
echo "2. If any failures, investigate using runbook"
echo "3. Check #week-1-consistency-monitoring Slack channel"
echo "4. Run again tomorrow at the same time"
echo ""
echo -e "${GREEN}Daily checks complete!${NC}"
