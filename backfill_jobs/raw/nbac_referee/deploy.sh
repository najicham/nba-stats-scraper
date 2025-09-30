#!/bin/bash
# FILE: backfill_jobs/raw/nbac_referee/deploy.sh

# Deploy NBA.com Referee Processor Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying NBA.com Referee Processor Backfill Job..."

# Use standardized raw processors backfill deployment script
./bin/raw/deploy/deploy_processor_backfill_job.sh nbac_referee

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (check data availability):"
echo "  gcloud run jobs execute nbac-referee-processor-backfill --args=--dry-run,--start-date=2025-01-01,--end-date=2025-01-07 --region=us-west2"
echo ""
echo "  # Dry run with limit (check first 10 files):"
echo "  gcloud run jobs execute nbac-referee-processor-backfill --args=--dry-run,--limit=10 --region=us-west2"
echo ""
echo "  # Small test (3 days):"
echo "  gcloud run jobs execute nbac-referee-processor-backfill --args=--start-date=2025-01-01,--end-date=2025-01-03 --region=us-west2"
echo ""
echo "  # Small test with limit (first 5 files):"
echo "  gcloud run jobs execute nbac-referee-processor-backfill --args=--limit=5 --region=us-west2"
echo ""
echo "  # Weekly processing:"
echo "  gcloud run jobs execute nbac-referee-processor-backfill --args=--start-date=2025-01-01,--end-date=2025-01-07 --region=us-west2"
echo ""
echo "  # Monthly processing:"
echo "  gcloud run jobs execute nbac-referee-processor-backfill --args=--start-date=2025-01-01,--end-date=2025-01-31 --region=us-west2"
echo ""
echo "  # Use defaults (processes last 30 days to today):"
echo "  gcloud run jobs execute nbac-referee-processor-backfill --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • Processes NBA.com referee assignments data from GCS to BigQuery"
echo "  • Two data types: game assignments (officials per game) and replay center staff"
echo "  • Multiple path patterns checked for data availability"
echo "  • Uses latest file per date if multiple scrapes exist"
echo "  • Job has 1-hour timeout with 4GB memory and 2 CPUs"
echo "  • Default behavior: processes last 30 days to today if no dates specified"
echo "  • Path patterns: nba-com/referee-assignments/, nba-com/referee-game-line-history/"
echo "  • Supports success, partial_success, and validation_failed statuses"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo "  • For comma-separated values, use custom delimiter: --args=\"^|^--param=val1,val2|--other=val\""
echo ""

print_section_header "Validate results"
echo "  # Check recent data in BigQuery"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_records, MIN(assignment_date) as earliest_date, MAX(assignment_date) as latest_date, COUNT(DISTINCT game_id) as unique_games FROM \\\`nba-props-platform.nba_raw.nbac_referee_assignments\\\`\""
echo ""
echo "  # Check daily coverage"
echo "  bq query --use_legacy_sql=false \"SELECT assignment_date, COUNT(DISTINCT game_id) as games_count, COUNT(*) as total_assignments FROM \\\`nba-props-platform.nba_raw.nbac_referee_assignments\\\` GROUP BY assignment_date ORDER BY assignment_date DESC LIMIT 10\""
echo ""
echo "  # Check referee assignment counts (should be 3 officials per game typically)"
echo "  bq query --use_legacy_sql=false \"SELECT game_id, COUNT(*) as officials_count FROM \\\`nba-props-platform.nba_raw.nbac_referee_assignments\\\` WHERE assignment_date = CURRENT_DATE() GROUP BY game_id\""

# Print final timing summary
print_deployment_summary