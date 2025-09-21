#!/bin/bash
# FILE: backfill/nbac_referee_assignments/deploy.sh

# Deploy NBA Referee Assignments Backfill Job

set -e

echo "Deploying NBA Referee Assignments Backfill Job..."

# Use standardized scrapers backfill deployment script
./bin/scrapers/deploy/deploy_scrapers_backfill_job.sh backfill/nbac_referee_assignments/job-config.env

echo "Deployment complete!"
echo ""
echo "Test Commands:"
echo "  # Dry run:"
echo "  gcloud run jobs execute nba-referee-assignments-backfill --args=--dry-run,--limit=5 --region=us-west2"
echo ""
echo "  # Small test:"
echo "  gcloud run jobs execute nba-referee-assignments-backfill --args=--limit=10 --region=us-west2"
echo ""
echo "  # Single season:"
echo "  gcloud run jobs execute nba-referee-assignments-backfill --args=--seasons=2023 --region=us-west2"
echo ""
echo "  # Full backfill:"
echo "  gcloud run jobs execute nba-referee-assignments-backfill --region=us-west2"