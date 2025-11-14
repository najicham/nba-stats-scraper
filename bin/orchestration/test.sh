#!/bin/bash
# bin/orchestration/test.sh
#
# Test NBA Props Orchestration endpoints (local or Cloud Run)
# Usage:
#   ./bin/orchestration/test.sh              # Test Cloud Run
#   ./bin/orchestration/test.sh --local      # Test local (localhost:8080)

set -e

# Determine target
if [[ "$1" == "--local" ]]; then
    SERVICE_URL="http://localhost:8080"
    AUTH_HEADER=""
    echo "🧪 Testing LOCAL orchestration service"
else
    PROJECT_ID="nba-props-platform"
    REGION="us-west2"
    SERVICE_NAME="nba-orchestration-service"
    
    SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
        --platform=managed \
        --region=${REGION} \
        --format="value(status.url)" \
        --project=${PROJECT_ID} 2>/dev/null)
    
    if [[ -z "$SERVICE_URL" ]]; then
        echo "❌ Cloud Run service not found. Deploy first or use --local flag."
        exit 1
    fi
    
    AUTH_TOKEN=$(gcloud auth print-identity-token)
    AUTH_HEADER="Authorization: Bearer ${AUTH_TOKEN}"
    echo "🧪 Testing CLOUD RUN orchestration service"
fi

echo "URL: ${SERVICE_URL}"
echo ""

# Function to run test
run_test() {
    local name=$1
    local endpoint=$2
    local method=${3:-GET}
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Test: ${name}"
    echo "Endpoint: ${method} ${endpoint}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    if [[ "$method" == "POST" ]]; then
        if [[ -n "$AUTH_HEADER" ]]; then
            curl -s -X POST \
                -H "${AUTH_HEADER}" \
                -H "Content-Type: application/json" \
                -d '{}' \
                "${SERVICE_URL}${endpoint}" | jq '.'
        else
            curl -s -X POST \
                -H "Content-Type: application/json" \
                -d '{}' \
                "${SERVICE_URL}${endpoint}" | jq '.'
        fi
    else
        if [[ -n "$AUTH_HEADER" ]]; then
            curl -s -H "${AUTH_HEADER}" "${SERVICE_URL}${endpoint}" | jq '.'
        else
            curl -s "${SERVICE_URL}${endpoint}" | jq '.'
        fi
    fi
    
    local exit_code=$?
    if [[ $exit_code -eq 0 ]]; then
        echo "✅ PASS"
    else
        echo "❌ FAIL"
    fi
    echo ""
}

# Run tests
run_test "Health Check" "/health" "GET"
run_test "Generate Daily Schedule" "/generate-daily-schedule" "POST"
run_test "Evaluate Workflows (Master Controller)" "/evaluate-workflows" "POST"
run_test "Run Cleanup Processor" "/run-cleanup" "POST"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Testing Complete"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
