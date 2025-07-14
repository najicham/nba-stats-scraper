#!/bin/bash
echo "=== Cloud Run Status ==="
gcloud run services describe nba-scrapers --region us-west2 --format="table(
  metadata.name,
  status.conditions[0].status,
  status.url
)"

echo -e "\n=== Recent Logs ==="
gcloud run services logs read nba-scrapers --region us-west2 --limit 10

echo -e "\n=== Recent GCS Files ==="
gsutil ls -l gs://nba-analytics-raw-data/oddsapi/historical-events/ | tail -5
