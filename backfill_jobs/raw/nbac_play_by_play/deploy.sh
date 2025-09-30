#!/bin/bash
# FILE: backfill_jobs/raw/nbac_play_by_play/deploy.sh

# Deploy NBA.com Play-by-Play Processor Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying NBA.com Play-by-Play Processor Backfill Job..."

# Use standardized raw processors backfill deployment script
./bin/raw/deploy/deploy_processor_backfill_job.sh nbac_play_by_play

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (check data availability):"
echo "  gcloud run jobs execute nbac-play-by-play-processor-backfill --args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Dry run with limit (check first 10 files):"
echo "  gcloud run jobs execute nbac-play-by-play-processor-backfill --args=--dry-run,--limit=10 --region=us-west2"
echo ""
echo "  # Small test (3 days):"
echo "  gcloud run jobs execute nbac-play-by-play-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-03 --region=us-west2"
echo ""
echo "  # Small test with limit (first 5 files):"
echo "  gcloud run jobs execute nbac-play-by-play-processor-backfill --args=--limit=5 --region=us-west2"
echo ""
echo "  # Weekly processing:"
echo "  gcloud run jobs execute nbac-play-by-play-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Monthly processing:"
echo "  gcloud run jobs execute nbac-play-by-play-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2"
echo ""
echo "  # Full season backfill (2023-24):"
echo "  gcloud run jobs execute nbac-play-by-play-processor-backfill --args=--start-date=2023-10-17,--end-date=2024-06-17 --region=us-west2"
echo ""
echo "  # Full historical backfill:"
echo "  gcloud run jobs execute nbac-play-by-play-processor-backfill --args=--start-date=2021-10-01,--end-date=2025-06-30 --region=us-west2"
echo ""
echo "  # Use defaults (processes current NBA season to date):"
echo "  gcloud run jobs execute nbac-play-by-play-processor-backfill --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • Processes NBA.com play-by-play data from GCS to BigQuery"
echo "  • LARGE DATA: 500-800 events per game with detailed play information"
echo "  • High resource requirements: 1-hour timeout, 8GB memory, 4 CPUs"
echo "  • Path: nba-com/play-by-play/{date}/game_{gameId}/*.json"
echo "  • Multiple game files per date during NBA season (~5-15 games/day)"
echo "  • Default behavior: processes current NBA season (October to today)"
echo "  • Event types: shots, rebounds, fouls, turnovers, substitutions, etc."
echo "  • Critical for detailed game analysis and player performance tracking"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo "  • For comma-separated values, use custom delimiter: --args=\"^|^--param=val1,val2|--other=val\""
echo ""

print_section_header "Validate results"
echo "  # Check recent data in BigQuery"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_events, MIN(game_date) as earliest_date, MAX(game_date) as latest_date, COUNT(DISTINCT game_id) as unique_games FROM \\\`nba-props-platform.nba_raw.nbac_play_by_play\\\`\""
echo ""
echo "  # Check daily game coverage"
echo "  bq query --use_legacy_sql=false \"SELECT game_date, COUNT(DISTINCT game_id) as games_count, COUNT(*) as total_events FROM \\\`nba-props-platform.nba_raw.nbac_play_by_play\\\` GROUP BY game_date ORDER BY game_date DESC LIMIT 10\""
echo ""
echo "  # Check average events per game (should be ~500-800)"
echo "  bq query --use_legacy_sql=false \"SELECT AVG(events_per_game) as avg_events FROM (SELECT game_id, COUNT(*) as events_per_game FROM \\\`nba-props-platform.nba_raw.nbac_play_by_play\\\` GROUP BY game_id)\""

# Print final timing summary
print_deployment_summary