#!/bin/bash
# bin/monitoring/rebuild_canary_image.sh
#
# Rebuild + push the pipeline-canary Cloud Run job image, then update the job.
#
# WHY LOCAL `docker build` (not `gcloud builds submit`):
#   The repo-root .gcloudignore excludes bin/ from every `gcloud builds submit`
#   / `gcloud run deploy --source` upload. A `!bin/monitoring/` negation does
#   NOT rescue it — gcloud's git-mode file enumeration silently drops `!`
#   re-includes that live under an excluded directory (verified 2026-07-04 with
#   `gcloud meta list-files-for-upload`; the same negation works in a plain
#   filesystem-walk fixture, so it is a gcloud-in-a-git-repo quirk, not a
#   pattern typo). Dockerfile.canary does `COPY bin/monitoring/`, so a
#   gcloud-submitted build ships an image WITHOUT pipeline_canary_queries.py and
#   the job dies with "can't open file '/app/bin/monitoring/pipeline_canary_queries.py'".
#   A LOCAL docker build reads the real filesystem and ignores .gcloudignore, so
#   bin/monitoring is present. The sibling monitoring images (drift-alerter,
#   auto-cleanup) are built the same way and stay healthy for the same reason.
#
# Usage (run from repo root):
#   ./bin/monitoring/rebuild_canary_image.sh            # build + push + update job
#   ./bin/monitoring/rebuild_canary_image.sh --execute  # also run one execution
#
# NOTE: off-season the execution will EXIT 1 with "N canary failures" (0 picks /
# 0 predictions / missing models) — that is the canary correctly reporting the
# empty-data state, not an image defect. Keep the scheduler triggers PAUSED
# (nba-pipeline-canary-trigger, nba-pipeline-canary-routine-trigger) until the
# pipeline is producing picks at season open.

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
JOB_NAME="nba-pipeline-canary"
IMG="us-west2-docker.pkg.dev/${PROJECT_ID}/nba-props/pipeline-canary:latest"

# Must run from repo root so the build context contains bin/monitoring/ + shared/
if [[ ! -f bin/monitoring/Dockerfile.canary ]]; then
  echo "ERROR: run this from the repo root (bin/monitoring/Dockerfile.canary not found)" >&2
  exit 1
fi

echo "1. Building ${IMG} (local docker — reads real FS, bypasses .gcloudignore)..."
docker build -f bin/monitoring/Dockerfile.canary -t "${IMG}" .

echo "2. Sanity-check the entrypoint file is actually in the image..."
docker run --rm --entrypoint ls "${IMG}" -la /app/bin/monitoring/pipeline_canary_queries.py

echo "3. Pushing to Artifact Registry..."
docker push "${IMG}"

echo "4. Pointing the Cloud Run job at the freshly-pushed :latest digest..."
DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' "${IMG}")
gcloud run jobs update "${JOB_NAME}" \
  --region="${REGION}" --project="${PROJECT_ID}" \
  --image="${DIGEST}"

if [[ "${1:-}" == "--execute" ]]; then
  echo "5. Executing one run (off-season: expect EXIT 1 = empty-data canary failures)..."
  gcloud run jobs execute "${JOB_NAME}" --region="${REGION}" --project="${PROJECT_ID}" --wait || true
fi

echo "Done. Image: ${DIGEST}"
echo "Triggers must stay PAUSED off-season: nba-pipeline-canary-trigger, nba-pipeline-canary-routine-trigger"
