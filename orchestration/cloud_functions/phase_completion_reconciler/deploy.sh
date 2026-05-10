#!/bin/bash
# Deploy phase_completion_reconciler Cloud Function (Gen2) + scheduler.

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
FUNCTION_NAME="phase-completion-reconciler"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SOURCE_DIR}/../../.." && pwd)"
SCHEDULER_NAME="phase-completion-reconciler-30min"

MODE="${1:-all}"

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
    --memory=1Gi --timeout=540s --max-instances=4 \
    --service-account="phase-completion-reconciler@${PROJECT_ID}.iam.gserviceaccount.com" \
    --update-env-vars="GCP_PROJECT_ID=${PROJECT_ID}"
}

create_scheduler() {
  CF_URL=$(gcloud functions describe "${FUNCTION_NAME}" --gen2 --region="${REGION}" \
    --project="${PROJECT_ID}" --format='value(serviceConfig.uri)')

  if gcloud scheduler jobs describe "${SCHEDULER_NAME}" \
       --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud scheduler jobs update http "${SCHEDULER_NAME}" \
      --location="${REGION}" --project="${PROJECT_ID}" \
      --schedule="*/30 * * * *" --time-zone="America/New_York" \
      --uri="${CF_URL}/" --http-method=GET \
      --oidc-service-account-email="756957797294-compute@developer.gserviceaccount.com" \
      --oidc-token-audience="${CF_URL}/" \
      --description="Reconciles EXPECTED rows in expected_outputs every 30 min. Phase D."
  else
    gcloud scheduler jobs create http "${SCHEDULER_NAME}" \
      --location="${REGION}" --project="${PROJECT_ID}" \
      --schedule="*/30 * * * *" --time-zone="America/New_York" \
      --uri="${CF_URL}/" --http-method=GET \
      --oidc-service-account-email="756957797294-compute@developer.gserviceaccount.com" \
      --oidc-token-audience="${CF_URL}/" \
      --description="Reconciles EXPECTED rows in expected_outputs every 30 min. Phase D."
  fi
}

case "${MODE}" in
  --cf-only) deploy_function ;;
  --scheduler-only) create_scheduler ;;
  all) deploy_function; create_scheduler ;;
  *) echo "unknown mode: ${MODE}"; exit 2 ;;
esac

echo "==> phase_completion_reconciler deploy complete."
