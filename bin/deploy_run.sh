#!/usr/bin/env bash
set -euo pipefail
PROJECT=${PROJECT:-"nba-props-platform"}
REGION="us-west2"
SERVICE="${1:-odds-player-props}"           # name passed as first arg
MODULE="${2:-scrapers.oddsapi.oddsa_player_props}"  # python -m path

IMAGE=$(cat .last_image) || { echo "Build image first"; exit 1; }

gcloud run deploy "${SERVICE}" \
  --image "${IMAGE}" \
  --command "python" \
  --args "-m,${MODULE}" \
  --service-account "workflow-sa@${PROJECT}.iam.gserviceaccount.com" \
  --region "${REGION}" \
  --min-instances 0 --max-instances 1
