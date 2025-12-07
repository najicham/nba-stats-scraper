#!/bin/bash
# Two-Pass Backfill: Registry THEN Analytics
# Eliminates timing issues by ensuring registry is populated first
#
# This prevents 83% of unresolved player name issues (timing issues) by ensuring
# the registry processor (Phase 1) completes BEFORE analytics processor (Phase 3) runs.
#
# Background:
# During normal backfills, analytics sometimes runs before or in parallel with registry.
# This causes players to be marked as "unresolved" even though they exist in the registry
# - just not yet when analytics runs.
#
# Solution:
# Two-pass approach ensures sequential execution:
#   PASS 1: Populate registry (Phase 1)
#   PASS 2: Run analytics (Phase 3) - now all players should resolve

set -e  # Exit on error

# Configuration
START_DATE=${1:-"2021-10-19"}
END_DATE=${2:-"2025-06-22"}
PROJECT_ID="nba-props-platform"

# Get absolute path to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=================================="
echo "TWO-PASS BACKFILL"
echo "Start Date: $START_DATE"
echo "End Date: $END_DATE"
echo "Project Root: $PROJECT_ROOT"
echo "=================================="

# Validate date format
if ! [[ "$START_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo "Error: Invalid start date format. Expected YYYY-MM-DD, got: $START_DATE"
    exit 1
fi

if ! [[ "$END_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo "Error: Invalid end date format. Expected YYYY-MM-DD, got: $END_DATE"
    exit 1
fi

# PASS 1: Registry
echo ""
echo "=== PASS 1: Populating Registry ==="
echo "This ensures all players are in the registry before analytics runs"
echo ""

# Run registry backfill
python "$PROJECT_ROOT/backfill_jobs/reference/gamebook_registry/gamebook_registry_reference_backfill.py" \
    --start-date "$START_DATE" \
    --end-date "$END_DATE" \
    --strategy merge

# Check if successful
if [ $? -ne 0 ]; then
    echo ""
    echo "=================================="
    echo "PASS 1 FAILED: Registry population failed"
    echo "=================================="
    exit 1
fi

echo ""
echo "=================================="
echo "PASS 1 COMPLETE: Registry populated"
echo "=================================="

# Wait a moment to ensure BigQuery commits are complete
echo ""
echo "Waiting 5 seconds for BigQuery commits to complete..."
sleep 5

# PASS 2: Analytics
echo ""
echo "=== PASS 2: Running Analytics ==="
echo "Now that registry is complete, analytics should resolve ~99% of players"
echo ""

# Run analytics backfill
python "$PROJECT_ROOT/backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py" \
    --start-date "$START_DATE" \
    --end-date "$END_DATE"

# Check if successful
if [ $? -ne 0 ]; then
    echo ""
    echo "=================================="
    echo "PASS 2 FAILED: Analytics processing failed"
    echo "=================================="
    echo ""
    echo "Note: Registry (Pass 1) completed successfully."
    echo "You can retry analytics only by running:"
    echo "  python $PROJECT_ROOT/backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \\"
    echo "    --start-date $START_DATE --end-date $END_DATE"
    exit 1
fi

echo ""
echo "=================================="
echo "PASS 2 COMPLETE: Analytics processed"
echo "=================================="

echo ""
echo "=================================="
echo "TWO-PASS BACKFILL COMPLETE"
echo "=================================="
echo ""
echo "Next steps:"
echo "1. Check unresolved count (should be <20):"
echo "   bq query --use_legacy_sql=false \\"
echo "     \"SELECT COUNT(*) as unresolved_count FROM \\\`$PROJECT_ID.nba_reference.unresolved_player_names\\\`\""
echo ""
echo "2. View top unresolved players:"
echo "   bq query --use_legacy_sql=false \\"
echo "     \"SELECT source_name, raw_name, COUNT(*) as occurrences FROM \\\`$PROJECT_ID.nba_reference.unresolved_player_names\\\` \\"
echo "     GROUP BY source_name, raw_name ORDER BY occurrences DESC LIMIT 20\""
echo ""
echo "3. If unresolved count > 20, run AI resolution:"
echo "   python $PROJECT_ROOT/tools/player_registry/resolve_unresolved_batch.py"
echo ""
