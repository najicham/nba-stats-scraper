#!/bin/bash
# FILE: processor_backfill/nbac_gamebook/deploy.sh

# Deploy NBA.com Gamebook Processor Backfill Job

set -e

echo "Deploying NBA.com Gamebook Processor Backfill Job..."

# Use standardized processor backfill deployment script
./bin/processors/deploy/deploy_processor_backfill_job.sh nbac_gamebook

echo "Deployment complete!"
echo ""
echo "Test Commands:"
echo "  # Dry run (5-day test with problematic teams):"
echo "  gcloud run jobs execute nbac-gamebook-processor-backfill --args=--date-range=2024-01-15:2024-01-19,--team-filter=BKN,PHX,CHA,NYK,--dry-run --region=us-west2"
echo ""
echo "  # Small test (5 days, problematic teams):"
echo "  gcloud run jobs execute nbac-gamebook-processor-backfill --args=--date-range=2024-01-15:2024-01-19,--team-filter=BKN,PHX,CHA,NYK --region=us-west2"
echo ""
echo "  # Monthly test (January 2024):"
echo "  gcloud run jobs execute nbac-gamebook-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2"
echo ""
echo "  # Full historical backfill (3.5 years):"
echo "  gcloud run jobs execute nbac-gamebook-processor-backfill --args=--start-date=2021-10-01,--end-date=2025-06-30 --region=us-west2"
echo ""
echo "  # Team-specific reruns:"
echo "  gcloud run jobs execute nbac-gamebook-processor-backfill --args=--start-date=2023-01-01,--end-date=2023-12-31,--team-filter=BKN,PHX,CHA --region=us-west2"
echo ""
echo "Monitor logs:"
echo "  ./bin/processor_backfill/nbac_gamebook_backfill_monitor.sh"
echo ""
echo "Or monitor specific execution:"
echo "  gcloud run jobs executions logs [execution-id] --region=us-west2 --follow"
echo ""
echo "Validate results:"
echo "  # Check resolution performance"
echo "  bq query --use_legacy_sql=false \"SELECT * FROM \\\`nba_processing.resolution_performance\\\` ORDER BY processing_timestamp DESC LIMIT 5\""
echo ""
echo "  # Check data quality"
echo "  bq query --use_legacy_sql=false \"SELECT player_status, name_resolution_status, COUNT(*) as count FROM \\\`nba_raw.nbac_gamebook_player_stats\\\` WHERE DATE(_PARTITIONTIME) >= CURRENT_DATE() GROUP BY 1,2 ORDER BY 1,2\""
