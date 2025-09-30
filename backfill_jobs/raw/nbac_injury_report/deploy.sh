#!/bin/bash
# FILE: backfill_jobs/raw/nbac_injury_report/deploy.sh

# Deploy NBA.com Injury Report Processor Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying NBA.com Injury Report Processor Backfill Job..."

# Use standardized raw processors backfill deployment script
./bin/raw/deploy/deploy_processor_backfill_job.sh nbac_injury_report

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # IMPORTANT: --start-date and --end-date are REQUIRED for this processor"
echo ""
echo "  # Dry run (check data availability and hourly distribution):"
echo "  gcloud run jobs execute nbac-injury-report-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07,--dry-run --region=us-west2"
echo ""
echo "  # Small test (3 days):"
echo "  gcloud run jobs execute nbac-injury-report-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-03 --region=us-west2"
echo ""
echo "  # Small test with custom batch size:"
echo "  gcloud run jobs execute nbac-injury-report-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-03,--batch-size=50 --region=us-west2"
echo ""
echo "  # Weekly processing:"
echo "  gcloud run jobs execute nbac-injury-report-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Monthly processing:"
echo "  gcloud run jobs execute nbac-injury-report-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2"
echo ""
echo "  # Full historical backfill:"
echo "  gcloud run jobs execute nbac-injury-report-processor-backfill --args=--start-date=2021-10-01,--end-date=2025-08-29 --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • Processes NBA.com injury reports from GCS to BigQuery"
echo "  • CRITICAL: Processes ALL hourly snapshots, not just one per day"
echo "  • Path pattern: nba-com/injury-report-data/{date}/{hour}/*.json"
echo "  • Tracks injury status patterns across multiple daily updates"
echo "  • Job has 2-hour timeout with 4GB memory and 2 CPUs (larger for years of data)"
echo "  • --start-date and --end-date are REQUIRED parameters"
echo "  • --batch-size controls progress logging frequency (default: 100 files)"
echo "  • Dry run shows hourly distribution analysis"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo "  • For comma-separated values, use custom delimiter: --args=\"^|^--param=val1,val2|--other=val\""
echo ""

print_section_header "Validate results"
echo "  # Check recent data in BigQuery"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_records, MIN(report_date) as earliest_date, MAX(report_date) as latest_date, COUNT(DISTINCT player_id) as unique_players FROM \\\`nba-props-platform.nba_raw.nbac_injury_report\\\`\""
echo ""
echo "  # Check hourly coverage"
echo "  bq query --use_legacy_sql=false \"SELECT report_date, COUNT(*) as reports_per_day FROM \\\`nba-props-platform.nba_raw.nbac_injury_report\\\` GROUP BY report_date ORDER BY report_date DESC LIMIT 10\""

# Print final timing summary
print_deployment_summary