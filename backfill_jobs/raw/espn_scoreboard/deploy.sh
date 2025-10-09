#!/bin/bash
# FILE: backfill_jobs/raw/espn_scoreboard/deploy.sh

# Deploy ESPN Scoreboard Processor Backfill Job (Schedule-Based Version)

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying ESPN Scoreboard Processor Backfill Job (Schedule-Based)..."

# Use standardized raw processors backfill deployment script
./bin/raw/deploy/deploy_processor_backfill_job.sh espn_scoreboard

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (check what would be processed):"
echo "  gcloud run jobs execute espn-scoreboard-processor-backfill --args=--dry-run --region=us-west2"
echo ""
echo "  # Dry run with limit (first 10 game dates):"
echo "  gcloud run jobs execute espn-scoreboard-processor-backfill --args=--dry-run,--limit=10 --region=us-west2"
echo ""
echo "  # Dry run for specific season:"
echo "  gcloud run jobs execute espn-scoreboard-processor-backfill --args=--dry-run,--seasons=2024 --region=us-west2"
echo ""
echo "  # Small test (first 5 dates):"
echo "  gcloud run jobs execute espn-scoreboard-processor-backfill --args=--limit=5 --region=us-west2"
echo ""
echo "  # Process specific date range:"
echo "  gcloud run jobs execute espn-scoreboard-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2"
echo ""
echo "  # Process single season:"
echo "  gcloud run jobs execute espn-scoreboard-processor-backfill --args=--seasons=2024 --region=us-west2"
echo ""
echo "  # Process two seasons:"
echo "  gcloud run jobs execute espn-scoreboard-processor-backfill --args=--seasons=2023,2024 --region=us-west2"
echo ""
echo "  # Full historical backfill (all 4 seasons, ~843 game dates):"
echo "  gcloud run jobs execute espn-scoreboard-processor-backfill --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Key Features"
echo "  ✅ Schedule-based: Only processes actual game dates (skips ~500 off-days)"
echo "  ✅ Resume logic: Skips dates already in BigQuery"
echo "  ✅ Missing file detection: Reports dates with missing ESPN data"
echo "  ✅ Multi-season support: Process any combination of seasons 2021-2024"
echo "  ✅ 37% faster: Fewer GCS operations than date-range approach"
echo ""

print_section_header "Performance"
echo "  • Reads schedule once per season (4 reads total)"
echo "  • Processes only game dates (~843 dates vs 1343 total dates)"
echo "  • Expected duration: ~20-30 minutes for full backfill"
echo "  • Resume-friendly: Can restart without reprocessing"
echo ""

print_section_header "Notes"
echo "  • Args use comma-separated values (no spaces): --args=--param1=val1,--param2=val2"
echo "  • Seasons format: 2021,2022,2023,2024 (start year of season)"
echo "  • Date format: YYYY-MM-DD"
echo "  • Job timeout: 30 minutes (sufficient for all 4 seasons)"
echo ""

print_section_header "Validate results"
echo "  # Check data in BigQuery"
echo "  bq query --use_legacy_sql=false \\"
echo "    \"SELECT COUNT(*) as total_games, \\"
echo "    COUNT(DISTINCT game_date) as unique_dates, \\"
echo "    MIN(game_date) as earliest, \\"
echo "    MAX(game_date) as latest \\"
echo "    FROM \\\`nba-props-platform.nba_raw.espn_scoreboard\\\`\""
echo ""
echo "  # Check by season"
echo "  bq query --use_legacy_sql=false \\"
echo "    \"SELECT \\"
echo "    EXTRACT(YEAR FROM game_date) as year, \\"
echo "    COUNT(*) as games, \\"
echo "    COUNT(DISTINCT game_date) as dates \\"
echo "    FROM \\\`nba-props-platform.nba_raw.espn_scoreboard\\\` \\"
echo "    GROUP BY year \\"
echo "    ORDER BY year\""

# Print final timing summary
print_deployment_summary