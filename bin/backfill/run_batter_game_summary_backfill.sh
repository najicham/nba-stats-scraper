#!/bin/bash
# Backfill MLB batter_game_summary analytics
# Run after bdl_batter_stats is populated

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

# Date range - covers 2024 and 2025 MLB seasons
START_DATE="${1:-2024-03-28}"
END_DATE="${2:-2025-09-28}"

echo "=============================================="
echo "MLB Batter Game Summary Backfill"
echo "=============================================="
echo "Date range: $START_DATE to $END_DATE"
echo ""

# Check source data
echo "Checking source data..."
BATTER_COUNT=$(bq query --use_legacy_sql=false --format=csv \
    "SELECT COUNT(*) FROM mlb_raw.bdl_batter_stats WHERE game_date BETWEEN '$START_DATE' AND '$END_DATE'" 2>/dev/null | tail -1)
echo "Source batter stats rows: $BATTER_COUNT"

if [ "$BATTER_COUNT" -lt "1000" ]; then
    echo "ERROR: Not enough source data. Run collect_batter_stats.py first."
    exit 1
fi

# Run the processor
echo ""
echo "Starting batter_game_summary processor..."
SPORT=mlb PYTHONPATH=. .venv/bin/python -c "
from data_processors.analytics.mlb.batter_game_summary_processor import MlbBatterGameSummaryProcessor
from datetime import date, timedelta

processor = MlbBatterGameSummaryProcessor()

start = date.fromisoformat('$START_DATE')
end = date.fromisoformat('$END_DATE')
current = start
total_rows = 0
days_processed = 0

while current <= end:
    try:
        result = processor.process_date(current)
        rows = result.get('rows_processed', 0)
        total_rows += rows
        days_processed += 1

        if days_processed % 30 == 0:
            print(f'Progress: {current} - {days_processed} days, {total_rows} rows')
    except Exception as e:
        print(f'Error on {current}: {e}')

    current += timedelta(days=1)

print(f'\\nComplete! Processed {days_processed} days, {total_rows} total rows')
"

echo ""
echo "Verifying results..."
bq query --use_legacy_sql=false "
SELECT
    MIN(game_date) as start_date,
    MAX(game_date) as end_date,
    COUNT(*) as total_rows,
    COUNT(DISTINCT player_lookup) as unique_batters,
    COUNT(DISTINCT game_id) as unique_games,
    ROUND(AVG(k_rate_last_10), 3) as avg_k_rate_10
FROM mlb_analytics.batter_game_summary
"

echo ""
echo "Backfill complete!"
