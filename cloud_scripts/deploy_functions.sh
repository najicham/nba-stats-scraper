#!/usr/bin/env bash
# Deploy all Python scrapers that changed since the last push to origin/main.

set -euo pipefail
PROJECT_ID=$(gcloud config get-value project)
REGION=${REGION:-us-west2}
RUNTIME="python312"

# ✏️  Map “Cloud Function name → folder with its code”
declare -A FUNCTIONS=(
  [scrape_players]="scrapers/players"
  [scrape_props]="scrapers/props"
  # add more here
)

for FUNC in "${!FUNCTIONS[@]}"; do
  DIR="${FUNCTIONS[$FUNC]}"

  # Skip if that dir is unchanged ➜ saves Cloud Build minutes
  if git diff --quiet origin/main -- "$DIR"; then
    echo "🟡 $FUNC unchanged – skipping"
    continue
  fi

  echo "🚀 Deploying $FUNC from $DIR"
  gcloud functions deploy "$FUNC" \
    --gen2 \
    --runtime "$RUNTIME" \
    --source="$DIR" \
    --entry-point "$FUNC" \
    --trigger-http \
    --allow-unauthenticated
done

