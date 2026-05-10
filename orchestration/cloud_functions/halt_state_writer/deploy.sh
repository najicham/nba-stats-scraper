#!/bin/bash
# Deploy halt_state_writer Cloud Function (Gen2) + scheduler.
#
# Usage:
#   ./deploy.sh                  # full deploy: BQ table + CF + scheduler
#   ./deploy.sh --table-only     # create/refresh BQ table only
#   ./deploy.sh --cf-only        # CF deploy only
#   ./deploy.sh --scheduler-only # scheduler create/update only

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
FUNCTION_NAME="halt-state-writer"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SOURCE_DIR}/../../.." && pwd)"
SCHEMA_FILE="${REPO_ROOT}/schemas/bigquery/nba_orchestration/halt_state.sql"
SCHEDULER_NAME="halt-state-writer-daily"
SLACK_WEBHOOK_SECRET="slack-webhook-url"

MODE="${1:-all}"

create_table() {
  echo "==> Ensuring BQ table nba_orchestration.halt_state exists..."
  bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false < "${SCHEMA_FILE}"
  echo "    Table ready."
}

deploy_function() {
  echo "==> Deploying Cloud Function ${FUNCTION_NAME}..."

  # Stage shared/ files alongside main.py because CF runtime is flat.
  STAGE_DIR="$(mktemp -d)"
  trap "rm -rf ${STAGE_DIR}" EXIT

  cp "${SOURCE_DIR}/main.py" "${STAGE_DIR}/"
  cp "${SOURCE_DIR}/requirements.txt" "${STAGE_DIR}/"
  cp "${SOURCE_DIR}/__init__.py" "${STAGE_DIR}/" 2>/dev/null || true

  # Copy shared deps (bigquery_pool, gcp_config) so the CF can resolve imports.
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
    --timeout=300s \
    --max-instances=4 \
    --service-account="halt-state-writer@${PROJECT_ID}.iam.gserviceaccount.com" \
    --set-secrets="SLACK_WEBHOOK_URL_ALERTS=${SLACK_WEBHOOK_SECRET}:latest" \
    --update-env-vars="GCP_PROJECT_ID=${PROJECT_ID}"

  echo "    Function deployed."
}

create_scheduler() {
  echo "==> Ensuring scheduler ${SCHEDULER_NAME} exists..."

  CF_URL=$(gcloud functions describe "${FUNCTION_NAME}" \
    --gen2 --region="${REGION}" --project="${PROJECT_ID}" \
    --format='value(serviceConfig.uri)')

  if [ -z "${CF_URL}" ]; then
    echo "    ERROR: could not resolve CF URL for ${FUNCTION_NAME}" >&2
    exit 1
  fi

  # Check existence
  if gcloud scheduler jobs describe "${SCHEDULER_NAME}" \
       --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "    Updating existing scheduler..."
    gcloud scheduler jobs update http "${SCHEDULER_NAME}" \
      --location="${REGION}" --project="${PROJECT_ID}" \
      --schedule="0 5 * * *" \
      --time-zone="America/New_York" \
      --uri="${CF_URL}/?sport=all" \
      --http-method=GET \
      --oidc-service-account-email="756957797294-compute@developer.gserviceaccount.com" \
      --oidc-token-audience="${CF_URL}/" \
      --description="Daily halt_state writer for NBA + MLB. Pipeline-state-redesign Phase B."
  else
    echo "    Creating scheduler..."
    gcloud scheduler jobs create http "${SCHEDULER_NAME}" \
      --location="${REGION}" --project="${PROJECT_ID}" \
      --schedule="0 5 * * *" \
      --time-zone="America/New_York" \
      --uri="${CF_URL}/?sport=all" \
      --http-method=GET \
      --oidc-service-account-email="756957797294-compute@developer.gserviceaccount.com" \
      --oidc-token-audience="${CF_URL}/" \
      --description="Daily halt_state writer for NBA + MLB. Pipeline-state-redesign Phase B."
  fi
  echo "    Scheduler ready."
}

case "${MODE}" in
  --table-only)     create_table ;;
  --cf-only)        deploy_function ;;
  --scheduler-only) create_scheduler ;;
  all)              create_table; deploy_function; create_scheduler ;;
  *)                echo "unknown mode: ${MODE}"; exit 2 ;;
esac

echo "==> halt_state_writer deploy complete."
