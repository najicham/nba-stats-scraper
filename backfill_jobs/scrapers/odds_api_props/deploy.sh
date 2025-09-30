#!/bin/bash
# FILE: backfill_jobs/scrapers/odds_api_props/deploy.sh

# Deploy Odds API Props Historical Collection Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying Odds API Props Historical Collection Job..."

# Use standardized scrapers backfill deployment script
./bin/scrapers/deploy/deploy_scrapers_backfill_job.sh odds_api_props

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # IMPORTANT: Uses custom delimiter ^|^ for comma-separated seasons"
echo "  # LONG-RUNNING JOB: 4-8 hours for full 4-season backfill (~800 game dates)"
echo ""
echo "  # Dry run (see dates without API calls):"
echo "  gcloud run jobs execute nba-odds-api-season-backfill --args=--dry-run --region=us-west2"
echo ""
echo "  # Dry run with limit (check first 5 dates):"
echo "  gcloud run jobs execute nba-odds-api-season-backfill --args=--dry-run,--limit=5 --region=us-west2"
echo ""
echo "  # Small test (process 5 dates):"
echo "  gcloud run jobs execute nba-odds-api-season-backfill --args=--limit=5 --region=us-west2"
echo ""
echo "  # Single season test:"
echo "  gcloud run jobs execute nba-odds-api-season-backfill --args=\"^|^--seasons=2023\" --region=us-west2"
echo ""
echo "  # Two seasons:"
echo "  gcloud run jobs execute nba-odds-api-season-backfill --args=\"^|^--seasons=2023,2024\" --region=us-west2"
echo ""
echo "  # Full 4-season backfill (default - LONG RUNNING):"
echo "  gcloud run jobs execute nba-odds-api-season-backfill --region=us-west2"
echo ""
echo "  # With specific strategy:"
echo "  gcloud run jobs execute nba-odds-api-season-backfill --args=\"^|^--seasons=2023|--strategy=pregame\" --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Props Collection Strategies"
echo "  • conservative (default): 2h before game start - 100% reliability"
echo "  • pregame: 1h before game start - faster collection"
echo "  • final: 30m before game start - latest odds available"
echo ""

print_section_header "How This Job Works"
echo "  • Reads NBA schedule files from GCS (same as gamebook logic)"
echo "  • Extracts game dates for specified seasons (2021-2024)"
echo "  • Filters out preseason, All-Star, and special games"
echo "  • Includes all playoff and play-in games"
echo "  • For each date:"
echo "    1. Calls scraper for events data (once per date)"
echo "    2. Calls scraper for props data (once per game)"
echo "  • Events data cached per date (optimization)"
echo "  • Resume logic: skips dates already processed"
echo "  • Rate limited: 1.0 seconds between API calls"
echo ""

print_section_header "Notes"
echo "  • Collects historical NBA player props from The-Odds-API"
echo "  • Data source: NBA.com schedule files in GCS"
echo "  • Output paths:"
echo "    - Events: gs://nba-scraped-data/odds-api/events-history/"
echo "    - Props: gs://nba-scraped-data/odds-api/player-props-history/"
echo "  • Default seasons: 2021, 2022, 2023, 2024 (4 full seasons)"
echo "  • Processes ~800 game dates total"
echo "  • VERY LONG-RUNNING: 4-8 hours for full backfill"
echo "  • Job has 10-hour timeout with 2GB memory and 1 CPU"
echo "  • Props data available from May 3, 2023 onwards (earlier dates filtered)"
echo "  • Uses enhanced scraper service: https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"
echo "  • Resume capability: can restart from where it left off"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo "  • For comma-separated seasons, use pipe delimiter: --args=\"^|^--seasons=2021,2022\""
echo ""

print_section_header "Game Filtering Logic"
echo "  • INCLUDES: Regular season games, playoff games, play-in games"
echo "  • EXCLUDES: Preseason (week 0), All-Star events, special exhibition games"
echo "  • Validates NBA team codes (30 teams)"
echo "  • Filters dates before May 3, 2023 (props data not available)"
echo ""

print_section_header "Validate results"
echo "  # Check events data in GCS"
echo "  gsutil ls -lh gs://nba-scraped-data/odds-api/events-history/ | head -20"
echo ""
echo "  # Check props data in GCS"
echo "  gsutil ls -lh gs://nba-scraped-data/odds-api/player-props-history/ | head -20"
echo ""
echo "  # Count files per season (events)"
echo "  for year in 2021 2022 2023 2024; do"
echo "    echo \"Season \$year events:\""
echo "    gsutil ls -r gs://nba-scraped-data/odds-api/events-history/ | grep \"\$year-\" | wc -l"
echo "  done"
echo ""
echo "  # Count files per season (props)"
echo "  for year in 2021 2022 2023 2024; do"
echo "    echo \"Season \$year props:\""
echo "    gsutil ls -r gs://nba-scraped-data/odds-api/player-props-history/ | grep \"\$year-\" | wc -l"
echo "  done"
echo ""
echo "  # Check sample date data"
echo "  gsutil cat gs://nba-scraped-data/odds-api/player-props-history/2023-05-*/*/latest.json | jq '.data[0]' | head -50"
echo ""
echo "  # If processed to BigQuery, check data:"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_props, MIN(game_date) as earliest_date, MAX(game_date) as latest_date, COUNT(DISTINCT event_id) as unique_games, COUNT(DISTINCT player_name) as unique_players FROM \\\`nba-props-platform.nba_raw.odds_api_player_props\\\`\""
echo ""
echo "  # Check daily coverage (if in BigQuery):"
echo "  bq query --use_legacy_sql=false \"SELECT game_date, COUNT(DISTINCT player_name) as players_count, COUNT(*) as total_props FROM \\\`nba-props-platform.nba_raw.odds_api_player_props\\\` GROUP BY game_date ORDER BY game_date DESC LIMIT 10\""

# Print final timing summary
print_deployment_summary