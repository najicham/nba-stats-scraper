#!/bin/bash
# FILE: backfill_jobs/reference/nba_players_registry/deploy.sh

# Deploy NBA Players Registry Processor Backfill Job

set -e

echo "Deploying NBA Players Registry Processor Backfill Job..."

# Use standardized reference processors backfill deployment script
./bin/reference/deploy/deploy_reference_processor_backfill.sh nba_players_registry

echo "Deployment complete!"
echo ""
echo "Test Commands (Registry Building):"
echo "  # Safe first test (summary only):"
echo "  gcloud run jobs execute nba-players-registry-processor-backfill --args=--summary-only --region=us-west2"
echo ""
echo "  # Single season test:"
echo "  gcloud run jobs execute nba-players-registry-processor-backfill --args=--season=2024-25 --region=us-west2"
echo ""
echo "  # Specific seasons:"
echo "  gcloud run jobs execute nba-players-registry-processor-backfill --args=--seasons=2023-24,2024-25 --region=us-west2"
echo ""
echo "  # Date range processing (incremental updates):"
echo "  gcloud run jobs execute nba-players-registry-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2"
echo ""
echo "  # Full historical backfill (4+ years of gamebook data):"
echo "  gcloud run jobs execute nba-players-registry-processor-backfill --args=--all-seasons --region=us-west2"
echo ""
echo "Monitor logs:"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""
echo "Usage Scenarios:"
echo "  • Summary Only: Check current registry status without processing"
echo "  • Single Season: Build/update registry for specific season"
echo "  • Historical Backfill: Process all available gamebook data (recommended first run)"
echo "  • Date Range: Incremental updates for specific dates"
echo "  • Multiple Seasons: Process several specific seasons"
echo ""
echo "Notes:"
echo "  • Historical backfill processes 4+ years of NBA.com gamebook data"
echo "  • Registry is used by the name resolution system for player identification"
echo "  • Job has 2-hour timeout and 8GB memory for large dataset processing"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo ""
echo "Validate results:"
echo "  # Check registry summary"
echo "  gcloud run jobs execute nba-players-registry-processor-backfill --args=--summary-only --region=us-west2"
echo ""
echo "  # Query registry directly"
echo "  bq query --use_legacy_sql=false \"SELECT COUNT(*) as total_records, COUNT(DISTINCT player_lookup) as unique_players, COUNT(DISTINCT season) as seasons FROM \\\`nba-props-platform.nba_reference.nba_players_registry\\\`\""