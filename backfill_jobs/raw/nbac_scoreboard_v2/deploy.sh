#!/bin/bash
# FILE: backfill_jobs/raw/nbac_scoreboard_v2/deploy.sh

# Deploy NBA.com Scoreboard V2 Processor Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying NBA.com Scoreboard V2 Processor Backfill Job..."

# Use standardized raw processors backfill deployment script
./bin/raw/deploy/deploy_processor_backfill_job.sh nbac_scoreboard_v2

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # IMPORTANT: Dates are OPTIONAL - defaults to last 30 days if not specified"
echo ""
echo "  # Use defaults (last 30 days to today):"
echo "  gcloud run jobs execute nbac-scoreboard-v2-processor-backfill --region=us-west2"
echo ""
echo "  # Dry run with defaults (last 30 days):"
echo "  gcloud run jobs execute nbac-scoreboard-v2-processor-backfill --args=--dry-run --region=us-west2"
echo ""
echo "  # Dry run with limit (check first 10 files):"
echo "  gcloud run jobs execute nbac-scoreboard-v2-processor-backfill --args=--dry-run,--limit=10 --region=us-west2"
echo ""
echo "  # Small test with limit (process first 5 files from defaults):"
echo "  gcloud run jobs execute nbac-scoreboard-v2-processor-backfill --args=--limit=5 --region=us-west2"
echo ""
echo "  # Date range with dry run:"
echo "  gcloud run jobs execute nbac-scoreboard-v2-processor-backfill --args=--start-date=2025-01-01,--end-date=2025-01-07,--dry-run --region=us-west2"
echo ""
echo "  # Small test (3 days):"
echo "  gcloud run jobs execute nbac-scoreboard-v2-processor-backfill --args=--start-date=2025-01-01,--end-date=2025-01-03 --region=us-west2"
echo ""
echo "  # Small test with limit (3 days, max 5 files):"
echo "  gcloud run jobs execute nbac-scoreboard-v2-processor-backfill --args=--start-date=2025-01-01,--end-date=2025-01-03,--limit=5 --region=us-west2"
echo ""
echo "  # Weekly processing:"
echo "  gcloud run jobs execute nbac-scoreboard-v2-processor-backfill --args=--start-date=2025-01-01,--end-date=2025-01-07 --region=us-west2"
echo ""
echo "  # Monthly processing:"
echo "  gcloud run jobs execute nbac-scoreboard-v2-processor-backfill --args=--start-date=2025-01-01,--end-date=2025-01-31 --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • Processes NBA.com Scoreboard V2 data from GCS to BigQuery"
echo "  • Path pattern: nba-com/scoreboard-v2/{date}/*.json"
echo "  • Uses LATEST file per date (sorted by creation time)"
echo "  • Date arguments are OPTIONAL - defaults to last 30 days to today"
echo "  • Detailed status tracking: success, validation_failed, no_data, load_failed, error"
echo "  • Job has 1-hour timeout with 4GB memory and 2 CPUs"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo "  • For comma-separated values, use custom delimiter: --args=\"^|^--param=val1,val2|--other=val\""
echo ""

print_section_header "Validate results"
echo "  # Check recent data in BigQuery"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_records, MIN(game_date) as earliest_date, MAX(game_date) as latest_date, COUNT(DISTINCT game_id) as unique_games FROM \\\`nba-props-platform.nba_raw.nbac_scoreboard_v2\\\`\""
echo ""
echo "  # Check daily game counts (last 30 days)"
echo "  bq query --use_legacy_sql=false \"SELECT game_date, COUNT(*) as games_count FROM \\\`nba-props-platform.nba_raw.nbac_scoreboard_v2\\\` WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) GROUP BY game_date ORDER BY game_date DESC\""
echo ""
echo "  # Check game status distribution"
echo "  bq query --use_legacy_sql=false \"SELECT game_status_text, COUNT(*) as count FROM \\\`nba-props-platform.nba_raw.nbac_scoreboard_v2\\\` GROUP BY game_status_text ORDER BY count DESC\""

# Print final timing summary
print_deployment_summary