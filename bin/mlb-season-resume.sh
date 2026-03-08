#!/bin/bash
# Resume all MLB scheduler jobs for season start.
# Run this on Mar 24-25 before opening day (Mar 27).
#
# Usage: ./bin/mlb-season-resume.sh [--dry-run]

set -euo pipefail

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "DRY RUN — no changes will be made"
fi

echo "=== MLB Season Resume ==="
echo ""

# List all MLB scheduler jobs
JOBS=$(gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform \
    --format="value(name)" | grep "^mlb-")

TOTAL=$(echo "$JOBS" | wc -l)
RESUMED=0

echo "Found $TOTAL MLB scheduler jobs"
echo ""

for JOB in $JOBS; do
    STATE=$(gcloud scheduler jobs describe "$JOB" --location=us-west2 \
        --project=nba-props-platform --format="value(state)")

    if [[ "$STATE" == "PAUSED" ]]; then
        if [[ "$DRY_RUN" == "true" ]]; then
            echo "  [DRY] Would resume: $JOB"
        else
            gcloud scheduler jobs resume "$JOB" --location=us-west2 --project=nba-props-platform
            echo "  Resumed: $JOB"
        fi
        RESUMED=$((RESUMED + 1))
    else
        echo "  Already $STATE: $JOB"
    fi
done

echo ""
echo "=== Summary ==="
echo "Total MLB jobs: $TOTAL"
echo "Resumed: $RESUMED"
echo ""
echo "Next steps:"
echo "  1. Verify scrapes are flowing: check BQ mlb_raw tables"
echo "  2. Trigger test prediction: curl MLB worker endpoint"
echo "  3. Check grading next morning"
