#!/bin/bash
# FILE: backfill_jobs/raw/nbac_gamebook/deploy.sh

# Deploy NBA.com Gamebook Processor Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying NBA.com Gamebook Processor Backfill Job..."

# Use standardized raw processors backfill deployment script
./bin/raw/deploy/deploy_processor_backfill_job.sh nbac_gamebook

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (check data availability):"
echo "  gcloud run jobs execute nbac-gamebook-processor-backfill --args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Dry run with date-range format (uses colon separator):"
echo "  gcloud run jobs execute nbac-gamebook-processor-backfill --args=\"^|^--dry-run|--date-range=2024-01-01:2024-01-07\" --region=us-west2"
echo ""
echo "  # Small test (3 days):"
echo "  gcloud run jobs execute nbac-gamebook-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-03 --region=us-west2"
echo ""
echo "  # Test with team filter (specific teams only):"
echo "  gcloud run jobs execute nbac-gamebook-processor-backfill --args=\"^|^--start-date=2024-01-01|--end-date=2024-01-07|--team-filter=BKN,PHX,CHA\" --region=us-west2"
echo ""
echo "  # Weekly processing:"
echo "  gcloud run jobs execute nbac-gamebook-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Monthly processing:"
echo "  gcloud run jobs execute nbac-gamebook-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2"
echo ""
echo "  # Season processing (2023-24 season):"
echo "  gcloud run jobs execute nbac-gamebook-processor-backfill --args=--start-date=2023-10-01,--end-date=2024-06-30 --region=us-west2"
echo ""
echo "  # Full historical backfill:"
echo "  gcloud run jobs execute nbac-gamebook-processor-backfill --args=--start-date=2021-10-01,--end-date=2025-06-30 --region=us-west2"
echo ""
echo "  # Use defaults (processes full range from job-config.env):"
echo "  gcloud run jobs execute nbac-gamebook-processor-backfill --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • Processes NBA.com gamebook data (box scores with DNP/inactive players)"
echo "  • Uses latest file per game code for most current data"
echo "  • Sequential processing with single processor instance for proper finalization"
echo "  • Job has 6-hour timeout with 8GB memory and 4 CPUs (extended for long runs)"
echo "  • Increased memory for name resolution caching (player/team lookups)"
echo "  • Data sourced from gs://nba-scraped-data/nba-com/gamebooks-data/"
echo "  • Historical coverage from 2021-22 season through current season"
echo "  • Supports team filtering for testing specific teams (e.g., --team-filter=BKN,PHX,CHA)"
echo "  • SPECIAL ARGS: Use pipe delimiter for comma-separated values:"
echo "    - Date range: --args=\"^|^--date-range=2024-01-01:2024-01-07\""
echo "    - Team filter: --args=\"^|^--team-filter=BKN,PHX,CHA\""
echo "  • Standard args use equals syntax (--param=value) with no spaces"
echo ""

print_section_header "Validate results"
echo "  # Check recent data in BigQuery"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_records, MIN(game_date) as earliest_date, MAX(game_date) as latest_date, COUNT(DISTINCT game_id) as unique_games, COUNT(DISTINCT player_id) as unique_players FROM \\\`nba-props-platform.nba_raw.nbac_gamebook\\\`\""

# Print final timing summary
print_deployment_summary