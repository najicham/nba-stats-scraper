#!/bin/bash
# FILE: analytics_backfill/player_game_summary/deploy.sh

# Deploy Player Game Summary Analytics Processor Backfill Job

set -e

echo "Deploying Player Game Summary Analytics Processor Backfill Job..."

# Use standardized analytics processors backfill deployment script
./bin/analytics/deploy/deploy_analytics_processor_backfill.sh player_game_summary

echo "Deployment complete!"
echo ""
echo "Test Commands (Day-by-Day Processing):"
echo "  # Dry run (check data availability):"
echo "  gcloud run jobs execute player-game-summary-analytics-backfill --args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Small test (3 days):"
echo "  gcloud run jobs execute player-game-summary-analytics-backfill --args=--start-date=2024-01-01,--end-date=2024-01-03 --region=us-west2"
echo ""
echo "  # Weekly processing:"
echo "  gcloud run jobs execute player-game-summary-analytics-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Monthly processing (January 2024):"
echo "  gcloud run jobs execute player-game-summary-analytics-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2"
echo ""
echo "  # Large range processing (Q1 2024):"
echo "  gcloud run jobs execute player-game-summary-analytics-backfill --args=--start-date=2024-01-01,--end-date=2024-03-31 --region=us-west2"
echo ""
echo "  # Full historical backfill (processes day-by-day automatically):"
echo "  gcloud run jobs execute player-game-summary-analytics-backfill --args=--start-date=2021-10-01,--end-date=2024-12-31 --region=us-west2"
echo ""
echo "Monitor logs:"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""
echo "Notes:"
echo "  • This processor uses day-by-day processing to avoid BigQuery size limits"
echo "  • Large date ranges are automatically processed one day at a time for optimal performance"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo "  • For comma-separated values, use custom delimiter: --args=\"^|^--param=val1,val2|--other=val\""
echo ""
echo "Validate results:"
echo "  ./bin/analytics/validation/validate_analytics_data.sh"