#!/bin/bash
# check_scraper_deployment.sh
#
# Verifies scraper services are deployed with correct code.
# This script catches the "wrong Dockerfile" deployment issue.
#
# Usage: ./bin/monitoring/check_scraper_deployment.sh [--fix]
#
# Returns:
#   0 - All scraper services have correct code
#   1 - At least one scraper service has wrong code
#
# Created: 2026-01-29 (Post-mortem from wrong deployment incident)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Services to check
SCRAPER_SERVICES=(
    "nba-scrapers"
    "nba-phase1-scrapers"
)

# Expected service identity in health response
EXPECTED_IDENTITY="nba-scrapers"

# Track failures
FAILURES=0
FIX_MODE=false

# Parse arguments
if [[ "$1" == "--fix" ]]; then
    FIX_MODE=true
fi

echo "=== Scraper Deployment Verification ==="
echo "Checking that scraper services have correct code deployed..."
echo ""

for SERVICE in "${SCRAPER_SERVICES[@]}"; do
    echo -n "Checking $SERVICE... "

    # Get service URL
    URL=$(gcloud run services describe "$SERVICE" \
        --region=us-west2 \
        --format="value(status.url)" 2>/dev/null)

    if [[ -z "$URL" ]]; then
        echo -e "${YELLOW}SKIP${NC} (service not found)"
        continue
    fi

    # Get identity token for authenticated request
    TOKEN=$(gcloud auth print-identity-token --audiences="$URL" 2>/dev/null)

    # Check health endpoint
    RESPONSE=$(curl -s -H "Authorization: Bearer $TOKEN" "$URL/health" 2>/dev/null || echo '{"error":"connection failed"}')

    # Extract service identity from response
    ACTUAL_IDENTITY=$(echo "$RESPONSE" | grep -o '"service":"[^"]*"' | cut -d'"' -f4 || echo "unknown")

    if [[ "$ACTUAL_IDENTITY" == "$EXPECTED_IDENTITY" ]]; then
        echo -e "${GREEN}OK${NC} (service: $ACTUAL_IDENTITY)"
    else
        echo -e "${RED}WRONG CODE${NC} (got: $ACTUAL_IDENTITY, expected: $EXPECTED_IDENTITY)"
        FAILURES=$((FAILURES + 1))

        if [[ "$FIX_MODE" == true ]]; then
            echo "  Attempting to fix with ./bin/deploy-service.sh $SERVICE..."
            ./bin/deploy-service.sh "$SERVICE" || echo "  Fix failed!"
        fi
    fi
done

echo ""

if [[ $FAILURES -gt 0 ]]; then
    echo -e "${RED}=== DEPLOYMENT VERIFICATION FAILED ===${NC}"
    echo "$FAILURES service(s) have wrong code deployed."
    echo ""
    echo "To fix, run:"
    for SERVICE in "${SCRAPER_SERVICES[@]}"; do
        echo "  ./bin/deploy-service.sh $SERVICE"
    done
    echo ""
    echo "Or run this script with --fix to auto-deploy:"
    echo "  ./bin/monitoring/check_scraper_deployment.sh --fix"
    exit 1
else
    echo -e "${GREEN}=== All scraper services have correct code ===${NC}"
    exit 0
fi
