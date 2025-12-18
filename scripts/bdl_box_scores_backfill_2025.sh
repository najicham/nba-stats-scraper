#!/bin/bash
# FILE: scripts/bdl_box_scores_backfill_2025.sh
#
# Backfill Ball Don't Lie box scores for Oct 21 - Nov 12, 2025
# Missing dates at the start of the 2025-26 season
#
# Usage:
#   chmod +x scripts/bdl_box_scores_backfill_2025.sh
#   ./scripts/bdl_box_scores_backfill_2025.sh

# Don't exit on error - some dates may have no games
set +e

cd /home/naji/code/nba-stats-scraper

echo "========================================"
echo "BDL Box Scores Backfill: Oct 21 - Nov 12, 2025"
echo "========================================"
echo "Start time: $(date)"
echo ""

# Date range to backfill
START_DATE="2025-10-21"
END_DATE="2025-11-12"

# Counter for tracking
TOTAL=0
SUCCESS=0
FAILED=0

# Generate list of dates
CURRENT_DATE="$START_DATE"

echo "Processing dates from $START_DATE to $END_DATE..."
echo ""

while [[ "$CURRENT_DATE" < "$END_DATE" ]] || [[ "$CURRENT_DATE" == "$END_DATE" ]]; do
    TOTAL=$((TOTAL + 1))
    echo "[$TOTAL] Processing $CURRENT_DATE..."

    # Run the scraper
    OUTPUT=$(PYTHONPATH=. .venv/bin/python scrapers/balldontlie/bdl_box_scores.py --date "$CURRENT_DATE" --group gcs 2>&1)

    if echo "$OUTPUT" | grep -q "Uploaded to gs://"; then
        SUCCESS=$((SUCCESS + 1))
        echo "  ✅ Success"
    elif echo "$OUTPUT" | grep -q "No games"; then
        echo "  ⏭️ No games on this date"
    else
        FAILED=$((FAILED + 1))
        echo "  ❌ Failed"
        echo "$OUTPUT" | tail -3
    fi

    # Rate limiting - 1s between requests
    sleep 1

    # Increment date (using GNU date)
    CURRENT_DATE=$(date -I -d "$CURRENT_DATE + 1 day")
done

echo ""
echo "========================================"
echo "BACKFILL COMPLETE"
echo "========================================"
echo "End time: $(date)"
echo "Total dates: $TOTAL"
echo "Success: $SUCCESS"
echo "Failed: $FAILED"
echo ""
echo "Data location: gs://nba-scraped-data/ball-dont-lie/boxscores/"
