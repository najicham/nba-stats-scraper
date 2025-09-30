#!/bin/bash
# FILE: backfill_jobs/raw/nbac_player_movement/deploy.sh

# Deploy NBA.com Player Movement Processor Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying NBA.com Player Movement Processor Backfill Job..."

# Use standardized raw processors backfill deployment script
./bin/raw/deploy/deploy_processor_backfill_job.sh nbac_player_movement

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # IMPORTANT: Dates are OPTIONAL - processes all available files if not specified"
echo ""
echo "  # Dry run (check all available files):"
echo "  gcloud run jobs execute nbac-player-movement-processor-backfill --args=--dry-run --region=us-west2"
echo ""
echo "  # Dry run with limit (check first 10 files):"
echo "  gcloud run jobs execute nbac-player-movement-processor-backfill --args=--dry-run,--limit=10 --region=us-west2"
echo ""
echo "  # Small test with limit (process first 5 files):"
echo "  gcloud run jobs execute nbac-player-movement-processor-backfill --args=--limit=5 --region=us-west2"
echo ""
echo "  # Date range with dry run:"
echo "  gcloud run jobs execute nbac-player-movement-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07,--dry-run --region=us-west2"
echo ""
echo "  # Small test (3 days):"
echo "  gcloud run jobs execute nbac-player-movement-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-03 --region=us-west2"
echo ""
echo "  # Monthly processing:"
echo "  gcloud run jobs execute nbac-player-movement-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2"
echo ""
echo "  # Full processing (all available files - recommended):"
echo "  gcloud run jobs execute nbac-player-movement-processor-backfill --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • Processes NBA.com Player Movement data (trades, signings, releases)"
echo "  • Path pattern: nba-com/player-movement/{date}/*.json"
echo "  • Processes ALL available files by default (no date filtering needed)"
echo "  • Automatically filters to 2021+ transactions (≈4,200 of 8,797 total records)"
echo "  • Uses INSERT_NEW_ONLY strategy to prevent duplicate transactions"
echo "  • Handles composite primary key for multi-team trade scenarios"
echo "  • Job has 1-hour timeout with 4GB memory and 2 CPUs"
echo "  • Date arguments are OPTIONAL - omit to process all available files"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo "  • For comma-separated values, use custom delimiter: --args=\"^|^--param=val1,val2|--other=val\""
echo ""

print_section_header "Validate results"
echo "  # Check recent data in BigQuery"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_records, MIN(transaction_date) as earliest_date, MAX(transaction_date) as latest_date, COUNT(DISTINCT player_id) as unique_players FROM \\\`nba-props-platform.nba_raw.nbac_player_movement\\\`\""
echo ""
echo "  # Check transaction types"
echo "  bq query --use_legacy_sql=false \"SELECT transaction_type, COUNT(*) as count FROM \\\`nba-props-platform.nba_raw.nbac_player_movement\\\` GROUP BY transaction_type ORDER BY count DESC\""
echo ""
echo "  # Check recent transactions (last 30 days)"
echo "  bq query --use_legacy_sql=false \"SELECT transaction_date, player_name, transaction_description, transaction_type FROM \\\`nba-props-platform.nba_raw.nbac_player_movement\\\` WHERE transaction_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) ORDER BY transaction_date DESC LIMIT 10\""

# Print final timing summary
print_deployment_summary