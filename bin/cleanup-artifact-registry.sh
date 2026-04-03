#!/bin/bash
# Artifact Registry cleanup — keeps last N tags per image, deletes older ones.
# Session 509: Added to prevent AR from regrowing to 111 GB after manual cleanup.
#
# Usage:
#   ./bin/cleanup-artifact-registry.sh              # Dry run (default, safe)
#   ./bin/cleanup-artifact-registry.sh --execute    # Actually delete
#
# Schedule: Run weekly via Cloud Scheduler (Sunday 11 PM ET) to prevent regrowth.

set -euo pipefail

PROJECT="nba-props-platform"
REGION="us-west2"
REPOS=("nba-props" "cloud-run-source-deploy" "gcf-artifacts")
KEEP=5
DRY_RUN=true

if [[ "${1:-}" == "--execute" ]]; then
  DRY_RUN=false
  echo "=== EXECUTE MODE: will delete old image tags ==="
else
  echo "=== DRY RUN MODE: showing what would be deleted (pass --execute to delete) ==="
fi

TOTAL_DELETED=0

for REPO in "${REPOS[@]}"; do
  REGISTRY="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}"
  echo ""
  echo "--- Repository: ${REGISTRY} ---"

  # Get all images in this repo
  IMAGES=$(gcloud artifacts docker images list "${REGISTRY}" \
    --include-tags \
    --format="value(IMAGE)" \
    --sort-by="~CREATE_TIME" 2>/dev/null | sort -u)

  if [[ -z "$IMAGES" ]]; then
    echo "  (no images found or access denied)"
    continue
  fi

  while IFS= read -r IMAGE; do
    # Get all digests for this image with their tags, sorted newest first
    # Format: DIGEST<tab>TAGS<tab>CREATE_TIME
    ROWS=$(gcloud artifacts docker images list "${REGISTRY}" \
      --include-tags \
      --filter="IMAGE=${IMAGE}" \
      --format="value(version,TAGS,CREATE_TIME)" \
      --sort-by="~CREATE_TIME" 2>/dev/null | head -50)

    ROW_COUNT=$(echo "$ROWS" | grep -c . || true)

    if [[ "$ROW_COUNT" -le "$KEEP" ]]; then
      continue
    fi

    # Rows to delete = everything beyond KEEP newest
    TO_DELETE=$(echo "$ROWS" | tail -n "+$((KEEP + 1))")

    while IFS=$'\t' read -r DIGEST TAGS _REST; do
      [[ -z "$DIGEST" ]] && continue

      # Expand comma-separated tags and delete each individually, skipping 'latest'
      IFS=',' read -ra TAG_LIST <<< "$TAGS"
      for TAG in "${TAG_LIST[@]}"; do
        TAG=$(echo "$TAG" | tr -d ' ')
        [[ -z "$TAG" ]] && continue
        [[ "$TAG" == "latest" ]] && continue  # Never delete :latest

        if $DRY_RUN; then
          echo "  [DRY-RUN] Would delete: ${IMAGE}:${TAG}"
        else
          echo "  Deleting: ${IMAGE}:${TAG}"
          gcloud artifacts docker images delete \
            "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${IMAGE}:${TAG}" \
            --quiet 2>/dev/null && TOTAL_DELETED=$((TOTAL_DELETED + 1)) || true
        fi
      done

      # If no named tags (untagged digest), delete by digest
      if [[ -z "$TAGS" ]]; then
        if $DRY_RUN; then
          echo "  [DRY-RUN] Would delete digest: ${IMAGE}@${DIGEST}"
        else
          echo "  Deleting digest: ${IMAGE}@${DIGEST}"
          gcloud artifacts docker images delete \
            "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${IMAGE}@${DIGEST}" \
            --quiet 2>/dev/null && TOTAL_DELETED=$((TOTAL_DELETED + 1)) || true
        fi
      fi
    done <<< "$TO_DELETE"
  done <<< "$IMAGES"
done

echo ""
if $DRY_RUN; then
  echo "=== Dry run complete. Re-run with --execute to delete. ==="
else
  echo "=== Done. Deleted ${TOTAL_DELETED} image tags. ==="
fi
