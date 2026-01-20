#!/bin/bash

################################################################################
# Canary Deployment Script for NBA Stats Scraper Services
#
# Implements gradual traffic shift with automatic rollback on errors:
# 0% → 5% → 50% → 100%
#
# Usage:
#   ./bin/deploy/canary_deploy.sh <service-name> <source-dir> [options]
#
# Example:
#   ./bin/deploy/canary_deploy.sh prediction-coordinator predictions/coordinator
#
# Options:
#   --region REGION          GCP region (default: us-west2)
#   --project PROJECT        GCP project (default: nba-props-platform)
#   --tag TAG               Cloud Run tag (e.g., "staging" for staging deployment)
#   --monitoring-duration    Seconds to monitor each stage (default: 300 = 5min)
#   --error-threshold        Max errors before rollback (default: 5)
#   --skip-tests            Skip smoke tests (not recommended)
#   --dry-run               Show what would happen without deploying
#
# Based on: docs/08-projects/current/pipeline-reliability-improvements/
#           COMPREHENSIVE-ARCHITECTURAL-IMPROVEMENT-PLAN.md (lines 902-1080)
################################################################################

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default configuration
REGION="${REGION:-us-west2}"
PROJECT="${PROJECT:-nba-props-platform}"
MONITORING_DURATION="${MONITORING_DURATION:-300}"  # 5 minutes
ERROR_THRESHOLD="${ERROR_THRESHOLD:-5}"
SKIP_TESTS=false
DRY_RUN=false
TAG=""  # Optional Cloud Run tag (e.g., "staging")

# Parse arguments
if [ $# -lt 2 ]; then
    echo "Usage: $0 <service-name> <source-dir> [options]"
    echo "Example: $0 prediction-coordinator predictions/coordinator"
    exit 1
fi

SERVICE_NAME="$1"
SOURCE_DIR="$2"
shift 2

# Parse optional arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --region)
            REGION="$2"
            shift 2
            ;;
        --project)
            PROJECT="$2"
            shift 2
            ;;
        --monitoring-duration)
            MONITORING_DURATION="$2"
            shift 2
            ;;
        --error-threshold)
            ERROR_THRESHOLD="$2"
            shift 2
            ;;
        --skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        --tag)
            TAG="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

################################################################################
# Helper Functions
################################################################################

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

get_error_count() {
    local service=$1
    local since_minutes=$2

    # Query Cloud Logging for errors in the last N minutes
    local query="resource.type=\"cloud_run_revision\"
resource.labels.service_name=\"${service}\"
severity>=ERROR
timestamp>=\"$(date -u -d "${since_minutes} minutes ago" +%Y-%m-%dT%H:%M:%SZ)\""

    gcloud logging read "$query" \
        --project="$PROJECT" \
        --limit=1000 \
        --format="value(timestamp)" 2>/dev/null | wc -l
}

check_health_endpoint() {
    local service=$1

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would check health endpoint: curl SERVICE_URL/ready"
        return 0
    fi

    local url
    if [ -n "$TAG" ]; then
        # For tagged deployments, get the tag-specific URL from the service
        url=$(gcloud run services describe "$service" \
            --project="$PROJECT" \
            --region="$REGION" \
            --format="value(status.traffic.where(tag='$TAG').url.first())" 2>/dev/null)

        if [ -z "$url" ]; then
            log_warning "Could not get tagged URL, trying alternative method..."
            # Alternative: get from status.address.url but this might not be tagged
            local base_url=$(gcloud run services describe "$service" \
                --project="$PROJECT" \
                --region="$REGION" \
                --format="value(status.url)" 2>/dev/null)
            # Try to construct tagged URL from base URL
            url=$(echo "$base_url" | sed "s|https://|https://${TAG}---|")
        fi
        log_info "Using tagged URL for health check: $url"
    else
        # For standard deployments, get the main service URL
        url=$(gcloud run services describe "$service" \
            --project="$PROJECT" \
            --region="$REGION" \
            --format="value(status.url)" 2>/dev/null)
    fi

    if [ -z "$url" ]; then
        log_error "Could not get URL for service $service"
        return 1
    fi

    # Check /ready endpoint
    local http_code=$(curl -s -o /dev/null -w "%{http_code}" "${url}/ready" 2>/dev/null || echo "000")

    if [ "$http_code" = "200" ]; then
        log_success "Health check passed: ${url}/ready returned 200"
        return 0
    else
        log_error "Health check failed: ${url}/ready returned $http_code"
        return 1
    fi
}

run_smoke_tests() {
    local service=$1

    if [ "$SKIP_TESTS" = true ]; then
        log_warning "Skipping smoke tests (--skip-tests flag set)"
        return 0
    fi

    log_info "Running smoke tests for $service..."

    # Run pytest smoke tests
    if [ -f "tests/smoke/test_health_endpoints.py" ]; then
        ENVIRONMENT=staging pytest tests/smoke/test_health_endpoints.py -v -k "$service" 2>&1 | tail -20
        local exit_code=${PIPESTATUS[0]}

        if [ $exit_code -eq 0 ]; then
            log_success "Smoke tests passed"
            return 0
        else
            log_error "Smoke tests failed with exit code $exit_code"
            return 1
        fi
    else
        log_warning "Smoke test file not found, skipping tests"
        return 0
    fi
}

deploy_revision() {
    local service=$1
    local source=$2
    local traffic=$3

    log_info "Deploying new revision with ${traffic}% traffic..."

    if [ "$DRY_RUN" = true ]; then
        local tag_flag=""
        if [ -n "$TAG" ]; then
            tag_flag="--tag $TAG"
        fi
        log_info "[DRY RUN] Would deploy: gcloud run deploy $service --source $source --region $REGION --project $PROJECT --no-traffic $tag_flag"
        # Set dummy revision name for dry-run mode
        NEW_REVISION="${service}-dryrun-00001-xyz"
        return 0
    fi

    # Deploy new revision with no traffic
    # Check if Dockerfile exists - if so, build and deploy using Cloud Build
    local deploy_cmd
    if [ -f "$source/Dockerfile" ]; then
        log_info "Found Dockerfile, building image with Cloud Build..."
        local image_name="gcr.io/$PROJECT/$service:$(date +%s)"
        local dockerfile_path="$source/Dockerfile"

        # Create temporary cloudbuild.yaml
        cat > /tmp/cloudbuild-$service.yaml <<EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-f', '$dockerfile_path', '-t', '$image_name', '.']
images: ['$image_name']
EOF

        # Build image using Cloud Build from repo root
        gcloud builds submit \
            --config=/tmp/cloudbuild-$service.yaml \
            --project="$PROJECT" \
            . 2>&1 | tail -30

        local build_exit_code=${PIPESTATUS[0]}
        rm -f /tmp/cloudbuild-$service.yaml

        if [ $build_exit_code -ne 0 ]; then
            log_error "Image build failed"
            return 1
        fi

        log_success "Image built successfully: $image_name"

        # Deploy using the built image
        deploy_cmd="gcloud run deploy $service --image=$image_name --region=$REGION --project=$PROJECT --no-traffic --platform=managed"
    else
        deploy_cmd="gcloud run deploy $service --source=$source --region=$REGION --project=$PROJECT --no-traffic"
    fi

    if [ -n "$TAG" ]; then
        deploy_cmd="$deploy_cmd --tag=$TAG"
    fi
    $deploy_cmd --quiet 2>&1 | tail -10

    if [ ${PIPESTATUS[0]} -ne 0 ]; then
        log_error "Deployment failed"
        return 1
    fi

    # Get the new revision name
    NEW_REVISION=$(gcloud run services describe "$service" \
        --project="$PROJECT" \
        --region="$REGION" \
        --format="value(status.latestCreatedRevisionName)")

    log_success "New revision created: $NEW_REVISION"

    # Update traffic split
    if [ "$traffic" -gt 0 ]; then
        log_info "Setting traffic to ${traffic}%..."
        gcloud run services update-traffic "$service" \
            --to-revisions="$NEW_REVISION=$traffic" \
            --project="$PROJECT" \
            --region="$REGION" \
            --quiet
    fi

    return 0
}

rollback() {
    local service=$1

    log_error "Rolling back deployment..."

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would rollback: gcloud run services update-traffic $service --to-latest --project $PROJECT --region $REGION"
        return 0
    fi

    # Route all traffic back to previous revision
    gcloud run services update-traffic "$service" \
        --to-latest \
        --project="$PROJECT" \
        --region="$REGION" \
        --quiet

    log_warning "Rollback complete. Please investigate logs and redeploy when ready."
    exit 1
}

monitor_stage() {
    local service=$1
    local stage=$2
    local traffic=$3
    local duration=$4

    log_info "Monitoring stage $stage (${traffic}% traffic) for ${duration}s..."

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would monitor for ${duration}s, checking error counts and health"
        return 0
    fi

    local start_time=$(date +%s)
    local end_time=$((start_time + duration))

    while [ $(date +%s) -lt $end_time ]; do
        # Check error count in last 5 minutes
        local error_count=$(get_error_count "$service" 5)

        if [ "$error_count" -gt "$ERROR_THRESHOLD" ]; then
            log_error "Error threshold exceeded: $error_count errors (threshold: $ERROR_THRESHOLD)"
            rollback "$service"
        fi

        local remaining=$((end_time - $(date +%s)))
        echo -ne "\r${BLUE}[MONITOR]${NC} Errors: $error_count | Remaining: ${remaining}s    "

        sleep 10
    done

    echo "" # New line after progress
    log_success "Stage $stage monitoring complete. Error count: $(get_error_count "$service" $((duration / 60)))"
}

################################################################################
# Main Canary Deployment Flow
################################################################################

main() {
    log_info "Starting canary deployment for $SERVICE_NAME"
    log_info "Project: $PROJECT | Region: $REGION"
    log_info "Source: $SOURCE_DIR"
    log_info "Monitoring duration: ${MONITORING_DURATION}s per stage"
    log_info "Error threshold: $ERROR_THRESHOLD errors"
    echo ""

    # Validate service exists
    if ! gcloud run services describe "$SERVICE_NAME" \
        --project="$PROJECT" \
        --region="$REGION" \
        --quiet &>/dev/null; then
        log_error "Service $SERVICE_NAME not found in project $PROJECT, region $REGION"
        exit 1
    fi

    # Validate source directory exists
    if [ ! -d "$SOURCE_DIR" ]; then
        log_error "Source directory not found: $SOURCE_DIR"
        exit 1
    fi

    # For Dockerfile builds, stay in repo root; otherwise cd to source
    local deploy_source
    if [ -f "$SOURCE_DIR/Dockerfile" ]; then
        log_info "Dockerfile detected - deploying from repository root"
        deploy_source="$SOURCE_DIR"
    else
        cd "$SOURCE_DIR" || exit 1
        deploy_source="."
    fi

    # =========================================================================
    # Stage 0: Deploy new revision (0% traffic)
    # =========================================================================
    log_info "=== Stage 0: Deploy new revision (0% traffic) ==="
    if ! deploy_revision "$SERVICE_NAME" "$deploy_source" 0; then
        log_error "Initial deployment failed"
        exit 1
    fi

    # Check health endpoint
    if ! check_health_endpoint "$SERVICE_NAME"; then
        log_error "Health check failed on new revision"
        rollback "$SERVICE_NAME"
    fi

    # Run smoke tests
    if ! run_smoke_tests "$SERVICE_NAME"; then
        log_error "Smoke tests failed on new revision"
        rollback "$SERVICE_NAME"
    fi

    log_success "Stage 0 complete. New revision is healthy with 0% traffic."
    echo ""

    # =========================================================================
    # Stage 1: 5% traffic
    # =========================================================================
    log_info "=== Stage 1: Shift 5% traffic to new revision ==="
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would shift traffic: gcloud run services update-traffic $SERVICE_NAME --to-revisions=$NEW_REVISION=5"
    else
        gcloud run services update-traffic "$SERVICE_NAME" \
            --to-revisions="$NEW_REVISION=5" \
            --project="$PROJECT" \
            --region="$REGION" \
            --quiet
    fi

    monitor_stage "$SERVICE_NAME" "1" 5 "$MONITORING_DURATION"

    # Run smoke tests after monitoring
    if ! run_smoke_tests "$SERVICE_NAME"; then
        log_error "Smoke tests failed at 5% traffic"
        rollback "$SERVICE_NAME"
    fi

    log_success "Stage 1 complete. 5% traffic stable."
    echo ""

    # =========================================================================
    # Stage 2: 50% traffic
    # =========================================================================
    log_info "=== Stage 2: Shift 50% traffic to new revision ==="
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would shift traffic: gcloud run services update-traffic $SERVICE_NAME --to-revisions=$NEW_REVISION=50"
    else
        gcloud run services update-traffic "$SERVICE_NAME" \
            --to-revisions="$NEW_REVISION=50" \
            --project="$PROJECT" \
            --region="$REGION" \
            --quiet
    fi

    monitor_stage "$SERVICE_NAME" "2" 50 "$MONITORING_DURATION"

    log_success "Stage 2 complete. 50% traffic stable."
    echo ""

    # =========================================================================
    # Stage 3: 100% traffic
    # =========================================================================
    log_info "=== Stage 3: Shift 100% traffic to new revision ==="
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would shift traffic: gcloud run services update-traffic $SERVICE_NAME --to-revisions=$NEW_REVISION=100"
    else
        gcloud run services update-traffic "$SERVICE_NAME" \
            --to-revisions="$NEW_REVISION=100" \
            --project="$PROJECT" \
            --region="$REGION" \
            --quiet
    fi

    monitor_stage "$SERVICE_NAME" "3" 100 "$MONITORING_DURATION"

    # Final smoke tests
    if ! run_smoke_tests "$SERVICE_NAME"; then
        log_warning "Final smoke tests failed, but deployment is at 100%. Manual intervention may be needed."
    fi

    log_success "Stage 3 complete. 100% traffic on new revision."
    echo ""

    # =========================================================================
    # Deployment Complete
    # =========================================================================
    log_success "=========================================="
    log_success "CANARY DEPLOYMENT SUCCESSFUL"
    log_success "=========================================="
    log_info "Service: $SERVICE_NAME"
    log_info "Revision: $NEW_REVISION"
    log_info "Traffic: 100% on new revision"
    log_info "Total deployment time: $((MONITORING_DURATION * 3 / 60)) minutes"
    echo ""
    log_info "Next steps:"
    log_info "  1. Monitor service for next 24 hours"
    log_info "  2. Check logs: gcloud logging read 'resource.type=\"cloud_run_revision\" resource.labels.service_name=\"$SERVICE_NAME\"' --limit=50"
    log_info "  3. Verify metrics in Cloud Console"
    echo ""
}

# Run main function
main
