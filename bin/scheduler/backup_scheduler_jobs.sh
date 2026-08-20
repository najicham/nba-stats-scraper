#!/usr/bin/env bash
# Snapshot every Cloud Scheduler job to a version-controlled JSON file.
#
# WHY THIS EXISTS
# ---------------
# On 2026-07-03 an off-season purge deleted 94 scheduler jobs. The recovery plan
# (docs/02-operations/scheduler-restore-manifest-2026.md) named exactly one
# source of truth for their configs:
#
#   gs://nba-bigquery-backups/scheduler-jobs-backup/scheduler_jobs_backup_2026-07-03.json
#
# That bucket carries a 30-day delete lifecycle rule. The file aged out around
# 2026-08-02 and is gone. Nobody would have found out until the restore was
# attempted in September, four weeks before opening night.
#
# So: snapshots live in git, which has no TTL and no lifecycle rule. A copy is
# also written to GCS for convenience, but git is the authority.
#
# Usage:
#   ./bin/scheduler/backup_scheduler_jobs.sh            # write today's snapshot
#   ./bin/scheduler/backup_scheduler_jobs.sh --gcs      # also upload to GCS
#
# Commit the resulting file. It is small (~200KB) and diffs readably, so the
# history doubles as an audit trail of who changed which schedule when.
set -euo pipefail

PROJECT="${PROJECT:-nba-props-platform}"
LOCATION="${LOCATION:-us-west2}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="${REPO_ROOT}/ops/scheduler-snapshots"
STAMP="$(date -u +%Y-%m-%d)"
OUT="${OUT_DIR}/scheduler-jobs-${STAMP}.json"

mkdir -p "${OUT_DIR}"

echo "Exporting Cloud Scheduler jobs (${PROJECT}/${LOCATION})..."
gcloud scheduler jobs list \
  --location="${LOCATION}" \
  --project="${PROJECT}" \
  --format=json > "${OUT}.tmp"

COUNT="$(python3 -c "import json,sys;print(len(json.load(open('${OUT}.tmp'))))")"
if [ "${COUNT}" -eq 0 ]; then
  echo "ERROR: exported 0 jobs — refusing to overwrite a good snapshot with an empty one." >&2
  rm -f "${OUT}.tmp"
  exit 1
fi
mv "${OUT}.tmp" "${OUT}"

# Keep a stable 'latest' pointer so tooling does not have to guess the date.
cp "${OUT}" "${OUT_DIR}/scheduler-jobs-latest.json"

ENABLED="$(python3 -c "import json;d=json.load(open('${OUT}'));print(sum(1 for j in d if j.get('state')=='ENABLED'))")"
PAUSED="$(python3 -c "import json;d=json.load(open('${OUT}'));print(sum(1 for j in d if j.get('state')=='PAUSED'))")"
echo "Wrote ${OUT}"
echo "  ${COUNT} jobs  (${ENABLED} ENABLED, ${PAUSED} PAUSED)"

if [ "${1:-}" = "--gcs" ]; then
  # Deliberately NOT gs://nba-bigquery-backups — that bucket deletes at 30 days,
  # which is what destroyed the 2026-07-03 backup.
  DEST="gs://nba-props-status/scheduler-snapshots/scheduler-jobs-${STAMP}.json"
  gsutil cp "${OUT}" "${DEST}"
  echo "  copied to ${DEST}"
fi

echo
echo "Commit this file. git is the authority; GCS lifecycle rules are not."
