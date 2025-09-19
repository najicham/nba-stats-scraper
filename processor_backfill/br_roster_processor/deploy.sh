#!/bin/bash
# FILE: processor_backfill/br_roster_processor/deploy.sh

# Deploy Basketball Reference Roster Processor Backfill Job

set -e

echo "Deploying Basketball Reference Roster Processor Backfill Job..."

# Use standardized processor backfill deployment script
./bin/processors/deploy/deploy_processor_backfill_job.sh br_roster_processor

echo "Deployment complete!"
echo ""
echo "Test Commands:"
echo "  # Dry run (current season with a few teams):"
echo "  gcloud run jobs execute br-roster-processor-backfill --args=--season=2024,--teams=LAL,GSW,BOS,MIA,--dry-run --region=us-west2"
echo ""
echo "  # Small test (current season, specific teams):"
echo "  gcloud run jobs execute br-roster-processor-backfill --args=--season=2024,--teams=LAL,GSW,BOS,MIA --region=us-west2"
echo ""
echo "  # Single season, all teams:"
echo "  gcloud run jobs execute br-roster-processor-backfill --args=--season=2024 --region=us-west2"
echo ""
echo "  # Multiple seasons (last 3 seasons):"
echo "  for season in 2022 2023 2024; do"
echo "    echo \"Processing season \$season...\""
echo "    gcloud run jobs execute br-roster-processor-backfill --args=--season=\$season --region=us-west2"
echo "  done"
echo ""
echo "  # Historical backfill (2021-2024 seasons):"
echo "  for season in 2021 2022 2023 2024; do"
echo "    echo \"Processing season \$season...\""
echo "    gcloud run jobs execute br-roster-processor-backfill --args=--season=\$season --region=us-west2"
echo "  done"
echo ""
echo "  # Specific teams across multiple seasons:"
echo "  for season in 2022 2023 2024; do"
echo "    gcloud run jobs execute br-roster-processor-backfill --args=--season=\$season,--teams=LAL,GSW,BOS --region=us-west2"
echo "  done"
echo ""
echo "Monitor logs:"
echo "  ./bin/processor_backfill/br_roster_processor_backfill_monitor.sh"
echo ""
echo "Or monitor specific execution:"
echo "  gcloud run jobs executions logs [execution-id] --region=us-west2 --follow"
echo ""
echo "Validate results:"
echo "  # Check roster data processing stats"
echo "  bq query --use_legacy_sql=false \"SELECT season_year, team_abbrev, COUNT(*) as player_count FROM \\\`nba_raw.basketball_ref_rosters\\\` WHERE DATE(_PARTITIONTIME) >= CURRENT_DATE() - 7 GROUP BY 1,2 ORDER BY 1,2\""
echo ""
echo "  # Check recent processing results"
echo "  bq query --use_legacy_sql=false \"SELECT * FROM \\\`nba_processing.resolution_performance\\\` WHERE processor_name LIKE '%roster%' ORDER BY processing_timestamp DESC LIMIT 10\""
echo ""
echo "  # Verify roster completeness by season"
echo "  bq query --use_legacy_sql=false \"SELECT season_year, COUNT(DISTINCT team_abbrev) as teams_processed, COUNT(*) as total_players FROM \\\`nba_raw.basketball_ref_rosters\\\` GROUP BY 1 ORDER BY 1 DESC\""
