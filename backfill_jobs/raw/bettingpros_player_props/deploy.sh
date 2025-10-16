#!/bin/bash
# FILE: backfill_jobs/raw/bettingpros_player_props/deploy.sh

# Deploy BettingPros Player Props Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying BettingPros Player Props Backfill Job..."

# Use standardized raw processors backfill deployment script
./bin/raw/deploy/deploy_processor_backfill_job.sh bettingpros_player_props

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Small test (3 days):"
echo "  gcloud run jobs execute bettingpros-player-props-backfill --args=--start-date=2024-01-01,--end-date=2024-01-03 --region=us-west2"
echo ""
echo "  # Weekly processing:"
echo "  gcloud run jobs execute bettingpros-player-props-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Monthly processing:"
echo "  gcloud run jobs execute bettingpros-player-props-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2"
echo ""
echo "  # Full historical backfill:"
echo "  gcloud run jobs execute bettingpros-player-props-backfill --args=--start-date=2021-10-01,--end-date=2024-12-31 --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Validate results"
echo "  # Check BettingPros player props data"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_records, MIN(date) as earliest_date, MAX(date) as latest_date, COUNT(DISTINCT player_name) as unique_players FROM \\\`nba-props-platform.nba_raw.bettingpros_player_props\\\`\""

# Print final timing summary
print_deployment_summary