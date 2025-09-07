#!/usr/bin/env bash
# NBA Scrapers script - requires bash for consistency across environments
# Compatible with macOS zsh, Linux bash, and CI/CD systems

set -e

# Shell compatibility check
if [[ -z "$BASH_VERSION" ]]; then
    echo "❌ This script requires bash but is running in a different shell"
    echo "💡 Please run with: bash $(basename $0)"
    echo "   Or from zsh: bash $0"
    exit 1
fi

# Check bash version for advanced features
if [[ ${BASH_VERSION%%.*} -lt 3 ]]; then
    echo "❌ This script requires bash 3.0+ (found: $BASH_VERSION)"
    echo "💡 Please update bash or use a different system"
    exit 1
fi


echo "📊 NBA Scrapers Deployment Status"
echo "================================="

# Check if base image exists
PROJECT="nba-props-platform"
REGION="us-west2"
BASE_IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/pipeline/nba-base:latest"

echo "🔍 Checking infrastructure..."

if gcloud container images describe "$BASE_IMAGE" >/dev/null 2>&1; then
    echo "✅ Base image exists: $BASE_IMAGE"
    BASE_EXISTS=true
else
    echo "❌ Base image missing: $BASE_IMAGE"
    BASE_EXISTS=false
fi

if [ -f ".last_image" ]; then
    SERVICE_IMAGE=$(cat .last_image)
    echo "✅ Service image: $SERVICE_IMAGE"
    SERVICE_EXISTS=true
else
    echo "❌ No service image built yet"
    SERVICE_EXISTS=false
fi

# Check Cloud Run service
if gcloud run services describe nba-scrapers --region us-west2 >/dev/null 2>&1; then
    SERVICE_URL=$(gcloud run services describe nba-scrapers --region us-west2 --format 'value(status.url)')
    echo "✅ Cloud Run service: $SERVICE_URL"
    DEPLOYED=true
else
    echo "❌ Cloud Run service not deployed"
    DEPLOYED=false
fi

echo ""
echo "🎯 Recommended next steps:"

if [ "$BASE_EXISTS" = false ]; then
    echo "  1. make build-base        # Build base image (5 min)"
fi

if [ "$SERVICE_EXISTS" = false ] && [ "$BASE_EXISTS" = true ]; then
    echo "  2. make build-service     # Build service image (2 min)"
fi

if [ "$SERVICE_EXISTS" = true ] && [ "$DEPLOYED" = false ]; then
    echo "  3. make deploy-fast       # Deploy service (30 sec)"
fi

if [ "$BASE_EXISTS" = false ]; then
    echo ""
    echo "🚀 Or run complete setup: make setup-sophisticated"
fi

if [ "$DEPLOYED" = true ]; then
    echo ""
    echo "🎉 Ready for fast development: make code-deploy-fast (30 seconds!)"
fi
