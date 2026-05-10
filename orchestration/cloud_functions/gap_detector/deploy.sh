#!/bin/bash
# Deploy gap_detector Cloud Function (Gen2) + scheduler + Pub/Sub topic.

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
FUNCTION_NAME="gap-detector"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SOURCE_DIR}/../../.." && pwd)"
SCHEDULER_NAME="gap-detector-30min"
TOPIC_NAME="nba-backfill-trigger"

MODE="${1:-all}"

ensure_topic() {
  if ! gcloud pubsub topics describe "${TOPIC_NAME}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud pubsub topics create "${TOPIC_NAME}" --project="${PROJECT_ID}"
    echo "    Created topic ${TOPIC_NAME}"
  else
    echo "    Topic ${TOPIC_NAME} already exists"
  fi
}

deploy_function() {
  STAGE_DIR="$(mktemp -d)"
  trap "rm -rf ${STAGE_DIR}" EXIT
  cp "${SOURCE_DIR}/main.py" "${STAGE_DIR}/"
  cp "${SOURCE_DIR}/requirements.txt" "${STAGE_DIR}/"
  cp "${SOURCE_DIR}/__init__.py" "${STAGE_DIR}/" 2>/dev/null || true
  rsync -aL "${REPO_ROOT}/shared/" "${STAGE_DIR}/shared/"
  find "${STAGE_DIR}" -type d -exec touch {}/__init__.py \;

  gcloud functions deploy "${FUNCTION_NAME}" \
    --gen2 --runtime=python311 --region="${REGION}" --project="${PROJECT_ID}" \
    --source="${STAGE_DIR}" --entry-point=main \
    --trigger-http --no-allow-unauthenticated \
    --memory=512Mi --timeout=300s --max-instances=4 \
    --service-account="gap-detector@${PROJECT_ID}.iam.gserviceaccount.com" \
    --update-env-vars="GCP_PROJECT_ID=${PROJECT_ID},BACKFILL_TOPIC=${TOPIC_NAME},MAX_BACKFILL_ATTEMPTS=3,MAX_PUBLISHES_PER_RUN=50"
}

create_scheduler() {
  CF_URL=$(gcloud functions describe "${FUNCTION_NAME}" --gen2 --region="${REGION}" \
    --project="${PROJECT_ID}" --format='value(serviceConfig.uri)')

  if gcloud scheduler jobs describe "${SCHEDULER_NAME}" \
       --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud scheduler jobs update http "${SCHEDULER_NAME}" \
      --location="${REGION}" --project="${PROJECT_ID}" \
      --schedule="15,45 * * * *" --time-zone="America/New_York" \
      --uri="${CF_URL}/" --http-method=GET \
      --oidc-service-account-email="756957797294-compute@developer.gserviceaccount.com" \
      --oidc-token-audience="${CF_URL}/" \
      --description="Publishes backfill messages for stale EXPECTED rows. Phase E."
  else
    gcloud scheduler jobs create http "${SCHEDULER_NAME}" \
      --location="${REGION}" --project="${PROJECT_ID}" \
      --schedule="15,45 * * * *" --time-zone="America/New_York" \
      --uri="${CF_URL}/" --http-method=GET \
      --oidc-service-account-email="756957797294-compute@developer.gserviceaccount.com" \
      --oidc-token-audience="${CF_URL}/" \
      --description="Publishes backfill messages for stale EXPECTED rows. Phase E."
  fi
}

case "${MODE}" in
  --topic-only)     ensure_topic ;;
  --cf-only)        deploy_function ;;
  --scheduler-only) create_scheduler ;;
  all)              ensure_topic; deploy_function; create_scheduler ;;
  *)                echo "unknown mode: ${MODE}"; exit 2 ;;
esac

echo "==> gap_detector deploy complete."
