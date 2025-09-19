#!/bin/bash
# FILE: backfill/br_rosters/deploy.sh

# Deploy Basketball Reference Season Roster Backfill Job

set -e

echo "Deploying Basketball Reference Season Roster Backfill Job..."

# Use standardized scrapers backfill deployment script
./bin/scrapers/deploy/deploy_scrapers_backfill_job.sh backfill/br_rosters/job-config.env

echo "Deployment complete!"
echo ""
echo "Test Commands:"
echo "  # Validation test (Charlie Brown Jr. fix verification):"
echo "  gcloud run jobs execute br-rosters-backfill --args=\"^|^--seasons=2024|--teams=NYK|--group=dev|--debug\" --region=us-west2"
echo ""
echo "  # Small test (3 teams, current season):"
echo "  gcloud run jobs execute br-rosters-backfill --args=\"^|^--seasons=2026|--teams=NYK,LAL,MEM|--group=dev|--debug\" --region=us-west2"
echo ""
echo "  # Single season backfill:"
echo "  gcloud run jobs execute br-rosters-backfill --args=\"^|^--seasons=2026|--all-teams|--group=prod\" --region=us-west2"
echo ""
echo "  # Recent seasons (last 2 years):"
echo "  gcloud run jobs execute br-rosters-backfill --args=\"^|^--seasons=2025,2026|--all-teams|--group=prod\" --region=us-west2"
echo ""
echo "  # Full historical backfill (150 jobs, ~8-9 hours):"
echo "  gcloud run jobs execute br-rosters-backfill --args=\"^|^--seasons=2022,2023,2024,2025,2026|--all-teams|--group=prod\" --region=us-west2"
echo ""
echo "Note: Uses custom delimiter syntax (^|^) to handle comma-separated values properly in Cloud Run jobs."
echo "Estimated duration: 8-9 hours for full backfill due to Basketball Reference rate limiting (3.5s delays)."