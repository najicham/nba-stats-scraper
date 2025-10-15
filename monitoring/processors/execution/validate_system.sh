#!/bin/bash
# File: monitoring/processor_execution_monitoring/validate_system.sh
# Validation script for Processor Execution Monitoring system

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ID="nba-props-platform"

echo "========================================="
echo "Processor Execution Monitoring - System Validation"
echo "========================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}✓${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }

TESTS_PASSED=0
TESTS_FAILED=0
TESTS_WARNED=0

# 1. Configuration Validation
echo "1. Validating Configuration..."
cd "${SCRIPT_DIR}"
if python config/processor_config.py &>/dev/null; then
    pass "Configuration validation passed"
    ((TESTS_PASSED++))
else
    fail "Configuration validation failed"
    ((TESTS_FAILED++))
fi
echo ""

# 2. Check Enabled Processors
echo "2. Checking Enabled Processors..."
ENABLED_COUNT=$(python -c "from config.processor_config import get_enabled_processors; print(len(get_enabled_processors()))" 2>/dev/null || echo "0")
if [ "$ENABLED_COUNT" -gt 0 ]; then
    pass "Found ${ENABLED_COUNT} enabled processor(s)"
    ((TESTS_PASSED++))
else
    warn "No processors enabled for monitoring"
    ((TESTS_WARNED++))
fi
echo ""

# 3. Check BigQuery Table Exists
echo "3. Checking BigQuery Table..."
if bq show --project_id="${PROJECT_ID}" nba_reference.processor_run_history &>/dev/null; then
    pass "processor_run_history table exists"
    ((TESTS_PASSED++))
    
    # Check if table has data
    ROW_COUNT=$(bq query --use_legacy_sql=false --format=csv \
        "SELECT COUNT(*) FROM \`${PROJECT_ID}.nba_reference.processor_run_history\`" 2>/dev/null | tail -n1)
    
    if [ "$ROW_COUNT" -gt 0 ]; then
        pass "Table has ${ROW_COUNT} execution records"
    else
        warn "Table exists but is empty (processors haven't logged runs yet)"
        ((TESTS_WARNED++))
    fi
else
    fail "processor_run_history table does not exist"
    echo "   Run: bq mk --table nba_reference.processor_run_history schemas/bigquery/processor_run_history_schema.sql"
    ((TESTS_FAILED++))
fi
echo ""

# 4. Check BigQuery Permissions
echo "4. Checking BigQuery Access..."
if bq ls --project_id="${PROJECT_ID}" nba_reference &>/dev/null; then
    pass "BigQuery dataset accessible"
    ((TESTS_PASSED++))
else
    fail "Cannot access BigQuery dataset"
    ((TESTS_FAILED++))
fi
echo ""

# 5. Test Core Files Exist
echo "5. Checking Core Files..."
FILES=("execution_monitor_job.py" "utils/execution_monitor.py" "config/processor_config.py")
FILES_OK=0
for file in "${FILES[@]}"; do
    if [ -f "${SCRIPT_DIR}/${file}" ]; then
        ((FILES_OK++))
    else
        fail "Missing file: ${file}"
    fi
done

if [ $FILES_OK -eq ${#FILES[@]} ]; then
    pass "All core files present (${FILES_OK}/${#FILES[@]})"
    ((TESTS_PASSED++))
else
    fail "Some core files missing (${FILES_OK}/${#FILES[@]} found)"
    ((TESTS_FAILED++))
fi
echo ""

# 6. Test Local Execution
echo "6. Testing Local Execution..."
if [ -f "${SCRIPT_DIR}/utils/execution_monitor.py" ]; then
    if python execution_monitor_job.py --dry-run --lookback-days=7 &>/tmp/exec_monitor_test.log; then
        pass "Local execution successful"
        ((TESTS_PASSED++))
    else
        fail "Local execution failed (check /tmp/exec_monitor_test.log)"
        ((TESTS_FAILED++))
    fi
else
    warn "Cannot test execution - utils/execution_monitor.py missing"
    ((TESTS_WARNED++))
fi
echo ""

# 7. Check Cloud Run Deployment
echo "7. Checking Cloud Run Deployment..."
if gcloud run jobs describe processor-execution-monitor --region=us-west2 &>/dev/null; then
    pass "Cloud Run job deployed"
    ((TESTS_PASSED++))
else
    warn "Cloud Run job not deployed yet (run ./deploy.sh)"
    ((TESTS_WARNED++))
fi
echo ""

# 8. Check for Sample Data
echo "8. Checking for Sample Run History Data..."
if bq show --project_id="${PROJECT_ID}" nba_reference.processor_run_history &>/dev/null; then
    GAMEBOOK_RUNS=$(bq query --use_legacy_sql=false --format=csv \
        "SELECT COUNT(*) FROM \`${PROJECT_ID}.nba_reference.processor_run_history\` WHERE processor_name = 'gamebook'" 2>/dev/null | tail -n1)
    
    ROSTER_RUNS=$(bq query --use_legacy_sql=false --format=csv \
        "SELECT COUNT(*) FROM \`${PROJECT_ID}.nba_reference.processor_run_history\` WHERE processor_name = 'roster'" 2>/dev/null | tail -n1)
    
    if [ "$GAMEBOOK_RUNS" -gt 0 ] || [ "$ROSTER_RUNS" -gt 0 ]; then
        pass "Found run history data (gamebook: ${GAMEBOOK_RUNS}, roster: ${ROSTER_RUNS})"
        ((TESTS_PASSED++))
    else
        warn "No run history data yet (processors need to be instrumented)"
        ((TESTS_WARNED++))
    fi
else
    warn "Cannot check for data - table doesn't exist"
    ((TESTS_WARNED++))
fi
echo ""

# Summary
echo "========================================="
echo "Validation Summary"
echo "========================================="
echo -e "${GREEN}Passed:${NC}  ${TESTS_PASSED}"
echo -e "${YELLOW}Warnings:${NC} ${TESTS_WARNED}"
echo -e "${RED}Failed:${NC}  ${TESTS_FAILED}"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    if [ $TESTS_WARNED -eq 0 ]; then
        echo -e "${GREEN}✓ All systems operational!${NC}"
        exit 0
    else
        echo -e "${YELLOW}⚠ System functional with warnings${NC}"
        exit 0
    fi
else
    echo -e "${RED}✗ System has issues that need attention${NC}"
    exit 1
fi