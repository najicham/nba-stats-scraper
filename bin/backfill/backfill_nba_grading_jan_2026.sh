#!/bin/bash
# ============================================================================
# NBA Grading Historical Backfill - Jan 1-13, 2026
# ============================================================================
# Purpose: Grade all predictions from Jan 1-13 to increase statistical significance
# Created: Session 90 - 2026-01-17
# ============================================================================

set -e  # Exit on error

PROJECT_ID="nba-props-platform"
GRADING_QUERY="schemas/bigquery/nba_predictions/grade_predictions_query.sql"

# Date range to backfill
START_DATE="2026-01-01"
END_DATE="2026-01-13"

echo "============================================================================"
echo "NBA Grading Backfill: $START_DATE to $END_DATE"
echo "============================================================================"
echo ""

# Counter for tracking
total_dates=0
successful_dates=0
failed_dates=0

# Iterate through each date
current_date="$START_DATE"
while [[ "$current_date" < "$END_DATE" ]] || [[ "$current_date" == "$END_DATE" ]]; do
  total_dates=$((total_dates + 1))

  echo "[$total_dates] Grading predictions for: $current_date"

  # Run grading query with parameter
  if bq query \
    --use_legacy_sql=false \
    --project_id="$PROJECT_ID" \
    --parameter="game_date:DATE:$current_date" \
    < "$GRADING_QUERY" > /dev/null 2>&1; then

    successful_dates=$((successful_dates + 1))
    echo "    ✓ Success"
  else
    failed_dates=$((failed_dates + 1))
    echo "    ✗ Failed"
  fi

  # Move to next date
  current_date=$(date -I -d "$current_date + 1 day")
done

echo ""
echo "============================================================================"
echo "Backfill Complete!"
echo "============================================================================"
echo "Total dates processed: $total_dates"
echo "Successful: $successful_dates"
echo "Failed: $failed_dates"
echo ""
echo "Validating results..."

# Validation query
bq query --use_legacy_sql=false --format=pretty "
SELECT
  MIN(game_date) as earliest_date,
  MAX(game_date) as latest_date,
  COUNT(DISTINCT game_date) as total_days,
  COUNT(*) as total_grades,
  COUNTIF(has_issues = FALSE) as clean_grades,
  ROUND(100.0 * COUNTIF(has_issues = FALSE) / COUNT(*), 1) as clean_pct
FROM \`nba-props-platform.nba_predictions.prediction_grades\`
"

echo ""
echo "Backfill script complete!"
