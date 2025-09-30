#!/bin/bash
# FILE: backfill_jobs/raw/espn_team_roster/deploy.sh

# Deploy ESPN Team Roster Processor Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying ESPN Team Roster Processor Backfill Job..."

# Use standardized raw processors backfill deployment script
./bin/raw/deploy/deploy_processor_backfill_job.sh espn_team_roster

echo "Deployment complete!"
echo ""

print_section_header "Test Commands"
echo "  # Dry run (check data availability):"
echo "  gcloud run jobs execute espn-team-roster-processor-backfill --args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Dry run with limit (check first 10 files):"
echo "  gcloud run jobs execute espn-team-roster-processor-backfill --args=--dry-run,--limit=10 --region=us-west2"
echo ""
echo "  # Small test (3 days):"
echo "  gcloud run jobs execute espn-team-roster-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-03 --region=us-west2"
echo ""
echo "  # Small test with limit (first 5 files):"
echo "  gcloud run jobs execute espn-team-roster-processor-backfill --args=--limit=5 --region=us-west2"
echo ""
echo "  # Weekly processing:"
echo "  gcloud run jobs execute espn-team-roster-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Monthly processing:"
echo "  gcloud run jobs execute espn-team-roster-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2"
echo ""
echo "  # Full historical backfill:"
echo "  gcloud run jobs execute espn-team-roster-processor-backfill --args=--start-date=2024-01-01,--end-date=2025-12-31 --region=us-west2"
echo ""
echo "  # Use defaults (processes last 30 days):"
echo "  gcloud run jobs execute espn-team-roster-processor-backfill --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • Processes ESPN team roster data from GCS to BigQuery"
echo "  • Backup data source only (limited historical coverage)"
echo "  • Part of Morning Operations workflow (8 AM PT daily)"
echo "  • One file per team per day (30 NBA teams)"
echo "  • Path: espn/rosters/{date}/team_{abbr}/{timestamp}.json"
echo "  • Job has 1-hour timeout with 4GB memory and 2 CPUs"
echo "  • Default behavior: processes last 30 days if no dates specified"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo "  • For comma-separated values, use custom delimiter: --args=\"^|^--param=val1,val2|--other=val\""
echo ""

print_section_header "Validate results"
echo "  # Check recent data in BigQuery"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_records, MIN(roster_date) as earliest_date, MAX(roster_date) as latest_date, COUNT(DISTINCT team_abbr) as unique_teams FROM \\\`nba-props-platform.nba_raw.espn_team_rosters\\\`\""
echo ""
echo "  # Check daily team coverage"
echo "  bq query --use_legacy_sql=false \"SELECT roster_date, COUNT(DISTINCT team_abbr) as teams_count FROM \\\`nba-props-platform.nba_raw.espn_team_rosters\\\` GROUP BY roster_date ORDER BY roster_date DESC LIMIT 10\""

# Print final timing summary
print_deployment_summary