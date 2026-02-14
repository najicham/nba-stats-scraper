#!/usr/bin/env bash
# fix_all_iam.sh — Discover and fix missing IAM bindings (Session 242)
#
# Checks all Pub/Sub push subscription targets and Cloud Scheduler HTTP targets
# for roles/run.invoker IAM bindings. Fixes any missing bindings.
#
# Root cause: gcloud functions deploy with Eventarc can wipe IAM on the
# underlying Cloud Run service. Redeploys don't always preserve bindings.
#
# Usage:
#   ./bin/infrastructure/fix_all_iam.sh           # Check and fix
#   ./bin/infrastructure/fix_all_iam.sh --dry-run # Check only, don't fix

set -euo pipefail

PROJECT="nba-props-platform"
REGION="us-west2"
SA="serviceAccount:756957797294-compute@developer.gserviceaccount.com"
DRY_RUN=false

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
  echo "=== DRY RUN MODE — will check but not fix ==="
fi

CHECKED=0
FIXED=0
ALREADY_OK=0
SKIPPED=0
FAILED=0

# Track checked services to avoid duplicates
declare -A SEEN_SERVICES

extract_service_name() {
  local url="$1"
  # Format 1: https://SERVICE-f7p3g7f6ya-wl.a.run.app/...
  if [[ "$url" =~ https://([a-zA-Z0-9][-a-zA-Z0-9]*)-f7p3g7f6ya-wl\.a\.run\.app ]]; then
    echo "${BASH_REMATCH[1]}"
    return
  fi
  # Format 2: https://SERVICE-756957797294.us-west2.run.app/...
  if [[ "$url" =~ https://([a-zA-Z0-9][-a-zA-Z0-9]*)-[0-9]+\.us-west2\.run\.app ]]; then
    echo "${BASH_REMATCH[1]}"
    return
  fi
  # No match (e.g., cloudfunctions.net URLs, Cloud Run Jobs URLs)
  echo ""
}

check_and_fix_iam() {
  local service_name="$1"
  local source="$2"

  # Skip duplicates
  if [[ -n "${SEEN_SERVICES[$service_name]:-}" ]]; then
    return
  fi
  SEEN_SERVICES[$service_name]=1
  CHECKED=$((CHECKED + 1))

  # Get IAM policy for the Cloud Run service
  local policy
  policy=$(gcloud run services get-iam-policy "$service_name" \
    --region="$REGION" --project="$PROJECT" --format=json 2>/dev/null || echo "ERROR")

  if [[ "$policy" == "ERROR" ]]; then
    echo "  SKIP $service_name — service not found (source: $source)"
    SKIPPED=$((SKIPPED + 1))
    return
  fi

  # Check if roles/run.invoker is bound to the compute SA
  if echo "$policy" | grep -q "roles/run.invoker"; then
    if echo "$policy" | grep -q "756957797294-compute"; then
      echo "  OK   $service_name (source: $source)"
      ALREADY_OK=$((ALREADY_OK + 1))
      return
    fi
  fi

  # Missing — fix it
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "  MISSING $service_name — would fix (source: $source)"
    FIXED=$((FIXED + 1))
  else
    echo "  FIXING $service_name (source: $source)..."
    if gcloud run services add-iam-policy-binding "$service_name" \
      --region="$REGION" --member="$SA" --role=roles/run.invoker \
      --project="$PROJECT" >/dev/null 2>&1; then
      echo "  FIXED $service_name"
      FIXED=$((FIXED + 1))
    else
      echo "  FAILED to fix $service_name"
      FAILED=$((FAILED + 1))
    fi
  fi
}

echo ""
echo "=== Checking Pub/Sub Push Subscription Targets ==="
echo ""

# Get all Pub/Sub subscriptions with push endpoints (JSON for reliable parsing)
while read -r line; do
  sub_name=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('name',''))" 2>/dev/null)
  push_endpoint=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); pc=d.get('pushConfig',{}); print(pc.get('pushEndpoint',''))" 2>/dev/null)
  [[ -z "$push_endpoint" ]] && continue

  service_name=$(extract_service_name "$push_endpoint")
  if [[ -n "$service_name" ]]; then
    check_and_fix_iam "$service_name" "pubsub:${sub_name##*/}"
  fi
done < <(gcloud pubsub subscriptions list --project="$PROJECT" --format=json 2>/dev/null | python3 -c "
import sys, json
for item in json.load(sys.stdin):
    print(json.dumps(item))
" 2>/dev/null)

echo ""
echo "=== Checking Cloud Scheduler HTTP Targets ==="
echo ""

# Get all scheduler jobs with HTTP targets (JSON for reliable parsing)
while read -r line; do
  job_name=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('name',''))" 2>/dev/null)
  uri=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); ht=d.get('httpTarget',{}); print(ht.get('uri',''))" 2>/dev/null)
  [[ -z "$uri" ]] && continue

  service_name=$(extract_service_name "$uri")
  if [[ -n "$service_name" ]]; then
    check_and_fix_iam "$service_name" "scheduler:${job_name##*/}"
  fi
done < <(gcloud scheduler jobs list --location="$REGION" --project="$PROJECT" --format=json 2>/dev/null | python3 -c "
import sys, json
for item in json.load(sys.stdin):
    print(json.dumps(item))
" 2>/dev/null)

echo ""
echo "=== Summary ==="
echo "Checked: $CHECKED"
echo "Already OK: $ALREADY_OK"
echo "Skipped (not found): $SKIPPED"
if [[ "$DRY_RUN" == "true" ]]; then
  echo "Would fix: $FIXED"
else
  echo "Fixed: $FIXED"
fi
echo "Failed: $FAILED"

if [[ $FIXED -gt 0 && "$DRY_RUN" == "false" ]]; then
  echo ""
  echo "Fixed $FIXED IAM bindings. Verify with: ./bin/infrastructure/fix_all_iam.sh --dry-run"
fi

if [[ $FAILED -gt 0 ]]; then
  exit 1
fi
