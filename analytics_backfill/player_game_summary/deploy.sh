#!/bin/bash
# FILE: analytics_backfill/player_game_summary/deploy.sh

# Deploy Player Game Summary Analytics Processor Backfill Job

set -e

echo "Deploying Player Game Summary Analytics Processor Backfill Job..."

# Use standardized analytics processors backfill deployment script
./bin/analytics/deploy/deploy_analytics_processor_backfill.sh player_game_summary

echo "Deployment complete!"
echo ""
echo "Test Commands:"
echo "  # Dry run:"
echo "  gcloud run jobs execute player-game-summary-analytics-backfill --args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Small test (1 week):"
echo "  gcloud run jobs execute player-game-summary-analytics-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Monthly processing:"
echo "  gcloud run jobs execute player-game-summary-analytics-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2"
echo ""
echo "  # Full historical backfill (chunked):"
echo "  gcloud run jobs execute player-game-summary-analytics-backfill --args=--start-date=2021-10-01,--end-date=2024-12-31,--chunk-days=30 --region=us-west2"
echo ""
echo "Monitor logs:"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""
echo "Validate results:"
echo "  ./bin/analytics/validation/validate_analytics_data.sh"
