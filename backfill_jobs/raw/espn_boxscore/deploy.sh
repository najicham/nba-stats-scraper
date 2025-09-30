#!/bin/bash
# FILE: backfill_jobs/raw/espn_boxscore/deploy.sh

# Deploy ESPN Boxscore Processor Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying ESPN Boxscore Processor Backfill Job..."

# Use standardized raw processors backfill deployment script
./bin/raw/deploy/deploy_processor_backfill_job.sh espn_boxscore

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (check data availability):"
echo "  gcloud run jobs execute espn-boxscore-processor-backfill --args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Dry run with limit (check first 10 files):"
echo "  gcloud run jobs execute espn-boxscore-processor-backfill --args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-31,--limit=10 --region=us-west2"
echo ""
echo "  # Small test (3 days):"
echo "  gcloud run jobs execute espn-boxscore-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-03 --region=us-west2"
echo ""
echo "  # Small test with limit (3 days, max 5 files):"
echo "  gcloud run jobs execute espn-boxscore-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-03,--limit=5 --region=us-west2"
echo ""
echo "  # Weekly processing:"
echo "  gcloud run jobs execute espn-boxscore-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Monthly processing:"
echo "  gcloud run jobs execute espn-boxscore-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2"
echo ""
echo "  # Full historical backfill:"
echo "  gcloud run jobs execute espn-boxscore-processor-backfill --args=--start-date=2023-10-01,--end-date=2025-06-30 --region=us-west2"
echo ""
echo "  # Use defaults (processes full range from job-config.env):"
echo "  gcloud run jobs execute espn-boxscore-processor-backfill --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • Processes ESPN boxscore data from GCS to BigQuery (backup validation source)"
echo "  • Limited historical coverage starting 2023-24 season (October 2023)"
echo "  • Data sourced from gs://nba-scraped-data/espn/boxscores/"
echo "  • Used for validation and final checks, not primary data source"
echo "  • Each file contains one game's boxscore with player statistics"
echo "  • Job has 1-hour timeout with 4GB memory and 2 CPUs"
echo "  • Processing window: 5AM PT (early morning final check workflow)"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo "  • For comma-separated values, use custom delimiter: --args=\"^|^--param=val1,val2|--other=val\""
echo ""

print_section_header "Validate results"
echo "  # Check recent data in BigQuery"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_records, MIN(game_date) as earliest_date, MAX(game_date) as latest_date, COUNT(DISTINCT game_id) as unique_games FROM \\\`nba-props-platform.nba_raw.espn_boxscore\\\`\""

# Print final timing summary
print_deployment_summary