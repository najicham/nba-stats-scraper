#!/bin/bash
# Week 0 Security Fixes - Smoke Test Script
# Validates that security fixes are working correctly in staging
#
# Usage: ./bin/deploy/week0_smoke_tests.sh
#
# Prerequisites:
# - Services deployed to staging
# - Valid API key available in ANALYTICS_API_KEY env var (or pass as arg)

set -e

REGION="us-west2"
PROJECT_ID=$(gcloud config get-value project)

# Get API key from environment or argument
API_KEY="${ANALYTICS_API_KEY:-$1}"

if [ -z "$API_KEY" ]; then
    echo "❌ Error: No API key provided"
    echo "Usage: ANALYTICS_API_KEY=<key> ./bin/deploy/week0_smoke_tests.sh"
    echo "   or: ./bin/deploy/week0_smoke_tests.sh <api-key>"
    exit 1
fi

echo "🧪 Week 0 Security Fixes - Smoke Tests"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo ""

PASS=0
FAIL=0

# Function to print test result
print_result() {
    local test_name=$1
    local result=$2
    local details=$3

    if [ "$result" == "PASS" ]; then
        echo "  ✅ PASS: $test_name"
        ((PASS++))
    else
        echo "  ❌ FAIL: $test_name"
        echo "     Details: $details"
        ((FAIL++))
    fi
}

# Get service URLs
get_service_url() {
    local service_name=$1
    gcloud run services describe "$service_name" \
        --region="$REGION" \
        --format="value(status.url)" 2>/dev/null || echo ""
}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 1: Health Endpoints"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

for service in "nba-phase1-scrapers" "nba-phase2-raw-processors" "nba-phase3-analytics-processors" "nba-phase4-precompute-processors" "prediction-worker" "prediction-coordinator"; do
    URL=$(get_service_url "$service")
    if [ -z "$URL" ]; then
        print_result "$service health" "FAIL" "Service not found"
        continue
    fi

    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$URL/health" || echo "000")
    if [ "$HTTP_CODE" == "200" ]; then
        print_result "$service health" "PASS"
    else
        print_result "$service health" "FAIL" "HTTP $HTTP_CODE"
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 2: Authentication Enforcement (Phase 3 Analytics)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

ANALYTICS_URL=$(get_service_url "nba-phase3-analytics-processors")

if [ -n "$ANALYTICS_URL" ]; then
    # Test 2a: Request without API key should return 401
    echo "  Test 2a: Request without API key (expect 401)"
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST "$ANALYTICS_URL/process-date-range" \
        -H "Content-Type: application/json" \
        -d '{"start_date":"2026-01-19","end_date":"2026-01-19"}' || echo "000")

    if [ "$HTTP_CODE" == "401" ]; then
        print_result "No API key returns 401" "PASS"
    else
        print_result "No API key returns 401" "FAIL" "Got HTTP $HTTP_CODE (expected 401)"
    fi

    # Test 2b: Request with valid API key should NOT return 401
    echo "  Test 2b: Request with valid API key (expect NOT 401)"
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST "$ANALYTICS_URL/process-date-range" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: $API_KEY" \
        -d '{"start_date":"2026-01-19","end_date":"2026-01-19"}' || echo "000")

    if [ "$HTTP_CODE" != "401" ] && [ "$HTTP_CODE" != "000" ]; then
        print_result "Valid API key accepted" "PASS" "HTTP $HTTP_CODE"
    else
        print_result "Valid API key accepted" "FAIL" "Got HTTP $HTTP_CODE (should not be 401)"
    fi

    # Test 2c: Request with invalid API key should return 401
    echo "  Test 2c: Request with invalid API key (expect 401)"
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST "$ANALYTICS_URL/process-date-range" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: invalid-key-12345" \
        -d '{"start_date":"2026-01-19","end_date":"2026-01-19"}' || echo "000")

    if [ "$HTTP_CODE" == "401" ]; then
        print_result "Invalid API key returns 401" "PASS"
    else
        print_result "Invalid API key returns 401" "FAIL" "Got HTTP $HTTP_CODE (expected 401)"
    fi
else
    print_result "Authentication tests" "FAIL" "Analytics service not found"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 3: Environment Variables Loaded"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "  Checking Cloud Run environment variables..."
for service in "nba-phase1-scrapers" "nba-phase3-analytics-processors"; do
    ENV_VARS=$(gcloud run services describe "$service" \
        --region="$REGION" \
        --format="value(spec.template.spec.containers[0].env)" 2>/dev/null || echo "")

    if echo "$ENV_VARS" | grep -q "ALLOW_DEGRADED_MODE"; then
        print_result "$service has ALLOW_DEGRADED_MODE" "PASS"
    else
        print_result "$service has ALLOW_DEGRADED_MODE" "FAIL" "Variable not set"
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 4: Secrets Accessible"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

for service in "nba-phase1-scrapers" "nba-phase3-analytics-processors"; do
    SECRETS=$(gcloud run services describe "$service" \
        --region="$REGION" \
        --format="value(spec.template.spec.containers[0].env)" 2>/dev/null || echo "")

    # Check if secrets are mounted (look for secretKeyRef or similar)
    if echo "$SECRETS" | grep -q "secret"; then
        print_result "$service has secrets configured" "PASS"
    else
        print_result "$service has secrets configured" "FAIL" "No secrets found"
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Test 5: Check Logs for Security Issues"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "  Checking for unauthorized access attempts (should see 401s)..."
UNAUTH_COUNT=$(gcloud logging read "resource.type=\"cloud_run_revision\" \
    AND resource.labels.service_name=\"nba-phase3-analytics-processors\" \
    AND httpRequest.status=401" \
    --limit=10 --freshness=10m --format=json 2>/dev/null | jq 'length' || echo "0")

if [ "$UNAUTH_COUNT" -gt "0" ]; then
    print_result "401 logs present" "PASS" "$UNAUTH_COUNT unauthorized attempts logged"
else
    echo "  ℹ️  INFO: No 401s yet (run test 2 first, or wait for unauthorized attempts)"
fi

echo "  Checking for SQL parameterization warnings..."
SQL_WARNINGS=$(gcloud logging read "resource.type=\"cloud_run_revision\" \
    AND (textPayload=~\"SQL\" OR textPayload=~\"query\") \
    AND severity>=WARNING" \
    --limit=5 --freshness=10m --format=json 2>/dev/null | jq 'length' || echo "0")

if [ "$SQL_WARNINGS" == "0" ]; then
    print_result "No SQL warnings" "PASS"
else
    echo "  ⚠️  WARNING: Found $SQL_WARNINGS SQL-related warnings (review manually)"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Tests Passed: $PASS"
echo "  Tests Failed: $FAIL"
echo ""

if [ $FAIL -eq 0 ]; then
    echo "✅ All smoke tests passed!"
    echo ""
    echo "📝 Next steps:"
    echo "  1. Monitor staging for 24 hours"
    echo "  2. Check error rates: gcloud logging read 'severity>=ERROR' --freshness=1h"
    echo "  3. Review deployment checklist for production deployment"
    exit 0
else
    echo "❌ Some tests failed. Review failures above before proceeding."
    exit 1
fi
