#!/bin/bash
# FILE: backfill_jobs/scrapers/br_rosters/deploy.sh

# Deploy Basketball Reference Season Rosters Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying Basketball Reference Season Rosters Backfill Job..."

# Use standardized scrapers backfill deployment script
./bin/scrapers/deploy/deploy_scrapers_backfill_job.sh br_rosters

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # List valid Basketball Reference team abbreviations:"
echo "  gcloud run jobs execute br-rosters-backfill --args=--list-teams --region=us-west2"
echo ""
echo "  # Small test (single team, single season):"
echo "  gcloud run jobs execute br-rosters-backfill --args=\"^|^--teams=LAL|--seasons=2024|--debug\" --region=us-west2"
echo ""
echo "  # Test with multiple teams:"
echo "  gcloud run jobs execute br-rosters-backfill --args=\"^|^--teams=LAL,GSW,BOS|--seasons=2024\" --region=us-west2"
echo ""
echo "  # Single season, all teams:"
echo "  gcloud run jobs execute br-rosters-backfill --args=\"^|^--seasons=2024|--all-teams\" --region=us-west2"
echo ""
echo "  # Two seasons, all teams:"
echo "  gcloud run jobs execute br-rosters-backfill --args=\"^|^--seasons=2024,2025|--all-teams\" --region=us-west2"
echo ""
echo "  # Full 5-season backfill (default, all teams):"
echo "  gcloud run jobs execute br-rosters-backfill --region=us-west2"
echo ""
echo "  # Re-scrape without resume (force refresh):"
echo "  gcloud run jobs execute br-rosters-backfill --args=\"^|^--seasons=2024|--all-teams|--no-resume\" --region=us-west2"
echo ""
echo "  # Production mode (saves to prod/gcs):"
echo "  gcloud run jobs execute br-rosters-backfill --args=\"^|^--seasons=2022,2023,2024,2025|--all-teams|--group=prod\" --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • Scrapes Basketball Reference season rosters for NBA teams"
echo "  • LONG-RUNNING: 8-9 hours for 5 seasons x 30 teams = 150 jobs"
echo "  • RATE LIMITED: 3.5s delays to respect Basketball Reference (20 req/min)"
echo "  • Sequential processing: one team/season at a time"
echo "  • Resume capability: skips already processed team/season combinations"
echo "  • Uses Basketball Reference team abbreviations (not NBA.com codes)"
echo "  • Default: 5 seasons (2022, 2023, 2024, 2025, 2026) x 30 teams"
echo "  • Path: basketball-reference/season-rosters/{season}/{team}.json"
echo "  • Job has 10-hour timeout with 2GB memory and 1 CPU"
echo "  • Export groups: dev (default), test, prod, gcs"
echo "  • Valid BR teams: ATL, BOS, BRK, CHO, CHI, CLE, DAL, DEN, DET, GSW,"
echo "    HOU, IND, LAC, LAL, MEM, MIA, MIL, MIN, NOP, NYK, OKC, ORL,"
echo "    PHI, PHO, POR, SAC, SAS, TOR, UTA, WAS"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo "  • For comma-separated values, use pipe delimiter: --args=\"^|^--teams=LAL,GSW|--seasons=2024,2025\""
echo ""

print_section_header "Validate results"
echo "  # Check scraped data in GCS"
echo "  gsutil ls -lh gs://nba-scraped-data/basketball-reference/season-rosters/ | head -20"
echo ""
echo "  # Count rosters per season"
echo "  for year in 2022 2023 2024 2025; do"
echo "    season=\"\$year-\$((year+1-2000))\""
echo "    count=\$(gsutil ls gs://nba-scraped-data/basketball-reference/season-rosters/\$season/*.json 2>/dev/null | wc -l)"
echo "    echo \"Season \$season: \$count rosters\""
echo "  done"
echo ""
echo "  # Check sample roster"
echo "  gsutil cat gs://nba-scraped-data/basketball-reference/season-rosters/2024-25/LAL.json | jq '.'"
echo ""
echo "  # If processed to BigQuery, check data:"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_players, COUNT(DISTINCT season_year) as seasons, COUNT(DISTINCT team) as teams, MIN(season_year) as earliest_season, MAX(season_year) as latest_season FROM \\\`nba-props-platform.nba_raw.br_rosters_current\\\`\""
echo ""
echo "  # Check team roster counts (if in BigQuery):"
echo "  bq query --use_legacy_sql=false \"SELECT team, season_year, COUNT(*) as players FROM \\\`nba-props-platform.nba_raw.br_rosters_current\\\` WHERE season_year = 2024 GROUP BY team, season_year ORDER BY team\""

# Print final timing summary
print_deployment_summary