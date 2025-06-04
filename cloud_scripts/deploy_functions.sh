#!/usr/bin/env bash
# Deploy all Python scrapers that changed since the last push to origin/main
# using Option A for secrets: fetch from Secret Manager at deploy time.

set -euo pipefail

PROJECT_ID=$(gcloud config get-value project)
REGION=${REGION:-us-west2}
RUNTIME="python312"

# 1) Read the secret from Secret Manager (ODDS_API_KEY)
SECRET_VALUE=$(gcloud secrets versions access latest --secret=ODDS_API_KEY)

# ✏️  Map “Cloud Function name → folder with its code”
declare -A FUNCTIONS=(
  [scrape_players]="scrapers/players"
  [scrape_props]="scrapers/props"
  [scrape_odds_team_players]="scrapers/odds_api_team_players"
  [scrape_oddsapi_something_else]="scrapers/another_odds_function"
)

for FUNC in "${!FUNCTIONS[@]}"; do
  DIR="${FUNCTIONS[$FUNC]}"

  # Skip if that dir is unchanged => saves Cloud Build minutes/time
  if git diff --quiet origin/main -- "$DIR"; then
    echo "🟡 $FUNC unchanged – skipping"
    continue
  fi

  echo "🚀 Deploying $FUNC from $DIR"

  # Default is no extra env vars
  EXTRA_ENV=""

  # If the function name contains 'oddsapi' (or 'odds_api'), set the env var
  if [[ "$FUNC" == *"oddsa"* ]]; then
    EXTRA_ENV="--set-env-vars ODDS_API_KEY=$SECRET_VALUE"
  fi

  gcloud functions deploy "$FUNC" \
    --gen2 \
    --runtime "$RUNTIME" \
    --source="$DIR" \
    --entry-point gcf_entry \
    --trigger-http \
    --allow-unauthenticated \
    --region "$REGION" \
    $EXTRA_ENV

done
