#!/bin/bash
# FILE: processor_backfill/odds_game_lines/deploy.sh

# Deploy Odds Game Lines Processor Backfill Job

set -e

echo "Deploying Odds Game Lines Processor Backfill Job..."

# Use standardized processors backfill deployment script
./bin/processors/deploy/deploy_processor_backfill_job.sh processor_backfill/odds_game_lines/job-config.env

echo "Deployment complete!"
echo ""
echo "Test Commands:"
echo "  # Dry run:"
echo "  gcloud run jobs execute odds-game-lines-processor-backfill --args=--dry-run,--limit=5 --region=us-west2"
echo ""
echo "  # Small test:"
echo "  gcloud run jobs execute odds-game-lines-processor-backfill --args=--limit=10 --region=us-west2"
echo ""
echo "  # Process sample data (DET@BOS):"
echo "  gcloud run jobs execute odds-game-lines-processor-backfill --args=--start-date=2022-11-09,--end-date=2022-11-09,--limit=5 --region=us-west2"
echo ""
echo "  # Full backfill:"
echo "  gcloud run jobs execute odds-game-lines-processor-backfill --region=us-west2"
echo ""
echo "Monitor logs:"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"