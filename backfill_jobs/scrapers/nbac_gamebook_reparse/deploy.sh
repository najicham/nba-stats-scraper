#!/bin/bash
# FILE: backfill_jobs/scrapers/nbac_gamebook_reparse/deploy.sh

# Deploy NBA.com Gamebook PDF Enhanced Re-parse Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying NBA.com Gamebook PDF Enhanced Re-parse Job..."

# Use standardized scrapers backfill deployment script
./bin/scrapers/deploy/deploy_scrapers_backfill_job.sh nbac_gamebook_reparse

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # IMPORTANT: This job reads existing PDFs from GCS and re-parses them"
echo "  # Much faster than download job: 1-2 hours vs 6+ hours"
echo ""
echo "  # Dry run (see what PDFs exist without processing):"
echo "  gcloud run jobs execute nbac-gamebook-reparse --args=--dry-run --region=us-west2"
echo ""
echo "  # Dry run with limit (check first 10 games):"
echo "  gcloud run jobs execute nbac-gamebook-reparse --args=--dry-run,--limit=10 --region=us-west2"
echo ""
echo "  # Small test (process 5 games):"
echo "  gcloud run jobs execute nbac-gamebook-reparse --args=--limit=5 --region=us-west2"
echo ""
echo "  # Small test (process 20 games):"
echo "  gcloud run jobs execute nbac-gamebook-reparse --args=--limit=20 --region=us-west2"
echo ""
echo "  # Force re-parse (even if JSON already exists):"
echo "  gcloud run jobs execute nbac-gamebook-reparse --args=--limit=10,--force --region=us-west2"
echo ""
echo "  # Full reparse (all 4 seasons: 2021-2024, ~5,500 PDFs):"
echo "  gcloud run jobs execute nbac-gamebook-reparse --region=us-west2"
echo ""
echo "  # NOTE: For single season processing, use separate job executions:"
echo "  # The --seasons parameter accepts space-separated values which are complex in gcloud args"
echo "  # Default behavior processes all 4 seasons (2021, 2022, 2023, 2024)"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "How This Job Works"
echo "  • Scans GCS bucket for existing gamebook PDFs"
echo "  • Calls enhanced scraper service with pdf_source='gcs'"
echo "  • Scraper reads PDF from GCS (no NBA.com download)"
echo "  • Parses using battle-tested enhanced scraper logic"
echo "  • Saves parsed JSON to GCS in gamebooks-data/"
echo "  • Much faster: 1-2 hours vs 6+ hours for download job"
echo ""

print_section_header "Notes"
echo "  • Re-parses existing NBA.com gamebook PDFs using enhanced scraper"
echo "  • PDF source: gs://nba-scraped-data/nba-com/gamebooks-pdf/"
echo "  • Output: gs://nba-scraped-data/nba-com/gamebooks-data/"
echo "  • Processes ~5,500 PDFs across 4 seasons (2021-22 through 2024-25)"
echo "  • Default seasons: 2021, 2022, 2023, 2024"
echo "  • Skip logic: Won't re-parse if JSON already exists (use --force to override)"
echo "  • Resume capability: Can restart from where it left off"
echo "  • Rate limited: 0.5 seconds between scraper calls (configurable)"
echo "  • Job has 2-hour timeout with 2GB memory and 1 CPU"
echo "  • Uses enhanced scraper service: https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo ""

print_section_header "Processing Strategy"
echo "  • Scans GCS to find all existing PDFs by season"
echo "  • Uses most recent PDF per game (timestamp-sorted)"
echo "  • Checks for existing JSON before re-parsing (unless --force)"
echo "  • Calls scraper service per game with special 'reparse_from_gcs' mode"
echo "  • Progress tracking: Every 50 games with success rate"
echo ""

print_section_header "Validate results"
echo "  # Check parsed JSON files in GCS"
echo "  gsutil ls -lh gs://nba-scraped-data/nba-com/gamebooks-data/ | head -20"
echo ""
echo "  # Count parsed games per season"
echo "  for year in 2021 2022 2023 2024; do"
echo "    echo \"Season \$year parsed:\""
echo "    gsutil ls -r gs://nba-scraped-data/nba-com/gamebooks-data/\${year}-* | grep '.json$' | wc -l"
echo "  done"
echo ""
echo "  # Check sample parsed data"
echo "  gsutil cat gs://nba-scraped-data/nba-com/gamebooks-data/2024-01-*/*/latest.json | jq '.' | head -50"
echo ""
echo "  # If data is processed to BigQuery, check player stats:"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_records, COUNT(DISTINCT game_id) as unique_games, COUNT(DISTINCT player_id) as unique_players, MIN(game_date) as earliest_date, MAX(game_date) as latest_date FROM \\\`nba-props-platform.nba_raw.nbac_gamebook_player_stats\\\`\""
echo ""
echo "  # Check season breakdown (if in BigQuery):"
echo "  bq query --use_legacy_sql=false \"SELECT season_year, COUNT(DISTINCT game_id) as games, COUNT(DISTINCT player_id) as players, COUNT(*) as total_records FROM \\\`nba-props-platform.nba_raw.nbac_gamebook_player_stats\\\` GROUP BY season_year ORDER BY season_year DESC\""

# Print final timing summary
print_deployment_summary