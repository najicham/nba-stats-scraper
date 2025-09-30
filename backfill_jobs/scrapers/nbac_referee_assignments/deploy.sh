#!/bin/bash
# FILE: backfill_jobs/scrapers/nbac_referee_assignments/deploy.sh

# Deploy NBA Referee Assignments Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying NBA Referee Assignments Backfill Job..."

# Use standardized scrapers backfill deployment script
./bin/scrapers/deploy/deploy_scrapers_backfill_job.sh nbac_referee_assignments

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (see date counts without downloading):"
echo "  gcloud run jobs execute nba-referee-assignments-backfill --args=--dry-run,--limit=10 --region=us-west2"
echo ""
echo "  # Dry run with specific seasons:"
echo "  gcloud run jobs execute nba-referee-assignments-backfill --args=\"^|^--dry-run|--seasons=2023,2024|--limit=50\" --region=us-west2"
echo ""
echo "  # Small test (10 dates):"
echo "  gcloud run jobs execute nba-referee-assignments-backfill --args=--limit=10 --region=us-west2"
echo ""
echo "  # Single season:"
echo "  gcloud run jobs execute nba-referee-assignments-backfill --args=\"^|^--seasons=2023\" --region=us-west2"
echo ""
echo "  # Two seasons:"
echo "  gcloud run jobs execute nba-referee-assignments-backfill --args=\"^|^--seasons=2023,2024\" --region=us-west2"
echo ""
echo "  # Full 4-season backfill (default):"
echo "  gcloud run jobs execute nba-referee-assignments-backfill --region=us-west2"
echo ""
echo "  # Resume from specific date:"
echo "  gcloud run jobs execute nba-referee-assignments-backfill --args=--start-date=2023-04-15 --region=us-west2"
echo ""
echo "  # Date range filter:"
echo "  gcloud run jobs execute nba-referee-assignments-backfill --args=--start-date=2023-10-01,--end-date=2024-04-30 --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • Collects NBA referee assignments for 4 seasons (2021-2024)"
echo "  • Uses NBA.com schedule data from GCS to generate date lists"
echo "  • Processes ~1400 dates total (2-4 hours runtime)"
echo "  • Resume logic: skips dates with existing data in GCS"
echo "  • Handles off-season dates gracefully (no games is normal)"
echo "  • Path: nba-com/referee-assignments/{YYYY-MM-DD}/"
echo "  • Rate limited: 2 seconds per date for API stability"
echo "  • Job has 4-hour timeout with 2GB memory and 1 CPU"
echo "  • Default: processes all 4 seasons (2021,2022,2023,2024)"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo "  • For comma-separated seasons, use pipe delimiter: --args=\"^|^--seasons=2021,2022\""
echo ""

print_section_header "Validate results"
echo "  # Check scraped data in GCS"
echo "  gsutil ls -lh gs://nba-scraped-data/nba-com/referee-assignments/ | head -20"
echo ""
echo "  # Count files per season"
echo "  for year in 2021 2022 2023 2024; do"
echo "    echo \"Season \$year:\""
echo "    gsutil ls gs://nba-scraped-data/nba-com/referee-assignments/\$year-* | wc -l"
echo "  done"
echo ""
echo "  # If processed to BigQuery, check data:"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_records, MIN(assignment_date) as earliest_date, MAX(assignment_date) as latest_date, COUNT(DISTINCT game_id) as unique_games FROM \\\`nba-props-platform.nba_raw.nbac_referee_assignments\\\`\""
echo ""
echo "  # Check daily coverage (if in BigQuery):"
echo "  bq query --use_legacy_sql=false \"SELECT assignment_date, COUNT(DISTINCT game_id) as games_count, COUNT(*) as total_assignments FROM \\\`nba-props-platform.nba_raw.nbac_referee_assignments\\\` GROUP BY assignment_date ORDER BY assignment_date DESC LIMIT 10\""

# Print final timing summary
print_deployment_summary