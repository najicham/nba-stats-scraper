#!/bin/bash
set -euo pipefail
# FILE: bin/backfill/bdb_play_by_play_monitor.sh
# BigDataBall 2024-25 Enhanced Play-by-Play Backfill Monitoring Script

PROJECT_ID="${GCS_PROJECT_ID:-nba-props-platform}"
REGION="${GCP_REGION:-us-west2}"
JOB_NAME="bdb-play-by-play-backfill"

echo "🏀 BigDataBall 2024-25 Enhanced Play-by-Play Backfill Status"
echo "=========================================================="
echo ""

# Check job executions
echo "Recent job executions:"
gcloud run jobs executions list \
    --job=${JOB_NAME} \
    --region=${REGION} \
    --project=${PROJECT_ID} \
    --limit=5

echo ""

# Get the latest execution
LATEST_EXECUTION=$(gcloud run jobs executions list \
    --job=${JOB_NAME} \
    --region=${REGION} \
    --project=${PROJECT_ID} \
    --limit=1 \
    --format="value(metadata.name)" 2>/dev/null)

if [ -n "$LATEST_EXECUTION" ]; then
    echo "Latest execution: $LATEST_EXECUTION"
    echo ""
    
    # Show execution details
    echo "Execution status:"
    gcloud run jobs executions describe ${LATEST_EXECUTION} \
        --region=${REGION} \
        --project=${PROJECT_ID} \
        --format="table(metadata.name,status.conditions[0].type,status.conditions[0].status,status.startTime,status.completionTime)"
    
    echo ""
    echo "Recent logs (last 50 lines):"
    gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=${JOB_NAME} AND resource.labels.location=${REGION}" \
        --limit=50 \
        --format="value(timestamp,severity,textPayload)" \
        --project=${PROJECT_ID} \
        --freshness=1d | sort
else
    echo "No executions found for job ${JOB_NAME}"
fi

echo ""
echo "📊 BigDataBall GCS Data Status"
echo "============================="

# Check what data exists in GCS
echo ""
echo "Checking 2024-25 season data in GCS..."

# Count existing dates
EXISTING_DATES=$(gcloud storage ls gs://nba-scraped-data/big-data-ball/2024-25/ 2>/dev/null | wc -l || echo "0")
echo "Existing dates in 2024-25: $EXISTING_DATES"

if [ "$EXISTING_DATES" -gt 0 ]; then
    echo ""
    echo "Sample of existing dates:"
    gcloud storage ls gs://nba-scraped-data/big-data-ball/2024-25/ | head -10
    
    echo ""
    echo "Recent dates added:"
    gcloud storage ls gs://nba-scraped-data/big-data-ball/2024-25/ | tail -5
    
    # Count total games
    echo ""
    echo "Counting total games in 2024-25..."
    TOTAL_GAMES=$(gcloud storage ls -r gs://nba-scraped-data/big-data-ball/2024-25/*/game_*/ 2>/dev/null | wc -l || echo "0")
    echo "Total games collected: $TOTAL_GAMES"
    
    # Check file sizes
    echo ""
    echo "Sample file sizes (should be ~2-5MB each):"
    gcloud storage du gs://nba-scraped-data/big-data-ball/2024-25/ | tail -5
else
    echo "No 2024-25 data found in GCS yet"
fi

echo ""
echo "📈 Progress Comparison"
echo "===================="
echo "Comparing with existing seasons:"

for season in "2021-22" "2022-23" "2023-24"; do
    count=$(gcloud storage ls -r gs://nba-scraped-data/big-data-ball/${season}/*/game_*/ 2>/dev/null | wc -l || echo "0")
    echo "  ${season}: ${count} games"
done
echo "  2024-25: ${TOTAL_GAMES} games (target: ~1,400)"

echo ""
echo "🔧 Quick Commands"
echo "================"
echo "Start new backfill execution:"
echo "  gcloud run jobs execute ${JOB_NAME} --region=${REGION} --project=${PROJECT_ID}"
echo ""
echo "Test with limited date range:"
echo "  gcloud run jobs execute ${JOB_NAME} --region=${REGION} --project=${PROJECT_ID} \\"
echo "    --args='--start_date=2024-10-01 --end_date=2024-11-01'"
echo ""
echo "View live logs:"
echo "  gcloud logging tail \"resource.type=cloud_run_job AND resource.labels.job_name=${JOB_NAME}\" --project=${PROJECT_ID}"
echo ""
echo "Check specific date in GCS:"
echo "  gcloud storage ls gs://nba-scraped-data/big-data-ball/2024-25/2024-10-15/"
echo ""
echo "Validate a game file:"
echo "  gcloud storage cat gs://nba-scraped-data/big-data-ball/2024-25/2024-10-15/game_*/\*.csv | head -10"