#!/bin/bash
# FILE: processor_backfill/nbac_referee/deploy.sh

# Deploy NBA Referee Processor Backfill Job

set -e

echo "Deploying NBA Referee Processor Backfill Job..."

# Use standardized processors backfill deployment script
./bin/processors/deploy/deploy_processor_backfill_job.sh processor_backfill/nbac_referee/job-config.env

echo "Deployment complete!"
echo ""
echo "Test Commands:"
echo "  # Dry run:"
echo "  gcloud run jobs execute nbac-referee-processor-backfill --args=--dry-run,--limit=5 --region=us-west2"
echo ""
echo "  # Small test:"
echo "  gcloud run jobs execute nbac-referee-processor-backfill --args=--limit=10 --region=us-west2"
echo ""
echo "  # Date range:"
echo "  gcloud run jobs execute nbac-referee-processor-backfill --args=--start-date=2025-01-01,--end-date=2025-01-07 --region=us-west2"
echo ""
echo "  # Full backfill:"
echo "  gcloud run jobs execute nbac-referee-processor-backfill --region=us-west2"
echo ""
echo "Monitor logs:"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"