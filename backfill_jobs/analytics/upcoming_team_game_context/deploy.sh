#!/bin/bash
# File: backfill_jobs/analytics/upcoming_team_game_context/deploy.sh
# Description: Deploy upcoming team game context processor backfill job

set -e

echo "=========================================="
echo "Deploying Upcoming Team Game Context Backfill Job"
echo "=========================================="

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Change to project root
cd "$PROJECT_ROOT"

# Check if standardized deployment script exists
if [ ! -f "./bin/analytics/deploy/deploy_analytics_processor_backfill.sh" ]; then
    echo "ERROR: Standardized deployment script not found!"
    echo "Expected: ./bin/analytics/deploy/deploy_analytics_processor_backfill.sh"
    exit 1
fi

# Use standardized deployment script
echo "Using standardized analytics backfill deployment..."
./bin/analytics/deploy/deploy_analytics_processor_backfill.sh upcoming_team_game_context

echo ""
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "Test Commands:"
echo ""
echo "  # Dry run (see what would be processed):"
echo "  gcloud run jobs execute upcoming-team-game-context-backfill \\"
echo "    --args=--dry-run,--start-date=2025-01-15 \\"
echo "    --region=us-west2"
echo ""
echo "  # Single day:"
echo "  gcloud run jobs execute upcoming-team-game-context-backfill \\"
echo "    --args=--start-date=2025-01-15,--end-date=2025-01-15 \\"
echo "    --region=us-west2"
echo ""
echo "  # Date range:"
echo "  gcloud run jobs execute upcoming-team-game-context-backfill \\"
echo "    --args=--start-date=2025-01-01,--end-date=2025-01-31 \\"
echo "    --region=us-west2"
echo ""
echo "  # Check logs:"
echo "  gcloud run jobs executions list \\"
echo "    --job=upcoming-team-game-context-backfill \\"
echo "    --region=us-west2 \\"
echo "    --limit=1"
echo ""
echo "  # View execution logs (replace EXECUTION-ID):"
echo "  gcloud beta run jobs executions logs read EXECUTION-ID \\"
echo "    --region=us-west2"
echo ""