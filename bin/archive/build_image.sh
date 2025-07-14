#!/usr/bin/env bash
set -euo pipefail

PROJECT=${PROJECT:-"nba-props-platform"}
REGION="us-west2"
TAG="${1:-dev}"                     # ./bin/build_image.sh 2025-07-11

IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/pipeline/scrapers:${TAG}"

# Build & push
gcloud builds submit --tag "${IMAGE}" --file Dockerfile.scraper .

echo "Built & pushed ${IMAGE}"
echo "${IMAGE}" > .last_image      # convenience for deploy script
