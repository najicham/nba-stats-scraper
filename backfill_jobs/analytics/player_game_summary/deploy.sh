#!/bin/bash
# FILE: analytics_backfill/player_game_summary/deploy.sh

# Deploy Player Game Summary Analytics Processor Backfill Job

set -e

# Source shared wrapper functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

# Start deployment timing
start_deployment_timer

echo "Deploying Player Game Summary Analytics Processor Backfill Job..."

# Use standardized analytics processors backfill deployment script
./bin/analytics/deploy/deploy_analytics_processor_backfill.sh player_game_summary

echo "Deployment complete!"
echo ""

print_section_header "Test Commands (Day-by-Day Processing)"
echo "  # Dry run (check data availability):"
echo "  gcloud run jobs execute player-game-summary-analytics-backfill --args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Small test (3 days):"
echo "  gcloud run jobs execute player-game-summary-analytics-backfill --args=--start-date=2024-01-01,--end-date=2024-01-03 --region=us-west2"
echo ""
echo "  # Weekly processing:"
echo "  gcloud run jobs execute player-game-summary-analytics-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2"
echo ""
echo "  # Monthly processing (January 2024):"
echo "  gcloud run jobs execute player-game-summary-analytics-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2"
echo ""
echo "  # Large range processing (Q1 2024):"
echo "  gcloud run jobs execute player-game-summary-analytics-backfill --args=--start-date=2024-01-01,--end-date=2024-03-31 --region=us-west2"
echo ""
echo "  # Full historical backfill (processes day-by-day automatically):"
echo "  gcloud run jobs execute player-game-summary-analytics-backfill --args=--start-date=2021-10-01,--end-date=2024-12-31 --region=us-west2"
echo ""

print_section_header "Monitor logs"
echo "  gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow"
echo ""

print_section_header "Notes"
echo "  • This processor uses day-by-day processing to avoid BigQuery size limits"
echo "  • Large date ranges are automatically processed one day at a time for optimal performance"
echo "  • Args use equals syntax (--param=value) with no spaces or quotes"
echo "  • For comma-separated values, use custom delimiter: --args=\"^|^--param=val1,val2|--other=val\""
echo ""

print_section_header "Validate results"
echo "  ./bin/analytics/validation/validate_analytics_data.sh"

# Print final timing summary
print_deployment_summary