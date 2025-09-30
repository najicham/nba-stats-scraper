#!/bin/bash
# FILE: backfill_jobs/scrapers/nbac_injury/deploy.sh

# Deploy NBA.com Injury Reports Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying NBA.com Injury Reports Backfill Job..."

# Use standardized scrapers backfill deployment script
./bin/scrapers/deploy/deploy_scrapers_backfill_job.sh nbac_injury

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (see interval counts):"
echo "  gcloud run jobs execute nbac-injury-backfill --args=--dry-run,--limit=20 --region=us-west2"
echo ""
echo "  # Small test (10 intervals):"
echo "  gcloud run jobs execute nbac-injury-backfill --args=--limit=10 --region=us-west2"
echo ""
echo "  # Test with 100 intervals:"
echo "  gcloud run jobs execute nbac-injury-backfill --args=--limit=100 --region=us-west2"
echo ""
echo "  # Single season test:"
echo "  gcloud run jobs execute nbac-injury-backfill --args=\"^|^--seasons=2024|--limit=100\" --region=us-west2"
echo ""
echo "  # Resume from specific date:"
echo "  gcloud run jobs execute nbac-injury-backfill --args=--start-date=2024-01-01 --region=us-west2"
echo ""
echo "  # Full 4-season backfill (default):"
echo "  gcloud run jobs execute nbac-injury-backfill --region=us-west2"
echo ""
echo "  # Two seasons with limit:"
echo "  gcloud run jobs execute nbac-injury-backfill --args=\"^|^--seasons=2023,2024|--limit=500\" --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • Downloads NBA.com injury report PDFs for 4 seasons (2021-2024)"
echo "  • VERY LONG-RUNNING: 10+ hours for full 4-season backfill"
echo "  • Hourly interval strategy: 24 intervals per day (~50,000+ total intervals)"
echo "  • Uses NBA.com schedule data from GCS to generate date lists"
echo "  • Rate limited: 4 seconds per request (same as gamebook backfill)"
echo "  • Resume logic: skips intervals with existing PDFs in GCS"
echo "  • Pattern discovery: analyzes which times have reports available"
echo "  • Multiple path checks: injury-report-pdf/, injury-report-data/"
echo "  • Smart limit handling: skips existing files, only processes new ones"
echo "  • Path: nba-com/injury-report-pdf/{date}/{hour}/"
echo "  • Job has 10-hour timeout with 2Gi memory and 1 CPU"
echo "  • Default: processes all 4 seasons (2021, 2022, 2023, 2024)"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo "  • For comma-separated seasons, use pipe delimiter: --args=\"^|^--seasons=2021,2022\""
echo ""

print_section_header "Validate results"
echo "  # Check PDF files in GCS"
echo "  gsutil ls -lh gs://nba-scraped-data/nba-com/injury-report-pdf/ | head -20"
echo ""
echo "  # Count PDFs per season"
echo "  for year in 2021 2022 2023 2024; do"
echo "    count=\$(gsutil ls -r gs://nba-scraped-data/nba-com/injury-report-pdf/\$year-*/**/*.pdf 2>/dev/null | wc -l)"
echo "    echo \"Season \$year: \$count PDFs\""
echo "  done"
echo ""
echo "  # Check data files (JSON)"
echo "  gsutil ls -lh gs://nba-scraped-data/nba-com/injury-report-data/ | head -20"
echo ""
echo "  # Check sample date"
echo "  gsutil ls gs://nba-scraped-data/nba-com/injury-report-pdf/2024-01-15/"
echo ""
echo "  # View pattern analysis from logs (shows which times have reports):"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 | grep 'PATTERN ANALYSIS' -A 20"
echo ""
echo "  # If processed to BigQuery, check data:"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_reports, MIN(report_date) as earliest_date, MAX(report_date) as latest_date, COUNT(DISTINCT report_date) as unique_dates FROM \\\`nba-props-platform.nba_raw.nbac_injury_reports\\\`\""

# Print final timing summary
print_deployment_summary