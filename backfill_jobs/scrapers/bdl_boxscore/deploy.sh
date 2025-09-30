#!/bin/bash
# FILE: backfill_jobs/scrapers/bdl_boxscore/deploy.sh

# Deploy Ball Don't Lie Boxscore Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying Ball Don't Lie Boxscore Backfill Job..."

# Use standardized scrapers backfill deployment script
./bin/scrapers/deploy/deploy_scrapers_backfill_job.sh bdl_boxscore

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (see date counts without downloading):"
echo "  gcloud run jobs execute bdl-boxscore-backfill --args=--dry-run,--limit=10 --region=us-west2"
echo ""
echo "  # Dry run for specific season:"
echo "  gcloud run jobs execute bdl-boxscore-backfill --args=\"^|^--dry-run|--seasons=2023\" --region=us-west2"
echo ""
echo "  # Small test (10 dates):"
echo "  gcloud run jobs execute bdl-boxscore-backfill --args=--limit=10 --region=us-west2"
echo ""
echo "  # Single season:"
echo "  gcloud run jobs execute bdl-boxscore-backfill --args=\"^|^--seasons=2023\" --region=us-west2"
echo ""
echo "  # Two seasons:"
echo "  gcloud run jobs execute bdl-boxscore-backfill --args=\"^|^--seasons=2023,2024\" --region=us-west2"
echo ""
echo "  # Playoffs only (fast - just playoff games):"
echo "  gcloud run jobs execute bdl-boxscore-backfill --args=--playoffs-only --region=us-west2"
echo ""
echo "  # Playoffs only for specific season:"
echo "  gcloud run jobs execute bdl-boxscore-backfill --args=\"^|^--seasons=2024|--playoffs-only\" --region=us-west2"
echo ""
echo "  # Full 4-season backfill (default):"
echo "  gcloud run jobs execute bdl-boxscore-backfill --region=us-west2"
echo ""
echo "  # Skip early dates (resume from specific date):"
echo "  gcloud run jobs execute bdl-boxscore-backfill --args=--start-date=2023-10-01 --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • Downloads NBA box scores from Ball Don't Lie API for 4 seasons"
echo "  • FAST EXECUTION: 15-20 minutes for 4 seasons (~800-1000 dates)"
echo "  • Efficient: calls once per DATE (gets all games for that date)"
echo "  • Uses NBA.com schedule data from GCS to generate date lists"
echo "  • Rate limited: 0.5s between calls (conservative, BDL allows 600 req/min)"
echo "  • Resume logic: skips dates with existing data in GCS"
echo "  • Playoff filtering: --playoffs-only flag for targeted collection"
echo "  • Filters out pre-season, All-Star, and special games"
echo "  • Path: ball-dont-lie/box-scores/{YYYY-MM-DD}/"
echo "  • Job has 30-minute timeout with 1GB memory and 1 CPU"
echo "  • Default: processes all 4 seasons (2021,2022,2023,2024)"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo "  • For comma-separated seasons, use pipe delimiter: --args=\"^|^--seasons=2021,2022\""
echo ""

print_section_header "Validate results"
echo "  # Check scraped data in GCS"
echo "  gsutil ls -lh gs://nba-scraped-data/ball-dont-lie/box-scores/ | head -20"
echo ""
echo "  # Count files per season"
echo "  for year in 2021 2022 2023 2024; do"
echo "    echo \"Season \$year:\""
echo "    gsutil ls gs://nba-scraped-data/ball-dont-lie/box-scores/\$year-* | wc -l"
echo "  done"
echo ""
echo "  # Check sample date"
echo "  gsutil cat gs://nba-scraped-data/ball-dont-lie/box-scores/2024-01-15/*.json | jq '.'"
echo ""
echo "  # Validate with validation script"
echo "  ./bin/scrapers/validation/validate_bdl_boxscore.sh recent 5"
echo ""
echo "  # If processed to BigQuery, check data:"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_records, MIN(game_date) as earliest_date, MAX(game_date) as latest_date, COUNT(DISTINCT game_id) as unique_games FROM \\\`nba-props-platform.nba_raw.bdl_boxscores\\\`\""
echo ""
echo "  # Check daily coverage (if in BigQuery):"
echo "  bq query --use_legacy_sql=false \"SELECT game_date, COUNT(DISTINCT game_id) as games_count FROM \\\`nba-props-platform.nba_raw.bdl_boxscores\\\` GROUP BY game_date ORDER BY game_date DESC LIMIT 10\""

# Print final timing summary
print_deployment_summary