#!/bin/bash
# FILE: backfill_jobs/raw/bdl_injuries/deploy.sh

# Deploy BDL Injuries Processor Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying BDL Injuries Processor Backfill Job..."

# Use standardized raw processors backfill deployment script
./bin/raw/deploy/deploy_processor_backfill_job.sh bdl_injuries

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (check data availability):"
echo "  gcloud run jobs execute bdl-injuries-processor-backfill --args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Dry run with limit (check first 5 files):"
echo "  gcloud run jobs execute bdl-injuries-processor-backfill --args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-31,--limit=5 --region=us-west2"
echo ""
echo "  # Small test (3 days):"
echo "  gcloud run jobs execute bdl-injuries-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-03 --region=us-west2"
echo ""
echo "  # Small test with limit (3 days, max 5 files):"
echo "  gcloud run jobs execute bdl-injuries-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-03,--limit=5 --region=us-west2"
echo ""
echo "  # Weekly processing:"
echo "  gcloud run jobs execute bdl-injuries-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Monthly processing:"
echo "  gcloud run jobs execute bdl-injuries-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2"
echo ""
echo "  # Full historical backfill:"
echo "  gcloud run jobs execute bdl-injuries-processor-backfill --args=--start-date=2021-10-01,--end-date=2025-06-30 --region=us-west2"
echo ""
echo "  # Use defaults (processes full range from job-config.env):"
echo "  gcloud run jobs execute bdl-injuries-processor-backfill --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • Processes Ball Don't Lie injury report data from GCS to BigQuery"
echo "  • Injury reports are small JSON files with minimal processing requirements"
echo "  • Job has 30-minute timeout with 2GB memory and 1 CPU"
echo "  • Multiple files may exist per date (captured at different times)"
echo "  • Progress logging every 50 files"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo "  • For comma-separated values, use custom delimiter: --args=\"^|^--param=val1,val2|--other=val\""
echo ""

print_section_header "Validate results"
echo "  # Check recent data in BigQuery"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_records, MIN(report_date) as earliest_date, MAX(report_date) as latest_date, COUNT(DISTINCT player_id) as unique_players FROM \\\`nba-props-platform.nba_raw.bdl_injuries\\\`\""

# Print final timing summary
print_deployment_summary