#!/bin/bash
# FILE: backfill_jobs/scrapers/nbac_scoreboard_v2/deploy.sh

# Deploy NBA.com Scoreboard V2 Scraper Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying NBA.com Scoreboard V2 Scraper Backfill Job..."

# Use standardized scrapers backfill deployment script
./bin/scrapers/deploy/deploy_scrapers_backfill_job.sh nbac_scoreboard_v2

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (see what would be scraped):"
echo "  gcloud run jobs execute nbac-scoreboard-v2-backfill --args=\"^|^--dry-run|--limit=10\" --region=us-west2"
echo ""
echo "  # Small test (5 days):"
echo "  gcloud run jobs execute nbac-scoreboard-v2-backfill --args=\"^|^--start-date=2025-01-01|--end-date=2025-01-05\" --region=us-west2"
echo ""
echo "  # Single day test:"
echo "  gcloud run jobs execute nbac-scoreboard-v2-backfill --args=\"^|^--start-date=2025-01-15|--end-date=2025-01-15|--debug\" --region=us-west2"
echo ""
echo "  # Full month:"
echo "  gcloud run jobs execute nbac-scoreboard-v2-backfill --args=\"^|^--start-date=2025-01-01|--end-date=2025-01-31\" --region=us-west2"
echo ""
echo "  # Current season to date (2024-25):"
echo "  gcloud run jobs execute nbac-scoreboard-v2-backfill --args=\"^|^--start-date=2024-10-22|--end-date=2025-04-13\" --region=us-west2"
echo ""
echo "  # Custom delay (faster scraping):"
echo "  gcloud run jobs execute nbac-scoreboard-v2-backfill --args=\"^|^--start-date=2025-01-01|--end-date=2025-01-31|--delay=1.0\" --region=us-west2"
echo ""
echo "  # Production mode (saves to GCS):"
echo "  gcloud run jobs execute nbac-scoreboard-v2-backfill --args=\"^|^--start-date=2024-10-22|--end-date=2025-04-13|--group=prod\" --region=us-west2"
echo ""
echo "  # Re-scrape without resume (force refresh):"
echo "  gcloud run jobs execute nbac-scoreboard-v2-backfill --args=\"^|^--start-date=2025-01-01|--end-date=2025-01-31|--no-resume\" --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2"
echo ""

print_section_header "Notes"
echo "  • Scrapes NBA.com Scoreboard V2 data for NBA games"
echo "  • ✅ FIXED: Uses correct home/away team assignment"
echo "  • Duration: ~2-5 minutes for 30 days with default 2s delay"
echo "  • Duration: ~6-10 minutes for full season (~174 days)"
echo "  • RATE LIMITED: 2s delays by default to respect NBA.com servers"
echo "  • Uses proxy rotation (configured in scraper)"
echo "  • Sequential processing: one date at a time"
echo "  • Resume capability: skips already processed dates (if implemented)"
echo "  • Path: nba-com/scoreboard-v2/{YYYY-MM-DD}/*.json"
echo "  • Job has 1-hour timeout with 2GB memory and 1 CPU"
echo "  • Export groups: dev (default), test, prod, gcs"
echo "  • Date formats: YYYY-MM-DD or YYYYMMDD (both work)"
echo "  • Args use PIPE delimiter: --args=\"^|^--param1=value|--param2=value\""
echo "  • This is REQUIRED for args with dates/values"
echo ""

print_section_header "NBA Season Date Ranges"
echo "  2024-25 Season: 2024-10-22 to 2025-04-13 (~174 days)"
echo "  2023-24 Season: 2023-10-24 to 2024-04-14 (~174 days)"
echo "  2022-23 Season: 2022-10-18 to 2023-04-09 (~174 days)"
echo "  2021-22 Season: 2021-10-19 to 2022-04-10 (~174 days)"
echo ""

print_section_header "Why This Backfill Matters"
echo "  • Fixes home/away team assignment bug in historical data"
echo "  • Ensures correct team assignments for all games"
echo "  • Critical for accurate stats, analytics, and predictions"
echo "  • Should be run AFTER the scraper fix was deployed"
echo ""

print_section_header "Validate results"
echo "  # Check scraped data in GCS"
echo "  gsutil ls -lh gs://nba-scraped-data/nba-com/scoreboard-v2/ | head -20"
echo ""
echo "  # Count files per month"
echo "  gsutil ls gs://nba-scraped-data/nba-com/scoreboard-v2/2025-01-*/*.json | wc -l"
echo ""
echo "  # Check sample scoreboard"
echo "  gsutil cat gs://nba-scraped-data/nba-com/scoreboard-v2/2025-01-15/*.json | jq '.'"
echo ""
echo "  # Verify home/away teams are correct"
echo "  gsutil cat gs://nba-scraped-data/nba-com/scoreboard-v2/2025-01-15/*.json | jq '.games[0].teams'"
echo ""

# Print final timing summary
print_deployment_summary