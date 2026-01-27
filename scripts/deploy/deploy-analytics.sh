#!/bin/bash
# Quick deploy script for analytics processor
# Usage: ./scripts/deploy/deploy-analytics.sh [tag]
#
# This is a simplified wrapper around the full deployment script
# For complex deployments, use: ./bin/analytics/deploy/deploy_analytics_processors.sh

set -euo pipefail

# Configuration
SERVICE_NAME="nba-phase3-analytics-processors"
REGION="us-west2"
PROJECT_ID="nba-props-platform"
DOCKERFILE="docker/analytics-processor.Dockerfile"

# Optional tag for tracking (defaults to git commit SHA)
CUSTOM_TAG="${1:-}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Start deployment
echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║   NBA Analytics Processor - Quick Deploy                  ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Pre-flight checks
log_info "Running pre-flight checks..."

# Check if we're in the right directory
if [ ! -f "$DOCKERFILE" ]; then
    log_error "Dockerfile not found: $DOCKERFILE"
    log_error "Are you in the project root?"
    exit 1
fi

# Check gcloud authentication
if ! gcloud auth list --filter="status:ACTIVE" --format="value(account)" | grep -q "@"; then
    log_error "Not authenticated with gcloud"
    log_error "Run: gcloud auth login"
    exit 1
fi

# Check project
CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null)
if [ "$CURRENT_PROJECT" != "$PROJECT_ID" ]; then
    log_warning "Current project is $CURRENT_PROJECT, expected $PROJECT_ID"
    log_info "Switching to $PROJECT_ID..."
    gcloud config set project $PROJECT_ID
fi

log_success "Pre-flight checks passed"

# Get deployment metadata
GIT_COMMIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
GIT_COMMIT_FULL=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
DEPLOY_TAG="${CUSTOM_TAG:-$GIT_COMMIT_SHA}"

echo ""
log_info "Deployment metadata:"
echo "  Service:      $SERVICE_NAME"
echo "  Region:       $REGION"
echo "  Git branch:   $GIT_BRANCH"
echo "  Commit SHA:   $GIT_COMMIT_SHA"
echo "  Deploy tag:   $DEPLOY_TAG"
echo ""

# Confirmation
read -p "Deploy to production? (yes/no): " -r
echo
if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    log_warning "Deployment cancelled"
    exit 0
fi

# Record start time
DEPLOY_START=$(date +%s)
DEPLOY_START_DISPLAY=$(date '+%Y-%m-%d %H:%M:%S')

log_info "Starting deployment at $DEPLOY_START_DISPLAY..."

# Backup existing root Dockerfile if present
if [ -f "Dockerfile" ]; then
    BACKUP_NAME="Dockerfile.backup.$(date +%s)"
    log_info "Backing up existing Dockerfile to $BACKUP_NAME"
    mv Dockerfile "$BACKUP_NAME"
fi

# Copy Dockerfile to root
log_info "Copying $DOCKERFILE to root..."
cp "$DOCKERFILE" ./Dockerfile

# Build environment variables
ENV_VARS="GCP_PROJECT_ID=$PROJECT_ID"
ENV_VARS="$ENV_VARS,COMMIT_SHA=$GIT_COMMIT_SHA"
ENV_VARS="$ENV_VARS,COMMIT_SHA_FULL=$GIT_COMMIT_FULL"
ENV_VARS="$ENV_VARS,GIT_BRANCH=$GIT_BRANCH"
ENV_VARS="$ENV_VARS,DEPLOY_TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Deploy to Cloud Run
log_info "Deploying to Cloud Run (this takes 3-5 minutes)..."
echo ""

if gcloud run deploy $SERVICE_NAME \
    --source=. \
    --region=$REGION \
    --platform=managed \
    --no-allow-unauthenticated \
    --port=8080 \
    --memory=8Gi \
    --cpu=4 \
    --timeout=3600 \
    --concurrency=1 \
    --min-instances=0 \
    --max-instances=5 \
    --set-env-vars="$ENV_VARS" \
    --labels="commit-sha=$GIT_COMMIT_SHA,git-branch=${GIT_BRANCH//\//-},deploy-tag=${DEPLOY_TAG//\//-}" \
    --clear-base-image; then

    DEPLOY_STATUS=0
else
    DEPLOY_STATUS=$?
fi

# Cleanup temporary Dockerfile
log_info "Cleaning up temporary Dockerfile..."
rm ./Dockerfile

# Calculate deployment time
DEPLOY_END=$(date +%s)
DEPLOY_DURATION=$((DEPLOY_END - DEPLOY_START))

if [ $DEPLOY_DURATION -lt 60 ]; then
    DURATION_DISPLAY="${DEPLOY_DURATION}s"
elif [ $DEPLOY_DURATION -lt 3600 ]; then
    MINUTES=$((DEPLOY_DURATION / 60))
    SECONDS=$((DEPLOY_DURATION % 60))
    DURATION_DISPLAY="${MINUTES}m ${SECONDS}s"
else
    HOURS=$((DEPLOY_DURATION / 3600))
    MINUTES=$(((DEPLOY_DURATION % 3600) / 60))
    SECONDS=$((DEPLOY_DURATION % 60))
    DURATION_DISPLAY="${HOURS}h ${MINUTES}m ${SECONDS}s"
fi

echo ""
echo "════════════════════════════════════════════════════════════"

if [ $DEPLOY_STATUS -eq 0 ]; then
    log_success "Deployment completed successfully in $DURATION_DISPLAY!"

    # Get service URL
    SERVICE_URL=$(gcloud run services describe $SERVICE_NAME \
        --region=$REGION \
        --format="value(status.url)" 2>/dev/null || echo "unknown")

    # Get deployed revision
    DEPLOYED_REVISION=$(gcloud run services describe $SERVICE_NAME \
        --region=$REGION \
        --format="value(status.latestReadyRevisionName)" 2>/dev/null || echo "unknown")

    echo ""
    log_info "Deployment details:"
    echo "  Service URL:  $SERVICE_URL"
    echo "  Revision:     $DEPLOYED_REVISION"
    echo "  Commit:       $GIT_COMMIT_SHA"
    echo "  Duration:     $DURATION_DISPLAY"

    # Verification steps
    echo ""
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║   Next Steps - Verify Deployment                          ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""

    log_info "1. Test health endpoint:"
    echo "   curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \\"
    echo "     \"$SERVICE_URL/health\""
    echo ""

    log_info "2. Test analytics processing:"
    echo "   curl -X POST \"$SERVICE_URL/process-analytics\" \\"
    echo "     -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \\"
    echo "     -H \"Content-Type: application/json\" \\"
    echo "     -d '{\"processor\": \"player_game_summary\", \"start_date\": \"2026-01-27\", \"end_date\": \"2026-01-27\"}'"
    echo ""

    log_info "3. View logs:"
    echo "   gcloud run services logs read $SERVICE_NAME --region=$REGION --limit=50"
    echo ""

    log_info "4. View service details:"
    echo "   gcloud run services describe $SERVICE_NAME --region=$REGION"
    echo ""

    log_info "5. Rollback if needed:"
    echo "   See DEPLOYMENT.md for rollback procedures"
    echo ""

else
    log_error "Deployment failed after $DURATION_DISPLAY"
    echo ""
    log_info "Troubleshooting steps:"
    echo "  1. Check Cloud Build logs:"
    echo "     gcloud builds list --limit=5"
    echo ""
    echo "  2. Check service logs:"
    echo "     gcloud run services logs read $SERVICE_NAME --region=$REGION --limit=100"
    echo ""
    echo "  3. Review deployment runbook:"
    echo "     docs/02-operations/DEPLOYMENT.md"
    echo ""
    exit 1
fi

echo "════════════════════════════════════════════════════════════"
echo ""
