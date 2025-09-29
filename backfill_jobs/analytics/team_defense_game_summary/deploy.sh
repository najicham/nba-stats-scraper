#!/bin/bash
# FILE: analytics_backfill/team_defense_game_summary/deploy.sh

# Deploy Team Defense Game Summary Analytics Processor Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying Team Defense Game Summary Analytics Processor Backfill Job..."

# Use standardized analytics processors backfill deployment script
./bin/analytics/deploy/deploy_analytics_processor_backfill.sh team_defense_game_summary

echo "Deployment complete!"
echo ""
echo "⚠️  DEPENDENCY: Requires team_offense_game_summary to be populated first!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run:"
echo "  gcloud run jobs execute team-defense-game-summary-analytics-backfill --args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Small test (1 week):"
echo "  gcloud run jobs execute team-defense-game-summary-analytics-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Monthly processing:"
echo "  gcloud run jobs execute team-defense-game-summary-analytics-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2"
echo ""
echo "  # Full historical backfill (larger chunks since it's aggregation):"
echo "  gcloud run jobs execute team-defense-game-summary-analytics-backfill --args=--start-date=2021-10-01,--end-date=2024-12-31,--chunk-days=60 --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Check results"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as team_defense_records FROM \\\`nba-props-platform.nba_analytics.team_defense_game_summary\\\`\""

# Print final timing summary
print_deployment_summary