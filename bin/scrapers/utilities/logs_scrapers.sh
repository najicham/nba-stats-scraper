#!/bin/bash
# bin/utilities/logs_scrapers.sh
# View scraper logs
echo "📋 NBA Scraper Logs"
echo "==================="
gcloud run services logs read nba-scrapers --region ${REGION:-us-west2} --limit 20 || echo "Service not found or gcloud not configured"
