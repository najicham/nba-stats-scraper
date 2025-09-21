#!/bin/bash
# FILE: backfill/odds_api_lines/deploy.sh
# Deploy NBA Odds API Game Lines Backfill Job

set -e

echo "Deploying NBA Odds API Game Lines Backfill Job..."

# Use standardized scrapers backfill deployment script
./bin/scrapers/deploy/deploy_scrapers_backfill_job.sh backfill/odds_api_lines/job-config.env

echo "Deployment complete!"
echo ""
echo "Test Commands:"
echo "  # Dry run (see what would be processed):"
echo "  gcloud run jobs execute nba-odds-api-lines-backfill --args=--dry-run,--limit=5 --region=us-west2"
echo ""
echo "  # Small test (process 10 dates):"
echo "  gcloud run jobs execute nba-odds-api-lines-backfill --args=--limit=10 --region=us-west2"
echo ""
echo "  # Single season test:"
echo "  gcloud run jobs execute nba-odds-api-lines-backfill --args=--seasons=2023,--limit=20 --region=us-west2"
echo ""
echo "  # Full backfill (all 4 seasons):"
echo "  gcloud run jobs execute nba-odds-api-lines-backfill --region=us-west2"
echo ""
echo "Monitor:"
echo "  # List executions:"
echo "  gcloud run jobs executions list --job=nba-odds-api-lines-backfill --region=us-west2 --limit=5"