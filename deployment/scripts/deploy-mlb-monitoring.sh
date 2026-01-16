#!/bin/bash
set -e

# MLB Monitoring Infrastructure Deployment Script
# Deploys monitoring, validation, and scheduling infrastructure for MLB

# Configuration
PROJECT_ID="nba-props-platform"
REGION="us-west2"
SERVICE_ACCOUNT="mlb-monitoring-sa"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com"
MONITORING_REGISTRY="us-west2-docker.pkg.dev/${PROJECT_ID}/mlb-monitoring"
VALIDATORS_REGISTRY="us-west2-docker.pkg.dev/${PROJECT_ID}/mlb-validators"
VERSION="${VERSION:-v1.0.0}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Parse command line arguments
SKIP_SERVICE_ACCOUNT=false
SKIP_BUILD=false
SKIP_DEPLOY=false
SKIP_SCHEDULERS=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-service-account)
            SKIP_SERVICE_ACCOUNT=true
            shift
            ;;
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --skip-deploy)
            SKIP_DEPLOY=true
            shift
            ;;
        --skip-schedulers)
            SKIP_SCHEDULERS=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --version)
            VERSION="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--skip-service-account] [--skip-build] [--skip-deploy] [--skip-schedulers] [--dry-run] [--version VERSION]"
            exit 1
            ;;
    esac
done

log_info "Starting MLB Monitoring deployment..."
log_info "Project: $PROJECT_ID"
log_info "Region: $REGION"
log_info "Version: $VERSION"

if [ "$DRY_RUN" = true ]; then
    log_warn "DRY RUN MODE - No changes will be made"
fi

# Step 1: Setup Service Account
if [ "$SKIP_SERVICE_ACCOUNT" = false ]; then
    log_info "Setting up service account..."

    # Check if service account exists
    if gcloud iam service-accounts describe "$SERVICE_ACCOUNT_EMAIL" --project="$PROJECT_ID" &>/dev/null; then
        log_warn "Service account $SERVICE_ACCOUNT_EMAIL already exists, skipping creation"
    else
        log_info "Creating service account..."
        if [ "$DRY_RUN" = false ]; then
            gcloud iam service-accounts create "$SERVICE_ACCOUNT" \
                --display-name="MLB Monitoring Service Account" \
                --project="$PROJECT_ID"

            # Wait for service account to propagate
            log_info "Waiting for service account to propagate (60 seconds)..."
            sleep 60

            # Verify service account is accessible
            log_info "Verifying service account is ready..."
            for i in {1..10}; do
                if gcloud iam service-accounts describe "$SERVICE_ACCOUNT_EMAIL" --project="$PROJECT_ID" &>/dev/null; then
                    log_info "✓ Service account is ready"
                    break
                fi
                if [ $i -eq 10 ]; then
                    log_error "Service account not available after waiting"
                    exit 1
                fi
                log_info "  Waiting... (attempt $i/10)"
                sleep 10
            done
        fi
    fi

    # Grant permissions
    log_info "Granting IAM permissions..."
    ROLES=(
        "roles/bigquery.dataViewer"
        "roles/bigquery.jobUser"
        "roles/storage.objectViewer"
        "roles/storage.objectCreator"
        "roles/secretmanager.secretAccessor"
    )

    for role in "${ROLES[@]}"; do
        log_info "  - Granting $role"
        if [ "$DRY_RUN" = false ]; then
            gcloud projects add-iam-policy-binding "$PROJECT_ID" \
                --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
                --role="$role" \
                --quiet
        fi
    done
else
    log_warn "Skipping service account setup"
fi

# Step 2: Build and Push Docker Images
if [ "$SKIP_BUILD" = false ]; then
    log_info "Building and pushing Docker images..."

    # Monitoring images
    MONITORING_IMAGES=(
        "gap-detection"
        "freshness-checker"
        "prediction-coverage"
        "stall-detector"
    )

    for image in "${MONITORING_IMAGES[@]}"; do
        log_info "Building monitoring image: $image"
        IMAGE_TAG="${MONITORING_REGISTRY}/${image}:${VERSION}"
        IMAGE_LATEST="${MONITORING_REGISTRY}/${image}:latest"

        if [ "$DRY_RUN" = false ]; then
            docker build \
                -t "$IMAGE_TAG" \
                -t "$IMAGE_LATEST" \
                -f "deployment/dockerfiles/mlb/Dockerfile.${image}" \
                .

            log_info "Pushing $image..."
            docker push "$IMAGE_TAG"
            docker push "$IMAGE_LATEST"
        fi
    done

    # Validator images
    VALIDATOR_IMAGES=(
        "schedule-validator"
        "pitcher-props-validator"
        "prediction-coverage-validator"
    )

    for image in "${VALIDATOR_IMAGES[@]}"; do
        log_info "Building validator image: $image"
        IMAGE_TAG="${VALIDATORS_REGISTRY}/${image}:${VERSION}"
        IMAGE_LATEST="${VALIDATORS_REGISTRY}/${image}:latest"

        if [ "$DRY_RUN" = false ]; then
            docker build \
                -t "$IMAGE_TAG" \
                -t "$IMAGE_LATEST" \
                -f "deployment/dockerfiles/mlb/Dockerfile.${image}" \
                .

            log_info "Pushing $image..."
            docker push "$IMAGE_TAG"
            docker push "$IMAGE_LATEST"
        fi
    done
else
    log_warn "Skipping Docker image build"
fi

# Step 3: Deploy Cloud Run Jobs
if [ "$SKIP_DEPLOY" = false ]; then
    log_info "Deploying Cloud Run jobs..."

    # Deploy monitoring jobs
    MONITORING_JOBS=(
        "mlb-gap-detection"
        "mlb-freshness-checker"
        "mlb-prediction-coverage"
        "mlb-stall-detector"
    )

    for job in "${MONITORING_JOBS[@]}"; do
        log_info "Deploying monitoring job: $job"
        if [ "$DRY_RUN" = false ]; then
            gcloud run jobs replace \
                "deployment/cloud-run/mlb/monitoring/${job}.yaml" \
                --region="$REGION" \
                --quiet
        fi
    done

    # Deploy validator jobs
    VALIDATOR_JOBS=(
        "mlb-schedule-validator"
        "mlb-pitcher-props-validator"
        "mlb-prediction-coverage-validator"
    )

    for job in "${VALIDATOR_JOBS[@]}"; do
        log_info "Deploying validator job: $job"
        if [ "$DRY_RUN" = false ]; then
            gcloud run jobs replace \
                "deployment/cloud-run/mlb/validators/${job}.yaml" \
                --region="$REGION" \
                --quiet
        fi
    done

    # Test each job
    log_info "Testing deployed jobs..."
    for job in "${MONITORING_JOBS[@]}" "${VALIDATOR_JOBS[@]}"; do
        log_info "Testing job: $job"
        if [ "$DRY_RUN" = false ]; then
            if gcloud run jobs execute "$job" --region="$REGION" --wait --quiet; then
                log_info "  ✓ $job executed successfully"
            else
                log_error "  ✗ $job failed to execute"
            fi
        fi
    done
else
    log_warn "Skipping Cloud Run job deployment"
fi

# Step 4: Setup Cloud Schedulers
if [ "$SKIP_SCHEDULERS" = false ]; then
    log_info "Setting up Cloud Schedulers..."

    # Monitoring schedulers
    declare -A MONITORING_SCHEDULERS=(
        ["mlb-gap-detection-daily"]="0 13 * * *|America/New_York|mlb-gap-detection"
        ["mlb-freshness-checker-hourly"]="0 11-5/2 * 4-10 *|UTC|mlb-freshness-checker"
        ["mlb-prediction-coverage-pregame"]="0 22 * 4-10 *|UTC|mlb-prediction-coverage"
        ["mlb-prediction-coverage-postgame"]="0 7 * 4-10 *|UTC|mlb-prediction-coverage"
        ["mlb-stall-detector-hourly"]="0 11-5 * 4-10 *|UTC|mlb-stall-detector"
    )

    for scheduler_name in "${!MONITORING_SCHEDULERS[@]}"; do
        IFS='|' read -r schedule timezone job_name <<< "${MONITORING_SCHEDULERS[$scheduler_name]}"
        log_info "Creating scheduler: $scheduler_name"

        JOB_URI="https://us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${job_name}:run"

        if [ "$DRY_RUN" = false ]; then
            # Delete if exists
            gcloud scheduler jobs delete "$scheduler_name" \
                --location="$REGION" \
                --quiet 2>/dev/null || true

            # Create new
            gcloud scheduler jobs create http "$scheduler_name" \
                --location="$REGION" \
                --schedule="$schedule" \
                --time-zone="$timezone" \
                --uri="$JOB_URI" \
                --http-method=POST \
                --oauth-service-account-email="$SERVICE_ACCOUNT_EMAIL" \
                --quiet
        fi
    done

    # Validator schedulers
    declare -A VALIDATOR_SCHEDULERS=(
        ["mlb-schedule-validator-daily"]="0 11 * * *|America/New_York|mlb-schedule-validator"
        ["mlb-pitcher-props-validator-4hourly"]="0 10,14,18,22,2,6 * 4-10 *|UTC|mlb-pitcher-props-validator"
        ["mlb-prediction-coverage-validator-pregame"]="0 22 * 4-10 *|UTC|mlb-prediction-coverage-validator"
        ["mlb-prediction-coverage-validator-postgame"]="0 7 * 4-10 *|UTC|mlb-prediction-coverage-validator"
    )

    for scheduler_name in "${!VALIDATOR_SCHEDULERS[@]}"; do
        IFS='|' read -r schedule timezone job_name <<< "${VALIDATOR_SCHEDULERS[$scheduler_name]}"
        log_info "Creating scheduler: $scheduler_name"

        JOB_URI="https://us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${job_name}:run"

        if [ "$DRY_RUN" = false ]; then
            # Delete if exists
            gcloud scheduler jobs delete "$scheduler_name" \
                --location="$REGION" \
                --quiet 2>/dev/null || true

            # Create new
            gcloud scheduler jobs create http "$scheduler_name" \
                --location="$REGION" \
                --schedule="$schedule" \
                --time-zone="$timezone" \
                --uri="$JOB_URI" \
                --http-method=POST \
                --oauth-service-account-email="$SERVICE_ACCOUNT_EMAIL" \
                --quiet
        fi
    done
else
    log_warn "Skipping Cloud Scheduler setup"
fi

# Summary
log_info ""
log_info "═══════════════════════════════════════════════════════════"
log_info "  MLB Monitoring Deployment Complete!"
log_info "═══════════════════════════════════════════════════════════"
log_info ""
log_info "Deployed Components:"
log_info "  - 4 Monitoring Jobs (gap-detection, freshness-checker, prediction-coverage, stall-detector)"
log_info "  - 3 Validator Jobs (schedule, pitcher-props, prediction-coverage)"
log_info "  - 9 Cloud Schedulers (5 monitoring + 4 validators)"
log_info ""
log_info "Next Steps:"
log_info "  1. Monitor job executions in Cloud Console"
log_info "  2. Check #mlb-alerts Slack channel for alerts"
log_info "  3. Review logs: gcloud logging read 'resource.type=cloud_run_job'"
log_info "  4. Test with Spring Training data before Opening Day"
log_info ""
log_info "Useful Commands:"
log_info "  - List jobs: gcloud run jobs list --region=$REGION | grep mlb-"
log_info "  - List schedulers: gcloud scheduler jobs list --location=$REGION | grep mlb-"
log_info "  - Test job: gcloud run jobs execute <job-name> --region=$REGION --wait"
log_info "  - View logs: gcloud logging read 'resource.labels.job_name=<job-name>' --limit=50"
log_info ""

if [ "$DRY_RUN" = true ]; then
    log_warn "This was a DRY RUN - no actual changes were made"
    log_warn "Run without --dry-run to deploy"
fi
