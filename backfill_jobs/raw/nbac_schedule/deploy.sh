#!/bin/bash
# FILE: backfill_jobs/raw/nbac_schedule/deploy.sh

# Deploy NBA.com Schedule Processor Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying NBA.com Schedule Processor Backfill Job..."

# Use standardized raw processors backfill deployment script
./bin/raw/deploy/deploy_processor_backfill_job.sh nbac_schedule

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (check all seasons):"
echo "  gcloud run jobs execute nbac-schedule-processor-backfill --args=--dry-run --region=us-west2"
echo ""
echo "  # Dry run with limit:"
echo "  gcloud run jobs execute nbac-schedule-processor-backfill --args=--dry-run,--limit=2 --region=us-west2"
echo ""
echo "  # Process single season (2023-24):"
echo "  gcloud run jobs execute nbac-schedule-processor-backfill --args=--season=2023-24 --region=us-west2"
echo ""
echo "  # Process single season (2024-25):"
echo "  gcloud run jobs execute nbac-schedule-processor-backfill --args=--season=2024-25 --region=us-west2"
echo ""
echo "  # Process all available seasons (default behavior):"
echo "  gcloud run jobs execute nbac-schedule-processor-backfill --region=us-west2"
echo ""
echo "  # Process with limit (first N seasons):"
echo "  gcloud run jobs execute nbac-schedule-processor-backfill --args=--limit=3 --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • Processes NBA.com schedule data from GCS to BigQuery (season-based only)"
echo "  • Uses latest file per season (enhanced data from Sept 18, 2025+ has 15 analytical fields)"
echo "  • Data sourced from gs://nba-scraped-data/nba-com/schedule/{season}/"
echo "  • Available seasons: 2021-22, 2022-23, 2023-24, 2024-25, 2025-26"
echo "  • Season format uses dash: --season=2023-24 (NOT 2023 or 2023-2024)"
echo "  • If no season specified, processes all available seasons"
echo "  • Job has 30-minute timeout with 4GB memory and 2 CPUs (sufficient for all seasons)"
echo "  • Enhanced data includes: game metadata, team info, broadcast details, arena capacity, etc."
echo "  • Each season file contains full season schedule (~1,230 regular season games + playoffs)"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo ""

print_section_header "Validate results"
echo "  # Check recent data in BigQuery"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_games, MIN(game_date_est) as earliest_date, MAX(game_date_est) as latest_date, COUNT(DISTINCT season_year) as unique_seasons, COUNT(DISTINCT game_id) as unique_games FROM \\\`nba-props-platform.nba_raw.nbac_schedule\\\`\""
echo ""
echo "  # Check games by season:"
echo "  bq query --use_legacy_sql=false \"SELECT season_year, COUNT(*) as game_count FROM \\\`nba-props-platform.nba_raw.nbac_schedule\\\` GROUP BY season_year ORDER BY season_year DESC\""

# Print final timing summary
print_deployment_summary