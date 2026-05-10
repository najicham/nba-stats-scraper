#!/bin/bash
# Deploy backfill-pubsub-subscriber Cloud Function (Gen2).
#
# Subscribes to projects/nba-props-platform/topics/nba-backfill-trigger.
# Shares source code with scraper_gap_backfiller (different entry point).
# Pipeline-state-redesign Phase F.
#
# Usage:
#   ./deploy-pubsub-subscriber.sh

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
FUNCTION_NAME="backfill-pubsub-subscriber"
TOPIC_NAME="nba-backfill-trigger"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SOURCE_DIR}/../../.." && pwd)"

echo "==> Stage deployment package"
STAGE_DIR="$(mktemp -d)"
trap "rm -rf ${STAGE_DIR}" EXIT

cp "${SOURCE_DIR}/main.py" "${STAGE_DIR}/"
cp "${SOURCE_DIR}/requirements.txt" "${STAGE_DIR}/"

# Bring shared/ for parameter resolver + BQ client pool.
rsync -aL "${REPO_ROOT}/shared/" "${STAGE_DIR}/shared/"
find "${STAGE_DIR}" -type d -exec touch {}/__init__.py \;

echo "==> Deploy Cloud Function (entry point: pubsub_subscriber)"
gcloud functions deploy "${FUNCTION_NAME}" \
  --gen2 --runtime=python311 --region="${REGION}" --project="${PROJECT_ID}" \
  --source="${STAGE_DIR}" \
  --entry-point=pubsub_subscriber \
  --trigger-topic="${TOPIC_NAME}" \
  --memory=1Gi --timeout=540s --max-instances=10 \
  --service-account="gap-detector@${PROJECT_ID}.iam.gserviceaccount.com" \
  --update-env-vars="GCP_PROJECT_ID=${PROJECT_ID}"

echo "==> Done."
echo ""
echo "Note: subscriber runs as gap-detector SA (already has BQ + Pub/Sub access)."
echo "      For scraper invocation, the SA also needs run.invoker on nba-scrapers."
echo ""
echo "Granting nba-scrapers invoker..."
gcloud run services add-iam-policy-binding nba-scrapers \
  --region="${REGION}" --project="${PROJECT_ID}" \
  --member="serviceAccount:gap-detector@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.invoker" --quiet 2>&1 | tail -1
