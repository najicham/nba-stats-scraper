#!/bin/bash
# FILE: backfill_jobs/scrapers/espn_scoreboard/deploy.sh

# Deploy ESPN Scoreboard SCRAPER Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying ESPN Scoreboard SCRAPER Backfill Job..."

# CRITICAL: Use scrapers deployment script (NOT processor!)
./bin/scrapers/deploy/deploy_scrapers_backfill_job.sh espn_scoreboard

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (see what would be scraped):"
echo "  gcloud run jobs execute espn-scoreboard-backfill --args=\"^|^--dry-run|--limit=10\" --region=us-west2"
echo ""
echo "  # Small test (5 days):"
echo "  gcloud run jobs execute espn-scoreboard-backfill --args=\"^|^--start-date=2025-01-01|--end-date=2025-01-05\" --region=us-west2"
echo ""
echo "  # Single day test:"
echo "  gcloud run jobs execute espn-scoreboard-backfill --args=\"^|^--start-date=2025-01-15|--end-date=2025-01-15|--debug\" --region=us-west2"
echo ""
echo "  # Full month:"
echo "  gcloud run jobs execute espn-scoreboard-backfill --args=\"^|^--start-date=2025-01-01|--end-date=2025-01-31\" --region=us-west2"
echo ""
echo "  # Current season to date (2024-25):"
echo "  gcloud run jobs execute espn-scoreboard-backfill --args=\"^|^--start-date=2024-10-22|--end-date=2025-04-13\" --region=us-west2"
echo ""
echo "  # Custom delay (faster scraping):"
echo "  gcloud run jobs execute espn-scoreboard-backfill --args=\"^|^--start-date=2025-01-01|--end-date=2025-01-31|--delay=1.0\" --region=us-west2"
echo ""
echo "  # Production mode (saves to GCS):"
echo "  gcloud run jobs execute espn-scoreboard-backfill --args=\"^|^--start-date=2024-10-22|--end-date=2025-04-13|--group=prod\" --region=us-west2"
echo ""
echo "  # Re-scrape without resume (force refresh):"
echo "  gcloud run jobs execute espn-scoreboard-backfill --args=\"^|^--start-date=2025-01-01|--end-date=2025-01-31|--no-resume\" --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2"
echo ""

print_section_header "Notes"
echo "  • Scrapes ESPN scoreboard data for NBA games"
echo "  • Duration: ~2-5 minutes for 30 days with default 2s delay"
echo "  • Duration: ~6-10 minutes for full season (~174 days)"
echo "  • RATE LIMITED: 2s delays by default to respect ESPN servers"
echo "  • Sequential processing: one date at a time"
echo "  • Resume capability: skips already processed dates (if implemented)"
echo "  • Path: espn/scoreboard/{YYYY-MM-DD}/*.json"
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

print_section_header "Validate results"
echo "  # Check scraped data in GCS"
echo "  gsutil ls -lh gs://nba-scraped-data/espn/scoreboard/ | head -20"
echo ""
echo "  # Count files per month"
echo "  gsutil ls gs://nba-scraped-data/espn/scoreboard/2025-01-*/*.json | wc -l"
echo ""
echo "  # Check sample scoreboard"
echo "  gsutil cat gs://nba-scraped-data/espn/scoreboard/2025-01-15/*.json | jq '.'"
echo ""
echo "  # If processed to BigQuery, check data:"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_games, COUNT(DISTINCT game_date) as unique_dates, MIN(game_date) as earliest, MAX(game_date) as latest FROM \\\`nba-props-platform.nba_raw.espn_scoreboard\\\`\""

# Print final timing summary
print_deployment_summary