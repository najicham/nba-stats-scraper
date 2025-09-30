#!/bin/bash
# FILE: backfill_jobs/scrapers/bdb_play_by_play/deploy.sh

# Deploy BigDataBall Play-by-Play Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying BigDataBall Play-by-Play Backfill Job..."

# Use standardized scrapers backfill deployment script
./bin/scrapers/deploy/deploy_scrapers_backfill_job.sh bdb_play_by_play

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (see what would be discovered and downloaded):"
echo "  gcloud run jobs execute bdb-play-by-play-backfill --args=--dry-run --region=us-west2"
echo ""
echo "  # Test with limited date range (1 month):"
echo "  gcloud run jobs execute bdb-play-by-play-backfill --args=--start_date=2024-10-01,--end_date=2024-11-01 --region=us-west2"
echo ""
echo "  # Test with shorter date range (1 week):"
echo "  gcloud run jobs execute bdb-play-by-play-backfill --args=--start_date=2024-10-01,--end_date=2024-10-07 --region=us-west2"
echo ""
echo "  # Full 2024-25 season backfill (default dates):"
echo "  gcloud run jobs execute bdb-play-by-play-backfill --region=us-west2"
echo ""
echo "  # Custom date range:"
echo "  gcloud run jobs execute bdb-play-by-play-backfill --args=--start_date=2024-12-01,--end_date=2025-04-30 --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • Downloads BigDataBall enhanced play-by-play for 2024-25 NBA season"
echo "  • Two-phase process: discovery (find games) + download (get CSV files)"
echo "  • Default date range: 2024-10-01 to 2025-08-19 (full season + playoffs)"
echo "  • Estimated ~1200 games total, 4-8 hour runtime"
echo "  • Resume logic: automatically skips games already in GCS"
echo "  • Rate limited: 2 seconds per game for Google Drive API stability"
echo "  • Path: big-data-ball/2024-25/{date}/game_{game_id}/"
echo "  • Job has 8-hour timeout with 2GB memory and 1 CPU"
echo "  • Discovery uses weekly batches for efficiency"
echo "  • Downloads enhanced play-by-play CSV with detailed tracking data"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo ""

print_section_header "Validate results"
echo "  # Check scraped data in GCS"
echo "  gsutil ls -lh gs://nba-scraped-data/big-data-ball/2024-25/ | head -20"
echo ""
echo "  # Count total games downloaded"
echo "  gsutil ls -r gs://nba-scraped-data/big-data-ball/2024-25/**/game_* | wc -l"
echo ""
echo "  # Check sample game data"
echo "  gsutil ls gs://nba-scraped-data/big-data-ball/2024-25/2024-10-*/game_*/enhanced_pbp.csv"
echo ""
echo "  # List games by month"
echo "  for month in 10 11 12; do"
echo "    count=\$(gsutil ls gs://nba-scraped-data/big-data-ball/2024-25/2024-\$month-*/game_*/ 2>/dev/null | wc -l)"
echo "    echo \"2024-\$month: \$count games\""
echo "  done"
echo ""
echo "  # If processed to BigQuery, check data:"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_plays, COUNT(DISTINCT game_id) as unique_games, MIN(game_date) as earliest_date, MAX(game_date) as latest_date FROM \\\`nba-props-platform.nba_raw.bdb_play_by_play\\\`\""

# Print final timing summary
print_deployment_summary