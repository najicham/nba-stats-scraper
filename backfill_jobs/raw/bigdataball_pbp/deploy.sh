#!/bin/bash
# FILE: backfill_jobs/raw/bigdataball_pbp/deploy.sh

# Deploy Big Data Ball Play-by-Play Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying Big Data Ball Play-by-Play Backfill Job..."

# Use standardized raw processors backfill deployment script
./bin/raw/deploy/deploy_processor_backfill_job.sh bigdataball_pbp

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Small test (3 days):"
echo "  gcloud run jobs execute bigdataball-pbp-backfill --args=--start-date=2024-01-01,--end-date=2024-01-03 --region=us-west2"
echo ""
echo "  # Weekly processing:"
echo "  gcloud run jobs execute bigdataball-pbp-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Monthly processing:"
echo "  gcloud run jobs execute bigdataball-pbp-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2"
echo ""
echo "  # Full historical backfill:"
echo "  gcloud run jobs execute bigdataball-pbp-backfill --args=--start-date=2021-10-01,--end-date=2024-12-31 --region=us-west2"
echo ""

print_section_header "Important Notes"
echo "  • Big Data Ball enhanced play-by-play is released 2 hours after each game"
echo "  • Data is typically only available for recent seasons"
echo "  • Contains advanced tracking data not available in standard play-by-play"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Validate results"
echo "  # Check Big Data Ball play-by-play data"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_records, MIN(game_date) as earliest_date, MAX(game_date) as latest_date, COUNT(DISTINCT game_id) as unique_games FROM \\\`nba-props-platform.nba_raw.bigdataball_pbp\\\`\""

# Print final timing summary
print_deployment_summary