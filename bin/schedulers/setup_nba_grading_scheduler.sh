#!/bin/bash
# setup_nba_grading_scheduler.sh - Set up BigQuery scheduled query for NBA prediction grading
#
# This creates a scheduled query that runs daily at noon PT to grade yesterday's predictions.
#
# Usage: ./bin/schedulers/setup_nba_grading_scheduler.sh

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
SCHEDULE_NAME="nba-prediction-grading-daily"
DATASET="nba_predictions"

# Schedule: Daily at 12:00 PM PT
# Cron format: minute hour day month day-of-week
# 12:00 PM PT = 20:00 UTC (during standard time) or 19:00 UTC (during daylight saving)
# Using 20:00 UTC to be safe
SCHEDULE="0 20 * * *"  # Daily at 8:00 PM UTC (12:00 PM PT)

echo "========================================"
echo " Setting up NBA Grading Scheduled Query"
echo "========================================"
echo "Project: $PROJECT_ID"
echo "Schedule: $SCHEDULE (12:00 PM PT / 8:00 PM UTC)"
echo "Dataset: $DATASET"
echo ""

# Read the grading query from file
QUERY_FILE="schemas/bigquery/nba_predictions/grade_predictions_query.sql"

if [ ! -f "$QUERY_FILE" ]; then
    echo "❌ Error: Query file not found: $QUERY_FILE"
    exit 1
fi

echo "Reading query from: $QUERY_FILE"
echo ""

# Create or update the scheduled query using bq CLI
# Note: We use a templated query that sets @game_date to yesterday
QUERY=$(cat "$QUERY_FILE")

# Wrap the query with parameter declaration
SCHEDULED_QUERY="DECLARE game_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);

$QUERY"

echo "Creating scheduled query..."

# Delete existing scheduled query if it exists
if bq ls --transfer_config --transfer_location=us --project_id="$PROJECT_ID" | grep -q "$SCHEDULE_NAME"; then
    echo "⚠️  Existing scheduled query found. Deleting..."
    TRANSFER_CONFIG_ID=$(bq ls --transfer_config --transfer_location=us --project_id="$PROJECT_ID" --format=json | jq -r ".[] | select(.displayName == \"$SCHEDULE_NAME\") | .name" | cut -d'/' -f6)
    bq rm --transfer_config "$TRANSFER_CONFIG_ID"
    echo "✅ Deleted existing scheduled query"
fi

# Create the scheduled query
bq mk \
    --transfer_config \
    --project_id="$PROJECT_ID" \
    --data_source=scheduled_query \
    --display_name="$SCHEDULE_NAME" \
    --schedule="$SCHEDULE" \
    --target_dataset="$DATASET" \
    --params="{\"query\":\"$SCHEDULED_QUERY\",\"destination_table_name_template\":\"\",\"write_disposition\":\"WRITE_APPEND\",\"partitioning_field\":\"\"}"

echo ""
echo "========================================"
echo " Scheduled Query Created Successfully!"
echo "========================================"
echo "Name: $SCHEDULE_NAME"
echo "Schedule: Daily at 12:00 PM PT (8:00 PM UTC)"
echo "Target Dataset: $DATASET"
echo ""
echo "The query will:"
echo "  1. Run daily at noon Pacific Time"
echo "  2. Grade predictions from yesterday (game_date = CURRENT_DATE - 1 day)"
echo "  3. Insert results into nba_predictions.prediction_grades"
echo "  4. Skip already-graded predictions (idempotent)"
echo ""
echo "To view scheduled queries:"
echo "  bq ls --transfer_config --transfer_location=us --project_id=$PROJECT_ID"
echo ""
echo "To manually trigger the query:"
echo "  bq mk --transfer_run --run_time='<timestamp>' projects/<project-id>/locations/us/transferConfigs/<config-id>"
echo ""
