#!/bin/bash
set -euo pipefail

export GCP_PROJECT_ID=nba-props-platform

echo "[$(date)] Starting BDL injuries pipeline..."

# Scrape
python scrapers/balldontlie/bdl_injuries.py --group prod

# Process
TODAY=$(date +%Y-%m-%d)
GCS_FILE=$(gsutil ls "gs://nba-scraped-data/ball-dont-lie/injuries/${TODAY}/" | tail -1)
python scripts/test_bdl_injuries_processor.py --gcs-file "${GCS_FILE}" --load

# Validate
./scripts/validate-bdl-injuries realtime

echo "[$(date)] Pipeline complete!"
