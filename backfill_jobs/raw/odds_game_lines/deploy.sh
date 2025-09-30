#!/bin/bash
# FILE: backfill_jobs/raw/odds_game_lines/deploy.sh

# Deploy Odds API Game Lines Processor Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying Odds API Game Lines Processor Backfill Job..."

# Use standardized raw processors backfill deployment script
./bin/raw/deploy/deploy_processor_backfill_job.sh odds_game_lines

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (check data availability):"
echo "  gcloud run jobs execute odds-game-lines-processor-backfill --args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Dry run with limit (check first 10 files):"
echo "  gcloud run jobs execute odds-game-lines-processor-backfill --args=--dry-run,--limit=10 --region=us-west2"
echo ""
echo "  # Small test (3 days):"
echo "  gcloud run jobs execute odds-game-lines-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-03 --region=us-west2"
echo ""
echo "  # Small test with limit (max 50 files):"
echo "  gcloud run jobs execute odds-game-lines-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-03,--limit=50 --region=us-west2"
echo ""
echo "  # Weekly processing:"
echo "  gcloud run jobs execute odds-game-lines-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Monthly processing:"
echo "  gcloud run jobs execute odds-game-lines-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2"
echo ""
echo "  # Full historical backfill:"
echo "  gcloud run jobs execute odds-game-lines-processor-backfill --args=--start-date=2021-10-01,--end-date=2025-06-30 --region=us-west2"
echo ""
echo "  # Use defaults (processes full range from job-config.env):"
echo "  gcloud run jobs execute odds-game-lines-processor-backfill --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • Processes Odds API game lines history data from GCS to BigQuery"
echo "  • Contains pre-game odds snapshots with point spreads, totals, and moneylines"
echo "  • Data sourced from gs://nba-scraped-data/odds-api/game-lines-history/"
echo "  • Each file contains multiple sportsbook odds for games on that date"
echo "  • Many nested records per file (multiple bookmakers per game)"
echo "  • Job has 1-hour timeout with 4GB memory and 2 CPUs"
echo "  • Historical coverage from 2021-22 season through current season"
echo "  • Includes odds from major sportsbooks: DraftKings, FanDuel, BetMGM, etc."
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo ""

print_section_header "Validate results"
echo "  # Check recent data in BigQuery"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_records, MIN(snapshot_timestamp) as earliest_snapshot, MAX(snapshot_timestamp) as latest_snapshot, COUNT(DISTINCT game_id) as unique_games, COUNT(DISTINCT bookmaker_key) as unique_bookmakers FROM \\\`nba-props-platform.nba_raw.odds_game_lines\\\`\""
echo ""
echo "  # Check odds by bookmaker:"
echo "  bq query --use_legacy_sql=false \"SELECT bookmaker_key, COUNT(*) as odds_count FROM \\\`nba-props-platform.nba_raw.odds_game_lines\\\` GROUP BY bookmaker_key ORDER BY odds_count DESC\""

# Print final timing summary
print_deployment_summary