#!/bin/bash
# FILE: analytics_backfill/team_offense_game_summary/deploy.sh

# Deploy Team Offense Game Summary Analytics Processor Backfill Job

set -e

echo "Deploying Team Offense Game Summary Analytics Processor Backfill Job..."

# Use standardized analytics processors backfill deployment script
./bin/analytics/deploy/deploy_analytics_processor_backfill.sh team_offense_game_summary

echo "Deployment complete!"
echo ""
echo "⚠️  DEPENDENCY: Requires player_game_summary to be populated first!"
echo ""
echo "Test Commands:"
echo "  # Dry run:"
echo "  gcloud run jobs execute team-offense-game-summary-analytics-backfill --args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Small test (1 week):"
echo "  gcloud run jobs execute team-offense-game-summary-analytics-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Monthly processing:"
echo "  gcloud run jobs execute team-offense-game-summary-analytics-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2"
echo ""
echo "  # Full historical backfill (larger chunks since it's aggregation):"
echo "  gcloud run jobs execute team-offense-game-summary-analytics-backfill --args=--start-date=2021-10-01,--end-date=2024-12-31,--chunk-days=60 --region=us-west2"
echo ""
echo "Monitor logs:"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""
echo "Check results:"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as team_offense_records FROM \\\`nba-props-platform.nba_analytics.team_offense_game_summary\\\`\""
