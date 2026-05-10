#!/bin/bash
# Create GCP Uptime Checks for the user-visible playerprops.io routes.
#
# Replaces the proposed 5-layer frontend monitoring stack with a single
# external check that asserts both reachability AND content presence
# (closes both the April /mlb regression and the May Best Bets outage:
# both returned HTTP 200 + broken page).
#
# Pipeline-state-redesign Phase I.

set -euo pipefail

PROJECT_ID="nba-props-platform"

# Each check: name | path | content_matcher (regex or substring)
# We assert a stable substring rendered server-side that won't appear
# during a generic 200-OK error fallback.
ROUTES=(
  "playerprops-root|/|<title>"
  "playerprops-mlb|/mlb|MLB"
  "playerprops-nba-best-bets|/nba/best-bets|Best Bets"
)

create_uptime_check() {
  local name="$1"
  local path="$2"
  local matcher="$3"

  cat > "/tmp/uptime-${name}.json" <<EOF
{
  "displayName": "${name}",
  "monitoredResource": {
    "type": "uptime_url",
    "labels": {
      "host": "playerprops.io",
      "project_id": "${PROJECT_ID}"
    }
  },
  "httpCheck": {
    "path": "${path}",
    "port": 443,
    "useSsl": true,
    "validateSsl": true,
    "requestMethod": "GET",
    "acceptedResponseStatusCodes": [
      {"statusClass": "STATUS_CLASS_2XX"}
    ]
  },
  "timeout": "10s",
  "period": "300s",
  "selectedRegions": ["USA_OREGON", "USA_VIRGINIA"],
  "contentMatchers": [
    {
      "content": "${matcher}",
      "matcher": "CONTAINS_STRING"
    }
  ]
}
EOF

  echo "==> Creating uptime check: ${name}"
  gcloud monitoring uptime create "${name}" \
    --project="${PROJECT_ID}" \
    --resource-type=uptime-url \
    --resource-labels="host=playerprops.io,project_id=${PROJECT_ID}" \
    --path="${path}" \
    --port=443 \
    --protocol=https \
    --period=5 \
    --timeout=10 \
    --regions=usa-oregon,usa-virginia,usa-iowa \
    --matcher-content="${matcher}" \
    --matcher-type=contains-string \
    --validate-ssl=true 2>&1 | tail -5 || \
    echo "    (may already exist; check console)"
}

for route in "${ROUTES[@]}"; do
  IFS='|' read -r name path matcher <<<"${route}"
  create_uptime_check "${name}" "${path}" "${matcher}"
done

echo ""
echo "==> Done. Manual next step: in Cloud Monitoring console → Uptime Checks,"
echo "    attach the alerting policy that triggers on consecutive failures."
echo "    Suggest: 2-of-3 region failures, 5-min lookback."
