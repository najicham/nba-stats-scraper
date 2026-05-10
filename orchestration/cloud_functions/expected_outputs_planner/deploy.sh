#!/bin/bash
# Deploy expected_outputs_planner Cloud Function (Gen2) + scheduler.
#
# Usage:
#   ./deploy.sh                  # full deploy (CF + scheduler)
#   ./deploy.sh --cf-only        # CF deploy only
#   ./deploy.sh --scheduler-only # scheduler create/update only
#   ./deploy.sh --bootstrap-history  # one-shot: seed 2025-26 season

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
FUNCTION_NAME="expected-outputs-planner"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SOURCE_DIR}/../../.." && pwd)"
SCHEDULER_NAME="expected-outputs-planner-nightly"

MODE="${1:-all}"

deploy_function() {
  echo "==> Deploying Cloud Function ${FUNCTION_NAME}..."

  STAGE_DIR="$(mktemp -d)"
  trap "rm -rf ${STAGE_DIR}" EXIT

  cp "${SOURCE_DIR}/main.py" "${STAGE_DIR}/"
  cp "${SOURCE_DIR}/requirements.txt" "${STAGE_DIR}/"
  cp "${SOURCE_DIR}/__init__.py" "${STAGE_DIR}/" 2>/dev/null || true

  rsync -aL "${REPO_ROOT}/shared/" "${STAGE_DIR}/shared/"
  find "${STAGE_DIR}" -type d -exec touch {}/__init__.py \;

  gcloud functions deploy "${FUNCTION_NAME}" \
    --gen2 \
    --runtime=python311 \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --source="${STAGE_DIR}" \
    --entry-point=main \
    --trigger-http \
    --no-allow-unauthenticated \
    --memory=512Mi \
    --timeout=540s \
    --max-instances=4 \
    --service-account="expected-outputs-planner@${PROJECT_ID}.iam.gserviceaccount.com" \
    --update-env-vars="GCP_PROJECT_ID=${PROJECT_ID}"
}

create_scheduler() {
  CF_URL=$(gcloud functions describe "${FUNCTION_NAME}" \
    --gen2 --region="${REGION}" --project="${PROJECT_ID}" \
    --format='value(serviceConfig.uri)')

  if [ -z "${CF_URL}" ]; then
    echo "ERROR: could not resolve CF URL" >&2; exit 1
  fi

  if gcloud scheduler jobs describe "${SCHEDULER_NAME}" \
       --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud scheduler jobs update http "${SCHEDULER_NAME}" \
      --location="${REGION}" --project="${PROJECT_ID}" \
      --schedule="0 4 * * *" \
      --time-zone="America/New_York" \
      --uri="${CF_URL}/?lookahead_days=14&sport=all" \
      --http-method=GET \
      --oidc-service-account-email="756957797294-compute@developer.gserviceaccount.com" \
      --oidc-token-audience="${CF_URL}/" \
      --description="Plans 14d of expected_outputs nightly. Pipeline-state-redesign Phase C."
  else
    gcloud scheduler jobs create http "${SCHEDULER_NAME}" \
      --location="${REGION}" --project="${PROJECT_ID}" \
      --schedule="0 4 * * *" \
      --time-zone="America/New_York" \
      --uri="${CF_URL}/?lookahead_days=14&sport=all" \
      --http-method=GET \
      --oidc-service-account-email="756957797294-compute@developer.gserviceaccount.com" \
      --oidc-token-audience="${CF_URL}/" \
      --description="Plans 14d of expected_outputs nightly. Pipeline-state-redesign Phase C."
  fi
}

bootstrap_history() {
  CF_URL=$(gcloud functions describe "${FUNCTION_NAME}" \
    --gen2 --region="${REGION}" --project="${PROJECT_ID}" \
    --format='value(serviceConfig.uri)')
  echo "==> Seeding 2025-26 season (2025-10-01 → today + 14d)..."
  curl -sS -X GET \
    -H "Authorization: Bearer $(gcloud auth print-identity-token --audiences=${CF_URL}/)" \
    "${CF_URL}/?history_seed_date=2025-10-01&lookahead_days=14&sport=all" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d, indent=2))"
}

case "${MODE}" in
  --cf-only)            deploy_function ;;
  --scheduler-only)     create_scheduler ;;
  --bootstrap-history)  bootstrap_history ;;
  all)                  deploy_function; create_scheduler ;;
  *)                    echo "unknown mode: ${MODE}"; exit 2 ;;
esac

echo "==> expected_outputs_planner deploy complete."
