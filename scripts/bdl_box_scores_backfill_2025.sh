#!/bin/bash
# FILE: scripts/bdl_box_scores_backfill_2025.sh
#
# Backfill Ball Don't Lie box scores for Oct 21 - Nov 12, 2025
# Missing dates at the start of the 2025-26 season
#
# Usage:
#   chmod +x scripts/bdl_box_scores_backfill_2025.sh
#   ./scripts/bdl_box_scores_backfill_2025.sh

set -e

echo "========================================"
echo "BDL Box Scores Backfill: Oct 21 - Nov 12, 2025"
echo "========================================"
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

echo "Generating date range..."
while [[ "$CURRENT_DATE" < "$END_DATE" ]] || [[ "$CURRENT_DATE" == "$END_DATE" ]]; do
    ((TOTAL++))
    echo "[$TOTAL] Processing $CURRENT_DATE..."

    # Run the scraper
    if PYTHONPATH=. .venv/bin/python scrapers/balldontlie/bdl_box_scores.py --date "$CURRENT_DATE" --group gcs 2>&1 | grep -q "Uploaded to gs://"; then
        ((SUCCESS++))
        echo "  ✅ Success"
    else
        ((FAILED++))
        echo "  ❌ Failed"
    fi

    # Rate limiting - 0.5s between requests (120 req/min)
    sleep 0.5

    # Increment date (using GNU date)
    CURRENT_DATE=$(date -I -d "$CURRENT_DATE + 1 day")
done

echo ""
echo "========================================"
echo "BACKFILL COMPLETE"
echo "========================================"
echo "Total dates: $TOTAL"
echo "Success: $SUCCESS"
echo "Failed: $FAILED"
echo ""
echo "Data location: gs://nba-scraped-data/ball-dont-lie/boxscores/"
