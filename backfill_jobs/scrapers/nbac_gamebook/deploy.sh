#!/bin/bash
# FILE: backfill_jobs/scrapers/nbac_gamebook/deploy.sh

# Deploy NBA.com Gamebook Scraper Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying NBA.com Gamebook Scraper Backfill Job..."

# Use scraper-specific backfill deployment script
# Note: This is different from processor backfill - this downloads PDFs from NBA.com
./bin/scrapers/deploy/deploy_scraper_backfill_job.sh nbac_gamebook

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (check game counts without downloading):"
echo "  gcloud run jobs execute nbac-gamebook-backfill --args=\"^|^--seasons=2023|--limit=100|--dry-run\" --region=us-west2"
echo ""
echo "  # Small test (limit to 10 games):"
echo "  gcloud run jobs execute nbac-gamebook-backfill --args=\"^|^--seasons=2023|--limit=10\" --region=us-west2"
echo ""
echo "  # Single season (2023-24 with playoffs):"
echo "  gcloud run jobs execute nbac-gamebook-backfill --args=\"^|^--seasons=2023\" --region=us-west2"
echo ""
echo "  # Two seasons (2023-24 and 2024-25):"
echo "  gcloud run jobs execute nbac-gamebook-backfill --args=\"^|^--seasons=2023,2024\" --region=us-west2"
echo ""
echo "  # Full 4-season backfill (all available data):"
echo "  gcloud run jobs execute nbac-gamebook-backfill --args=\"^|^--seasons=2021,2022,2023,2024\" --region=us-west2"
echo ""
echo "  # Resume from specific date (skip already downloaded):"
echo "  gcloud run jobs execute nbac-gamebook-backfill --args=\"^|^--start-date=2023-04-15|--seasons=2023\" --region=us-west2"
echo ""
echo "  # Date range filter:"
echo "  gcloud run jobs execute nbac-gamebook-backfill --args=\"^|^--start-date=2023-10-01|--end-date=2023-12-31|--seasons=2023\" --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • SCRAPER JOB: Downloads fresh PDFs directly from NBA.com (not a processor)"
echo "  • Downloads ~5,500 gamebook PDFs across 4 NBA seasons (2021-22 through 2024-25)"
echo "  • Includes regular season, playoffs, and play-in games (enhanced filtering)"
echo "  • Excludes preseason and All-Star special events (Celebrity Game, Skills, etc.)"
echo "  • Job has 7-hour timeout with 2GB memory and 1 CPU (sized for slow downloads)"
echo "  • Rate limited: 4 seconds per game (NBA.com requirement)"
echo "  • Expected duration: ~6+ hours for full 4-season backfill"
echo "  • Resume logic: automatically skips already downloaded PDFs"
echo "  • PDFs saved to: gs://nba-scraped-data/nba-com/gamebooks-pdf/"
echo "  • Requires scraper service URL (set via SCRAPER_SERVICE_URL env var)"
echo "  • CRITICAL: Use pipe delimiter for comma-separated seasons:"
echo "    --args=\"^|^--seasons=2021,2022,2023,2024\""
echo "  • Date filters also need pipe delimiter when combined with seasons:"
echo "    --args=\"^|^--start-date=2023-10-01|--end-date=2024-06-30|--seasons=2023\""
echo ""

print_section_header "Validate results"
echo "  # Check downloaded PDFs in GCS"
echo "  gsutil ls -r gs://nba-scraped-data/nba-com/gamebooks-pdf/ | wc -l"
echo ""
echo "  # Check recent downloads (last 7 days):"
echo "  gsutil ls -l gs://nba-scraped-data/nba-com/gamebooks-pdf/**/*.pdf | grep \$(date -d '7 days ago' +%Y-%m-%d)"
echo ""
echo "  # Sample validation (check if specific game exists):"
echo "  gsutil ls gs://nba-scraped-data/nba-com/gamebooks-pdf/2023-10-24/20231024-LALMEM/"

# Print final timing summary
print_deployment_summary