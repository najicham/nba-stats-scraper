#!/bin/bash
# Create / update the nba-pipeline-health Cloud Monitoring dashboard.
#
# Pipeline-state-redesign Phase L.

set -euo pipefail

PROJECT_ID="nba-props-platform"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DASH_FILE="${SCRIPT_DIR}/nba-pipeline-health.json"

# Look up by displayName (the only stable id; Cloud Monitoring dashboards use
# system-assigned numeric IDs internally).
EXISTING=$(gcloud monitoring dashboards list \
  --project="${PROJECT_ID}" \
  --filter='displayName="NBA Pipeline Health"' \
  --format='value(name)' | head -1 || true)

if [ -n "${EXISTING:-}" ]; then
  echo "==> Updating existing dashboard ${EXISTING}"
  gcloud monitoring dashboards update "${EXISTING}" \
    --project="${PROJECT_ID}" \
    --config-from-file="${DASH_FILE}"
else
  echo "==> Creating new dashboard"
  gcloud monitoring dashboards create \
    --project="${PROJECT_ID}" \
    --config-from-file="${DASH_FILE}"
fi

echo "==> Done. View at:"
echo "    https://console.cloud.google.com/monitoring/dashboards?project=${PROJECT_ID}"
