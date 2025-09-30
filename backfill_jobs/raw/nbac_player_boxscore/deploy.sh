#!/bin/bash
# FILE: backfill_jobs/raw/nbac_player_boxscore/deploy.sh

# Deploy NBA.com Player Boxscore Processor Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying NBA.com Player Boxscore Processor Backfill Job..."

# Use standardized raw processors backfill deployment script
./bin/raw/deploy/deploy_processor_backfill_job.sh nbac_player_boxscore

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (check data availability):"
echo "  gcloud run jobs execute nbac-player-boxscore-processor-backfill --args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Dry run with limit (check first 10 files):"
echo "  gcloud run jobs execute nbac-player-boxscore-processor-backfill --args=--dry-run,--limit=10 --region=us-west2"
echo ""
echo "  # Small test (3 days):"
echo "  gcloud run jobs execute nbac-player-boxscore-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-03 --region=us-west2"
echo ""
echo "  # Small test with limit (max 50 files):"
echo "  gcloud run jobs execute nbac-player-boxscore-processor-backfill --args=--limit=50 --region=us-west2"
echo ""
echo "  # Single season processing (2023-24 season):"
echo "  gcloud run jobs execute nbac-player-boxscore-processor-backfill --args=--season=2023 --region=us-west2"
echo ""
echo "  # Multiple seasons (requires pipe delimiter for comma-separated values):"
echo "  gcloud run jobs execute nbac-player-boxscore-processor-backfill --args=\"^|^--seasons=2021,2022,2023\" --region=us-west2"
echo ""
echo "  # Multiple seasons with limit:"
echo "  gcloud run jobs execute nbac-player-boxscore-processor-backfill --args=\"^|^--seasons=2021,2022,2023|--limit=100\" --region=us-west2"
echo ""
echo "  # Weekly processing:"
echo "  gcloud run jobs execute nbac-player-boxscore-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Monthly processing:"
echo "  gcloud run jobs execute nbac-player-boxscore-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2"
echo ""
echo "  # Full historical backfill:"
echo "  gcloud run jobs execute nbac-player-boxscore-processor-backfill --args=--start-date=2021-10-01,--end-date=2025-06-30 --region=us-west2"
echo ""
echo "  # Use defaults (processes full range from job-config.env):"
echo "  gcloud run jobs execute nbac-player-boxscore-processor-backfill --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • Processes NBA.com player boxscore data from GCS to BigQuery"
echo "  • Uses latest file per date (current-state data with most recent updates)"
echo "  • Data sourced from gs://nba-scraped-data/nba-com/player-boxscores/"
echo "  • Historical coverage from 2021-22 season through current season"
echo "  • Job has 2-hour timeout with 4GB memory and 2 CPUs"
echo "  • Season-based processing available:"
echo "    - Single season: --season=2023 (for 2023-24 season)"
echo "    - Multiple seasons: --seasons=2021,2022,2023 (requires pipe delimiter)"
echo "  • Available seasons: 2021-22, 2022-23, 2023-24, 2024-25"
echo "  • SPECIAL ARGS: Use pipe delimiter for comma-separated seasons:"
echo "    --args=\"^|^--seasons=2021,2022,2023|--limit=100\""
echo "  • Standard args use equals syntax (--param=value) with no spaces"
echo ""

print_section_header "Validate results"
echo "  # Check recent data in BigQuery"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_records, MIN(game_date) as earliest_date, MAX(game_date) as latest_date, COUNT(DISTINCT game_id) as unique_games, COUNT(DISTINCT player_id) as unique_players FROM \\\`nba-props-platform.nba_raw.nbac_player_boxscore\\\`\""

# Print final timing summary
print_deployment_summary