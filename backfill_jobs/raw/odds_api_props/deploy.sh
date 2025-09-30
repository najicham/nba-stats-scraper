#!/bin/bash
# FILE: backfill_jobs/raw/odds_api_props/deploy.sh

# Deploy Odds API Props Processor Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying Odds API Props Processor Backfill Job..."

# Use standardized raw processors backfill deployment script
./bin/raw/deploy/deploy_processor_backfill_job.sh odds_api_props

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (check data availability for date range):"
echo "  gcloud run jobs execute odds-api-props-backfill --args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Dry run for specific dates:"
echo "  gcloud run jobs execute odds-api-props-backfill --args=\"^|^--dry-run|--dates=2024-01-01,2024-01-15,2024-02-01\" --region=us-west2"
echo ""
echo "  # Small test (3 days):"
echo "  gcloud run jobs execute odds-api-props-backfill --args=--start-date=2024-01-01,--end-date=2024-01-03 --region=us-west2"
echo ""
echo "  # Process specific dates only:"
echo "  gcloud run jobs execute odds-api-props-backfill --args=\"^|^--dates=2024-01-01,2024-01-15,2024-02-01\" --region=us-west2"
echo ""
echo "  # Weekly processing:"
echo "  gcloud run jobs execute odds-api-props-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Monthly processing:"
echo "  gcloud run jobs execute odds-api-props-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2"
echo ""
echo "  # Season backfill (2023-24):"
echo "  gcloud run jobs execute odds-api-props-backfill --args=--start-date=2023-10-01,--end-date=2024-06-30 --region=us-west2"
echo ""
echo "  # Full historical backfill (May 2023 to April 2025):"
echo "  gcloud run jobs execute odds-api-props-backfill --args=--start-date=2023-05-01,--end-date=2025-04-30 --region=us-west2"
echo ""
echo "  # With custom parallelism (8 workers, 200 batch size):"
echo "  gcloud run jobs execute odds-api-props-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31,--max-workers=8,--batch-size=200 --region=us-west2"
echo ""
echo "  # Use defaults (processes May 2023 to April 2025):"
echo "  gcloud run jobs execute odds-api-props-backfill --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • Processes Odds API player props data from GCS to BigQuery"
echo "  • LARGE-SCALE BACKFILL: May 2023 through 2024-25 season coverage"
echo "  • Parallel processing: 4 workers by default (configurable with --max-workers)"
echo "  • Batch processing: 100 files per batch (configurable with --batch-size)"
echo "  • Two path patterns: odds-api/player-props/ and odds-api/player-props-history/"
echo "  • Tracks unique games, players, and bookmakers across all files"
echo "  • Job has 1-hour timeout with 4GB memory and 2 CPUs"
echo "  • Multiple daily snapshots: processes chronologically, latest data preferred"
echo "  • Comprehensive statistics: rows loaded, games, players, bookmakers"
echo "  • Can process specific dates or date ranges"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo "  • For comma-separated dates, use pipe delimiter: --args=\"^|^--dates=2024-01-01,2024-01-15\""
echo ""

print_section_header "Validate results"
echo "  # Check recent data in BigQuery"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_records, MIN(commence_time) as earliest_date, MAX(commence_time) as latest_date, COUNT(DISTINCT game_id) as unique_games, COUNT(DISTINCT player_name) as unique_players FROM \\\`nba-props-platform.nba_raw.odds_api_props\\\`\""
echo ""
echo "  # Check daily coverage and bookmakers"
echo "  bq query --use_legacy_sql=false \"SELECT DATE(commence_time) as game_date, COUNT(*) as total_props, COUNT(DISTINCT game_id) as games_count, COUNT(DISTINCT bookmaker) as bookmakers_count FROM \\\`nba-props-platform.nba_raw.odds_api_props\\\` GROUP BY game_date ORDER BY game_date DESC LIMIT 10\""
echo ""
echo "  # Check bookmaker distribution"
echo "  bq query --use_legacy_sql=false \"SELECT bookmaker, COUNT(*) as prop_count, COUNT(DISTINCT game_id) as games_covered FROM \\\`nba-props-platform.nba_raw.odds_api_props\\\` WHERE DATE(commence_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) GROUP BY bookmaker ORDER BY prop_count DESC\""

# Print final timing summary
print_deployment_summary