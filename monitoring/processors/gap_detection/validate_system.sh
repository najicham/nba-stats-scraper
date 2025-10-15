#!/bin/bash
# File: monitoring/processing_gap_detection/validate_system.sh
# Comprehensive validation of Processing Gap Detection System

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ID="nba-props-platform"

echo "========================================="
echo "Processing Gap Detection - System Validation"
echo "========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

pass() {
    echo -e "${GREEN}✓${NC} $1"
}

fail() {
    echo -e "${RED}✗${NC} $1"
}

warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Test counter
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
ENABLED_COUNT=$(python -c "from config.processor_config import get_enabled_processors; print(len(get_enabled_processors()))")
if [ "$ENABLED_COUNT" -gt 0 ]; then
    pass "Found ${ENABLED_COUNT} enabled processor(s)"
    ((TESTS_PASSED++))
else
    warn "No processors enabled for monitoring"
    ((TESTS_WARNED++))
fi
echo ""

# 3. Test Path Normalization
echo "3. Testing Path Normalization..."
python3 << 'EOF'
import sys
sys.path.insert(0, '.')
from utils.gap_detector import ProcessingGapDetector

detector = ProcessingGapDetector()

# Test cases
test_cases = [
    ("gs://bucket/path/to/file.json", "path/to/file.json"),
    ("path/to/file.json", "path/to/file.json"),
    ("gs://nba-scraped-data/nba-com/player-list/2025-10-01/file.json", 
     "nba-com/player-list/2025-10-01/file.json")
]

all_passed = True
for input_path, expected in test_cases:
    result = detector._normalize_file_path(input_path)
    if result == expected:
        print(f"  ✓ {input_path[:50]}... → {result[:50]}...")
    else:
        print(f"  ✗ Expected: {expected}")
        print(f"    Got:      {result}")
        all_passed = False

sys.exit(0 if all_passed else 1)
EOF

if [ $? -eq 0 ]; then
    pass "Path normalization working correctly"
    ((TESTS_PASSED++))
else
    fail "Path normalization has issues"
    ((TESTS_FAILED++))
fi
echo ""

# 4. Check GCS Access
echo "4. Checking GCS Access..."
if gsutil ls gs://nba-scraped-data/ &>/dev/null; then
    pass "GCS bucket accessible"
    ((TESTS_PASSED++))
else
    fail "Cannot access GCS bucket"
    ((TESTS_FAILED++))
fi
echo ""

# 5. Check BigQuery Access
echo "5. Checking BigQuery Access..."
if bq ls --project_id="${PROJECT_ID}" nba_raw &>/dev/null; then
    pass "BigQuery dataset accessible"
    ((TESTS_PASSED++))
else
    fail "Cannot access BigQuery dataset"
    ((TESTS_FAILED++))
fi
echo ""

# 6. Test Local Execution
echo "6. Testing Local Execution (Dry Run)..."
if python processing_gap_monitor_job.py --date=2025-10-01 --dry-run &>/tmp/gap_monitor_test.log; then
    pass "Local execution successful"
    ((TESTS_PASSED++))
else
    fail "Local execution failed (check /tmp/gap_monitor_test.log)"
    ((TESTS_FAILED++))
fi
echo ""

# 7. Check Cloud Run Deployment
echo "7. Checking Cloud Run Deployment..."
if gcloud run jobs describe processing-gap-monitor --region=us-west2 &>/dev/null; then
    pass "Cloud Run job deployed"
    ((TESTS_PASSED++))
    
    # Check recent executions
    RECENT_EXEC=$(gcloud run jobs executions list \
        --job=processing-gap-monitor \
        --region=us-west2 \
        --limit=1 \
        --format="value(name)" 2>/dev/null | head -n1)
    
    if [ ! -z "$RECENT_EXEC" ]; then
        pass "Found recent execution: ${RECENT_EXEC}"
    else
        warn "No recent executions found"
        ((TESTS_WARNED++))
    fi
else
    warn "Cloud Run job not deployed yet (run ./deploy.sh)"
    ((TESTS_WARNED++))
fi
echo ""

# 8. Check Notification System
echo "8. Checking Notification Configuration..."
if [ -f "${SCRIPT_DIR}/../../.env" ]; then
    source "${SCRIPT_DIR}/../../.env"
    
    if [ ! -z "${SLACK_WEBHOOK_MONITORING_ERROR}" ]; then
        pass "Slack webhook configured"
        ((TESTS_PASSED++))
    else
        warn "Slack webhook not configured"
        ((TESTS_WARNED++))
    fi
    
    if [ ! -z "${BREVO_SMTP_USERNAME}" ]; then
        pass "Email (Brevo) configured"
        ((TESTS_PASSED++))
    else
        warn "Email not configured (optional)"
        ((TESTS_WARNED++))
    fi
else
    warn "No .env file found"
    ((TESTS_WARNED++))
fi
echo ""

# 9. Check Documentation
echo "9. Checking Documentation..."
DOCS=("README.md" "ARCHITECTURE.md" "ADDING_PROCESSORS.md" "UPDATES.md")
DOCS_FOUND=0
for doc in "${DOCS[@]}"; do
    if [ -f "${SCRIPT_DIR}/${doc}" ]; then
        ((DOCS_FOUND++))
    fi
done

if [ $DOCS_FOUND -eq 4 ]; then
    pass "All documentation files present (${DOCS_FOUND}/4)"
    ((TESTS_PASSED++))
elif [ $DOCS_FOUND -gt 0 ]; then
    warn "Some documentation files missing (${DOCS_FOUND}/4 found)"
    ((TESTS_WARNED++))
else
    fail "No documentation files found"
    ((TESTS_FAILED++))
fi
echo ""

# 10. Test with Real Data
echo "10. Testing with Real Data..."
echo "   Looking for recent GCS files..."
RECENT_DATE=$(date -d "1 day ago" +%Y-%m-%d)
TEST_PREFIX="nba-com/player-list/${RECENT_DATE}/"

if gsutil ls "gs://nba-scraped-data/${TEST_PREFIX}" &>/dev/null; then
    pass "Found files for ${RECENT_DATE}"
    
    echo "   Running gap check on ${RECENT_DATE}..."
    if python processing_gap_monitor_job.py --date=${RECENT_DATE} --dry-run --processors=nbac_player_list &>/tmp/gap_test_real.log; then
        
        # Check if gap was detected or not
        if grep -q "No processing gaps detected" /tmp/gap_test_real.log; then
            pass "Gap check passed: File processed correctly"
            ((TESTS_PASSED++))
        elif grep -q "Processing Gap Detected" /tmp/gap_test_real.log; then
            warn "Gap detected for ${RECENT_DATE} - file may not be processed yet"
            ((TESTS_WARNED++))
        else
            warn "Gap check completed but result unclear"
            ((TESTS_WARNED++))
        fi
    else
        fail "Gap check execution failed"
        ((TESTS_FAILED++))
    fi
else
    warn "No recent files found for testing (this is OK during off-season)"
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