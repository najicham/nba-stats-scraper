#!/bin/bash
# FILE: backfill_jobs/scrapers/bp_props/deploy.sh

# Deploy BettingPros Props Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying BettingPros Props Backfill Job..."

# Use standardized scrapers backfill deployment script
./bin/scrapers/deploy/deploy_scrapers_backfill_job.sh bp_props

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (see date counts without downloading):"
echo "  gcloud run jobs execute bp-props-backfill --args=--dry-run,--limit=10 --region=us-west2"
echo ""
echo "  # Dry run for specific season:"
echo "  gcloud run jobs execute bp-props-backfill --args=\"^|^--dry-run|--seasons=2021\" --region=us-west2"
echo ""
echo "  # Small test (10 dates):"
echo "  gcloud run jobs execute bp-props-backfill --args=--limit=10 --region=us-west2"
echo ""
echo "  # Single season:"
echo "  gcloud run jobs execute bp-props-backfill --args=\"^|^--seasons=2021\" --region=us-west2"
echo ""
echo "  # Two seasons:"
echo "  gcloud run jobs execute bp-props-backfill --args=\"^|^--seasons=2021,2022\" --region=us-west2"
echo ""
echo "  # Playoffs only (fast - just playoff games):"
echo "  gcloud run jobs execute bp-props-backfill --args=--playoffs-only --region=us-west2"
echo ""
echo "  # Playoffs only for specific seasons:"
echo "  gcloud run jobs execute bp-props-backfill --args=\"^|^--seasons=2022,2023|--playoffs-only\" --region=us-west2"
echo ""
echo "  # Full 3-season backfill (default):"
echo "  gcloud run jobs execute bp-props-backfill --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • Downloads historical NBA player props from BettingPros for 3 seasons"
echo "  • LONG-RUNNING: 4-6 hours for full 3-season backfill"
echo "  • TWO scrapers per date: bp_events (game info) + bp_player_props (props)"
echo "  • Default seasons: 2021, 2022, 2023 (covers 2021-22, 2022-23, 2023-24)"
echo "  • Historical coverage: fills gap before Odds API coverage began"
echo "  • Uses NBA.com schedule data from GCS to generate date lists"
echo "  • Rate limited: 3 seconds between scraper calls (conservative)"
echo "  • Resume logic: checks for both events AND props data"
echo "  • Playoff filtering: --playoffs-only flag for targeted collection"
echo "  • Filters out pre-season, All-Star, and special games"
echo "  • Path: bettingpros/events/ and bettingpros/player-props/points/"
echo "  • Job has 6-hour timeout with 2GB memory and 1 CPU"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo "  • For comma-separated seasons, use pipe delimiter: --args=\"^|^--seasons=2021,2022\""
echo ""

print_section_header "Validate results"
echo "  # Check events data in GCS"
echo "  gsutil ls -lh gs://nba-scraped-data/bettingpros/events/ | head -20"
echo ""
echo "  # Check props data in GCS"
echo "  gsutil ls -lh gs://nba-scraped-data/bettingpros/player-props/points/ | head -20"
echo ""
echo "  # Count files per season (events)"
echo "  for year in 2021 2022 2023; do"
echo "    echo \"Season \$year events:\""
echo "    gsutil ls gs://nba-scraped-data/bettingpros/events/\$year-* | wc -l"
echo "  done"
echo ""
echo "  # Count files per season (props)"
echo "  for year in 2021 2022 2023; do"
echo "    echo \"Season \$year props:\""
echo "    gsutil ls gs://nba-scraped-data/bettingpros/player-props/points/\$year-* | wc -l"
echo "  done"
echo ""
echo "  # Check sample date data"
echo "  gsutil cat gs://nba-scraped-data/bettingpros/events/2023-01-15/*.json | jq '.'"
echo ""
echo "  # If processed to BigQuery, check data:"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_props, MIN(game_date) as earliest_date, MAX(game_date) as latest_date, COUNT(DISTINCT game_id) as unique_games, COUNT(DISTINCT player_name) as unique_players FROM \\\`nba-props-platform.nba_raw.bp_player_props\\\`\""
echo ""
echo "  # Check daily coverage (if in BigQuery):"
echo "  bq query --use_legacy_sql=false \"SELECT game_date, COUNT(DISTINCT player_name) as players_count, COUNT(*) as total_props FROM \\\`nba-props-platform.nba_raw.bp_player_props\\\` GROUP BY game_date ORDER BY game_date DESC LIMIT 10\""

# Print final timing summary
print_deployment_summary