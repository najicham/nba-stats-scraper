#!/bin/bash
# FILE: backfill_jobs/raw/nbac_team_boxscore/deploy.sh
# Deploy NBA.com Team Boxscore Processor Backfill Job

set -e

echo "Deploying NBA.com Team Boxscore Processor Backfill Job..."
echo ""

# Use standardized deployment script for raw processors
./bin/raw/deploy/deploy_processor_backfill_job.sh nbac_team_boxscore

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📋 Test Commands:"
echo ""
echo "  # Dry run (recommended first test):"
echo "  gcloud run jobs execute nbac-team-boxscore-processor-backfill \\"
echo "    --args=--dry-run,--limit=10 \\"
echo "    --region=us-west2"
echo ""
echo "  # Small test (5 games):"
echo "  gcloud run jobs execute nbac-team-boxscore-processor-backfill \\"
echo "    --args=--limit=5 \\"
echo "    --region=us-west2"
echo ""
echo "  # Single day:"
echo "  gcloud run jobs execute nbac-team-boxscore-processor-backfill \\"
echo "    --args=--start-date=2024-11-20,--end-date=2024-11-20 \\"
echo "    --region=us-west2"
echo ""
echo "  # Week range:"
echo "  gcloud run jobs execute nbac-team-boxscore-processor-backfill \\"
echo "    --args=--start-date=2024-11-01,--end-date=2024-11-07 \\"
echo "    --region=us-west2"
echo ""
echo "  # Month range:"
echo "  gcloud run jobs execute nbac-team-boxscore-processor-backfill \\"
echo "    --args=--start-date=2024-11-01,--end-date=2024-11-30 \\"
echo "    --region=us-west2"
echo ""
echo "📊 Monitor execution:"
echo "  gcloud run jobs executions list --job=nbac-team-boxscore-processor-backfill --region=us-west2"
echo ""
echo "📜 View logs:"
echo "  gcloud beta run jobs executions logs read [EXECUTION-ID] --region=us-west2"
