#!/bin/bash
# FILE: backfill_jobs/raw/br_roster_processor/deploy.sh

# Deploy Basketball Reference Roster Processor Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying Basketball Reference Roster Processor Backfill Job..."

# Use standardized raw processors backfill deployment script
./bin/raw/deploy/deploy_processor_backfill_job.sh br_roster_processor

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (check data availability for current season):"
echo "  gcloud run jobs execute br-roster-processor-backfill --args=--dry-run,--season=2024 --region=us-west2"
echo ""
echo "  # Dry run for specific teams:"
echo "  gcloud run jobs execute br-roster-processor-backfill --args=\"^|^--dry-run|--season=2024|--teams=LAL,GSW,BOS\" --region=us-west2"
echo ""
echo "  # Process single season (all teams):"
echo "  gcloud run jobs execute br-roster-processor-backfill --args=--season=2024 --region=us-west2"
echo ""
echo "  # Process single season (specific teams):"
echo "  gcloud run jobs execute br-roster-processor-backfill --args=\"^|^--season=2024|--teams=LAL,GSW,BOS,MIA\" --region=us-west2"
echo ""
echo "  # Process single team across one season:"
echo "  gcloud run jobs execute br-roster-processor-backfill --args=\"^|^--season=2023|--teams=LAL\" --region=us-west2"
echo ""
echo "  # Full historical backfill (requires manual execution per season):"
echo "  # Note: Must run separately for each season (2021, 2022, 2023, 2024)"
echo "  gcloud run jobs execute br-roster-processor-backfill --args=--season=2021 --region=us-west2"
echo "  gcloud run jobs execute br-roster-processor-backfill --args=--season=2022 --region=us-west2"
echo "  gcloud run jobs execute br-roster-processor-backfill --args=--season=2023 --region=us-west2"
echo "  gcloud run jobs execute br-roster-processor-backfill --args=--season=2024 --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • Processes Basketball Reference roster data by NBA season"
echo "  • Season format: Use year season starts (e.g., 2023 for 2023-24 season)"
echo "  • Processes 30 NBA teams per season (or specified teams)"
echo "  • Path: basketball-ref/season-rosters/{season}/{team}.json"
echo "  • Job has 1-hour timeout with 2GB memory and 1 CPU"
echo "  • Valid teams: ATL, BOS, BRK, CHO, CHI, CLE, DAL, DEN, DET, GSW,"
echo "    HOU, IND, LAC, LAL, MEM, MIA, MIL, MIN, NOP, NYK, OKC, ORL,"
echo "    PHI, PHX, POR, SAC, SAS, TOR, UTA, WAS"
echo "  • For comma-separated teams, use pipe delimiter: --args=\"^|^--teams=LAL,GSW|--season=2024\""
echo "  • Unlike other processors, this uses --season (not --start-date/--end-date)"
echo ""

print_section_header "Validate results"
echo "  # Check recent data in BigQuery"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_records, COUNT(DISTINCT season_year) as seasons, COUNT(DISTINCT team) as teams, MIN(season_year) as earliest_season, MAX(season_year) as latest_season FROM \\\`nba-props-platform.nba_raw.br_rosters_current\\\`\""
echo ""
echo "  # Check specific season"
echo "  bq query --use_legacy_sql=false \"SELECT team, COUNT(*) as players FROM \\\`nba-props-platform.nba_raw.br_rosters_current\\\` WHERE season_year = 2024 GROUP BY team ORDER BY team\""

# Print final timing summary
print_deployment_summary