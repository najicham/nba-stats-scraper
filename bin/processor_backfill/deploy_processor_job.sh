#!/bin/bash
# Generic deploy script for all processor backfill jobs
# Usage: ./deploy_processor_job.sh <processor_name>

set -e

# Check arguments
if [ $# -lt 1 ]; then
    echo "Usage: $0 <processor_name>"
    echo "Example: $0 br_roster_processor"
    exit 1
fi

PROCESSOR_NAME=$1
PROCESSOR_DIR="$(dirname "$0")/${PROCESSOR_NAME}"

# Check if processor directory exists
if [ ! -d "${PROCESSOR_DIR}" ]; then
    echo "Error: Processor directory not found: ${PROCESSOR_DIR}"
    exit 1
fi

# Check if job-config.env exists
if [ ! -f "${PROCESSOR_DIR}/job-config.env" ]; then
    echo "Error: job-config.env not found in ${PROCESSOR_DIR}"
    exit 1
fi

# Load configuration
echo "Loading configuration from ${PROCESSOR_DIR}/job-config.env"
source "${PROCESSOR_DIR}/job-config.env"

# Set defaults if not provided
JOB_NAME=${JOB_NAME:-"${PROCESSOR_NAME//_/-}-backfill"}
REGION=${REGION:-"us-west2"}
MEMORY=${MEMORY:-"2Gi"}
CPU=${CPU:-"1"}
TASK_TIMEOUT=${TASK_TIMEOUT:-"3600"}
MAX_RETRIES=${MAX_RETRIES:-"1"}
PARALLELISM=${PARALLELISM:-"1"}
TASK_COUNT=${TASK_COUNT:-"1"}

# Construct image name
IMAGE="gcr.io/${GCP_PROJECT_ID}/processor-backfill:${PROCESSOR_NAME}-$(date +%Y%m%d-%H%M%S)"
IMAGE_LATEST="gcr.io/${GCP_PROJECT_ID}/processor-backfill:${PROCESSOR_NAME}-latest"

echo "=========================================="
echo "Deploying Processor Backfill Job"
echo "=========================================="
echo "Processor: $PROCESSOR_NAME"
echo "Job Name: $JOB_NAME"
echo "Project: $GCP_PROJECT_ID"
echo "Region: $REGION"
echo "Image: $IMAGE"
echo "=========================================="

# Get the repository root (3 levels up from processor_backfill/deploy_processor_job.sh)
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
echo "Building from repository root: $REPO_ROOT"

# Build the container
echo ""
echo "Step 1: Building container..."
cd "$REPO_ROOT"

docker build \
  -f docker/processor.Dockerfile \
  --build-arg JOB_TYPE=processor_backfill \
  --build-arg JOB_NAME="${PROCESSOR_NAME}" \
  -t "${IMAGE}" \
  -t "${IMAGE_LATEST}" \
  .

# Push to GCR
echo ""
echo "Step 2: Pushing to Google Container Registry..."
docker push "${IMAGE}"
docker push "${IMAGE_LATEST}"

# Prepare environment variables
ENV_VARS=""
while IFS='=' read -r key value; do
    # Skip comments and empty lines
    [[ "$key" =~ ^#.*$ ]] && continue
    [[ -z "$key" ]] && continue
    
    # Skip export keyword
    key="${key#export }"
    
    # Remove quotes from value
    value="${value%\"}"
    value="${value#\"}"
    
    # Add to env vars (skip our script variables)
    if [[ "$key" != "JOB_NAME" && "$key" != "REGION" && "$key" != "MEMORY" && \
          "$key" != "CPU" && "$key" != "TASK_TIMEOUT" && "$key" != "MAX_RETRIES" && \
          "$key" != "PARALLELISM" && "$key" != "TASK_COUNT" && -n "$value" ]]; then
        ENV_VARS="${ENV_VARS} --set-env-vars ${key}=${value}"
    fi
done < "${PROCESSOR_DIR}/job-config.env"

# Get service account
SERVICE_ACCOUNT=${SERVICE_ACCOUNT:-"scrapers@${GCP_PROJECT_ID}.iam.gserviceaccount.com"}

# Create or update Cloud Run job
echo ""
echo "Step 3: Deploying to Cloud Run Jobs..."

# Check if job exists
if gcloud run jobs describe ${JOB_NAME} --region ${REGION} --project ${GCP_PROJECT_ID} &>/dev/null; then
    echo "Updating existing job: ${JOB_NAME}"
    gcloud run jobs update ${JOB_NAME} \
        --image "${IMAGE}" \
        --region ${REGION} \
        --project ${GCP_PROJECT_ID} \
        --memory ${MEMORY} \
        --cpu ${CPU} \
        --task-timeout ${TASK_TIMEOUT} \
        --max-retries ${MAX_RETRIES} \
        --parallelism ${PARALLELISM} \
        --task-count ${TASK_COUNT} \
        ${ENV_VARS}
else
    echo "Creating new job: ${JOB_NAME}"
    gcloud run jobs create ${JOB_NAME} \
        --image "${IMAGE}" \
        --region ${REGION} \
        --project ${GCP_PROJECT_ID} \
        --service-account ${SERVICE_ACCOUNT} \
        --memory ${MEMORY} \
        --cpu ${CPU} \
        --task-timeout ${TASK_TIMEOUT} \
        --max-retries ${MAX_RETRIES} \
        --parallelism ${PARALLELISM} \
        --task-count ${TASK_COUNT} \
        ${ENV_VARS}
fi

echo ""
echo "=========================================="
echo "✓ Deployment complete!"
echo "=========================================="
echo ""
echo "To run the job:"
echo "  gcloud run jobs execute ${JOB_NAME} --region ${REGION}"
echo ""
echo "To run with arguments:"
echo "  gcloud run jobs execute ${JOB_NAME} --region ${REGION} \\"
echo "    --args='--season','2023','--teams','LAL','GSW'"
echo ""
echo "To view logs:"
echo "  gcloud logging read \"resource.type=cloud_run_job AND resource.labels.job_name=${JOB_NAME}\" \\"
echo "    --limit 50 --project ${GCP_PROJECT_ID} --format json"
