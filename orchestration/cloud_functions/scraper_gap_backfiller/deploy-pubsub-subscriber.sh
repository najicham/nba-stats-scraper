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

# Stage `orchestration.parameter_resolver` as a flat module. The real
# orchestration/__init__.py eagerly imports MasterWorkflowController etc.
# whose transitive deps aren't in requirements.txt, so we ship an EMPTY
# package init alongside just the file we need.
mkdir -p "${STAGE_DIR}/orchestration"
: > "${STAGE_DIR}/orchestration/__init__.py"
cp "${REPO_ROOT}/orchestration/parameter_resolver.py" "${STAGE_DIR}/orchestration/parameter_resolver.py"

# Ship the YAML config that ParameterResolver loads at startup.
# scraper_parameters.yaml is required; workflows.yaml is consulted by
# _validate_workflow_date_config (non-blocking but kills log noise).
mkdir -p "${STAGE_DIR}/config"
cp "${REPO_ROOT}/config/scraper_parameters.yaml" "${STAGE_DIR}/config/"
cp "${REPO_ROOT}/config/workflows.yaml" "${STAGE_DIR}/config/"

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

echo "==> Granting nba-scrapers invoker to gap-detector SA"
gcloud run services add-iam-policy-binding nba-scrapers \
  --region="${REGION}" --project="${PROJECT_ID}" \
  --member="serviceAccount:gap-detector@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.invoker" --quiet 2>&1 | tail -1

# NBAScheduleService (constructed by ParameterResolver) falls back to GCS for
# per-game iteration (gamebook_pdf, play_by_play, team_boxscore resolvers).
# Schedule JSON lives at gs://nba-scraped-data/nba-com/schedule/{season}/.
#
# TODO(over-scope): grant is bucket-wide because the bucket runs with
# fine-grained ACLs (not uniform bucket-level access). IAM conditions like
# `resource.name.startsWith(".../nba-com/schedule/")` require UBLA, which is
# a one-way migration affecting all consumers. Revisit when the team
# coordinates a UBLA migration for this bucket. For now: the only consumer
# code path that exercises GCS in this CF is the schedule fallback.
echo "==> Granting nba-scraped-data objectViewer to gap-detector SA (bucket-wide; UBLA needed for prefix scope)"
gcloud storage buckets add-iam-policy-binding gs://nba-scraped-data \
  --member="serviceAccount:gap-detector@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer" --project="${PROJECT_ID}" --quiet 2>&1 | tail -1

# CRITICAL: EventArc invokes the subscriber CF using the trigger's SA.
# Without this binding, every Pub/Sub message gets a 403 and the
# subscription accumulates undelivered messages. (Hit this 2026-05-10
# morning — 790 NBA rows incorrectly marked FAILED before this was fixed.)
echo "==> Granting backfill-pubsub-subscriber invoker to gap-detector SA"
gcloud run services add-iam-policy-binding "${FUNCTION_NAME}" \
  --region="${REGION}" --project="${PROJECT_ID}" \
  --member="serviceAccount:gap-detector@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.invoker" --quiet 2>&1 | tail -1

# Phase 3 + Phase 5 dispatch require X-API-Key from Secret Manager.
# Phase 6 publishes to nba-phase6-export-trigger (gap-detector SA already
# has roles/pubsub.publisher at the project level, so no topic-level
# binding is needed). Phase 4 is unauthenticated at the app layer.
echo "==> Granting secretAccessor for analytics-api-keys (Phase 3) + coordinator-api-key (Phase 5) to gap-detector SA"
for secret in analytics-api-keys coordinator-api-key; do
  gcloud secrets add-iam-policy-binding "${secret}" \
    --project="${PROJECT_ID}" \
    --member="serviceAccount:gap-detector@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor" --quiet 2>&1 | tail -1
done

# Phase 3 + Phase 5 services need to accept calls from gap-detector SA.
# Both currently allow allUsers as invoker (precedented), but bind
# run.invoker explicitly so future tightening of allUsers doesn't break
# the dispatch path silently.
for svc in nba-phase3-analytics-processors nba-phase4-precompute-processors prediction-coordinator; do
  echo "==> Granting ${svc} invoker to gap-detector SA"
  gcloud run services add-iam-policy-binding "${svc}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --member="serviceAccount:gap-detector@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/run.invoker" --quiet 2>&1 | tail -1
done

echo "==> Done."
