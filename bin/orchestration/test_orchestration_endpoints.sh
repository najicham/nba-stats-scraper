#!/bin/bash
# test_orchestration_endpoints.sh
# Test all orchestration endpoints before Cloud Run deployment
#
# Usage: ./test_orchestration_endpoints.sh [BASE_URL]
# Examples:
#   ./test_orchestration_endpoints.sh                              # Tests localhost:8080
#   ./test_orchestration_endpoints.sh https://nba-scrapers-xxx.run.app  # Tests Cloud Run

BASE_URL="${1:-http://localhost:8080}"

echo "🧪 Testing NBA Scrapers Orchestration Endpoints"
echo "================================================"
echo "Base URL: $BASE_URL"
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASSED=0
FAILED=0

# Test function
test_endpoint() {
    local name="$1"
    local method="$2"
    local endpoint="$3"
    local data="$4"
    local expected_status="$5"
    
    echo "────────────────────────────────────────────────"
    echo "Test: $name"
    echo "Method: $method $endpoint"
    
    if [ -z "$data" ]; then
        response=$(curl -s -w "\n%{http_code}" -X "$method" "$BASE_URL$endpoint" -H "Content-Type: application/json")
    else
        response=$(curl -s -w "\n%{http_code}" -X "$method" "$BASE_URL$endpoint" -H "Content-Type: application/json" -d "$data")
    fi
    
    # Split response and status code
    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')
    
    # Check HTTP status
    if [ "$http_code" = "$expected_status" ]; then
        echo -e "${GREEN}✓ HTTP Status: $http_code${NC}"
        
        # Parse JSON to check for errors
        if echo "$body" | jq -e '.status' > /dev/null 2>&1; then
            status=$(echo "$body" | jq -r '.status')
            if [ "$status" = "success" ] || [ "$status" = "healthy" ]; then
                echo -e "${GREEN}✓ Status: $status${NC}"
                PASSED=$((PASSED + 1))
            else
                echo -e "${RED}✗ Status: $status${NC}"
                FAILED=$((FAILED + 1))
            fi
        else
            echo -e "${YELLOW}⚠ Could not parse status from response${NC}"
            PASSED=$((PASSED + 1))
        fi
        
        # Show relevant response data
        echo "Response preview:"
        echo "$body" | jq -C '.' 2>/dev/null | head -20 || echo "$body" | head -20
        
    else
        echo -e "${RED}✗ HTTP Status: $http_code (expected $expected_status)${NC}"
        echo "Response:"
        echo "$body" | jq -C '.' 2>/dev/null || echo "$body"
        FAILED=$((FAILED + 1))
    fi
    
    echo ""
}

# Run tests
echo "Starting tests..."
echo ""

# Test 1: Health Check
test_endpoint \
    "Health Check - Orchestration Status" \
    "GET" \
    "/health" \
    "" \
    "200"

# Test 2: List Scrapers
test_endpoint \
    "List Available Scrapers" \
    "GET" \
    "/scrapers" \
    "" \
    "200"

# Test 3: Master Controller Evaluation
test_endpoint \
    "Master Controller - Evaluate Workflows" \
    "POST" \
    "/evaluate" \
    "" \
    "200"

# Test 4: Cleanup Processor
test_endpoint \
    "Cleanup Processor - Run" \
    "POST" \
    "/cleanup" \
    '{}' \
    "200"

# Test 5: Generate Daily Schedule
test_endpoint \
    "Generate Daily Schedule" \
    "POST" \
    "/generate-daily-schedule" \
    '{}' \
    "200"

# Test 6: Trigger Workflow (morning_operations)
test_endpoint \
    "Manual Workflow Trigger - morning_operations" \
    "POST" \
    "/trigger-workflow" \
    '{"workflow_name": "morning_operations"}' \
    "200"

# Test 7: Execute Workflow (betting_lines)
test_endpoint \
    "Execute Workflow - betting_lines" \
    "POST" \
    "/execute-workflow" \
    '{"workflow_name": "betting_lines"}' \
    "200"

# Summary
echo "════════════════════════════════════════════════"
echo "TEST SUMMARY"
echo "════════════════════════════════════════════════"
echo -e "Passed: ${GREEN}$PASSED${NC}"
echo -e "Failed: ${RED}$FAILED${NC}"
echo "Total:  $((PASSED + FAILED))"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed! Ready for deployment.${NC}"
    exit 0
else
    echo -e "${RED}✗ Some tests failed. Review errors before deploying.${NC}"
    exit 1
fi
