#!/usr/bin/env bash
# Create–or–update Cloud Scheduler jobs for each function.

set -euo pipefail
PROJECT_ID=$(gcloud config get-value project)
REGION=${REGION:-us-west2}

# Map “job name → <function> <cron schedule>”
declare -A JOBS=(
  [daily-players]="scrape_players 0 6 * * *"
  [daily-props]="scrape_props   30 6 * * *"
)

for JOB in "${!JOBS[@]}"; do
  IFS=' ' read -r FUNC CRON_MIN CRON_HR CRON_DOM CRON_MON CRON_DOW <<<"${JOBS[$JOB]}"
  CRON="$CRON_MIN $CRON_HR $CRON_DOM $CRON_MON $CRON_DOW"
  URL="https://${REGION}-${PROJECT_ID}.cloudfunctions.net/${FUNC}"

  if gcloud scheduler jobs describe "$JOB" --location="$REGION" >/dev/null 2>&1; then
    echo "✏️  Updating job $JOB → $CRON"
    gcloud scheduler jobs update http "$JOB" \
      --schedule="$CRON" \
      --uri="$URL"
  else
    echo "➕ Creating job $JOB → $CRON"
    gcloud scheduler jobs create http "$JOB" \
      --schedule="$CRON" \
      --uri="$URL" \
      --http-method=GET
  fi
done
