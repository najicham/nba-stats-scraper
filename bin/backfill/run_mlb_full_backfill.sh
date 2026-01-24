#!/bin/bash
# Full MLB Pipeline Backfill
# Runs Phase 3 (batter_game_summary) + Phase 4 (lineup_k_analysis) + regenerate predictions
#
# Prerequisites: bdl_batter_stats must be populated first
#   Run: PYTHONPATH=. python scripts/mlb/collect_batter_stats.py
#
# Usage:
#   ./bin/backfill/run_mlb_full_backfill.sh                    # Full 2024-2025 backfill
#   ./bin/backfill/run_mlb_full_backfill.sh 2024-08-01 2024-08-31  # Specific date range

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

# Default date range (2024-2025 MLB seasons)
START_DATE="${1:-2024-03-28}"
END_DATE="${2:-2025-09-28}"

LOG_FILE="logs/mlb_full_backfill_$(date +%Y%m%d_%H%M%S).log"
mkdir -p logs

echo "=============================================="
echo "MLB Full Pipeline Backfill"
echo "=============================================="
echo "Date range: $START_DATE to $END_DATE"
echo "Log file: $LOG_FILE"
echo ""

# Step 0: Verify source data
echo "Step 0: Verifying source data..."
BATTER_COUNT=$(bq query --use_legacy_sql=false --format=csv \
    "SELECT COUNT(*) FROM mlb_raw.bdl_batter_stats WHERE game_date BETWEEN '$START_DATE' AND '$END_DATE'" 2>/dev/null | tail -1)

echo "  Source batter stats: $BATTER_COUNT rows"

if [ "$BATTER_COUNT" -lt "10000" ]; then
    echo ""
    echo "WARNING: Only $BATTER_COUNT batter stats found."
    echo "The full 2024-2025 season should have ~90,000+ rows."
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted. Run batter stats collection first:"
        echo "  PYTHONPATH=. python scripts/mlb/collect_batter_stats.py"
        exit 1
    fi
fi

# Step 1: Run batter_game_summary processor
echo ""
echo "=============================================="
echo "Step 1: Running batter_game_summary processor"
echo "=============================================="
echo "This generates rolling K rates for each batter..."

SPORT=mlb PYTHONPATH=. .venv/bin/python -c "
from data_processors.analytics.mlb.batter_game_summary_processor import MlbBatterGameSummaryProcessor
from datetime import date, timedelta

processor = MlbBatterGameSummaryProcessor()

start = date.fromisoformat('$START_DATE')
end = date.fromisoformat('$END_DATE')
current = start
total_rows = 0
days_processed = 0

print(f'Processing batter_game_summary from {start} to {end}...')

while current <= end:
    try:
        result = processor.process_date(current)
        rows = result.get('rows_processed', 0)
        total_rows += rows
        days_processed += 1

        if days_processed % 30 == 0:
            print(f'  Progress: {current} - {days_processed} days, {total_rows} total rows')
    except Exception as e:
        print(f'  Error on {current}: {e}')

    current += timedelta(days=1)

print(f'Batter game summary complete: {days_processed} days, {total_rows} rows')
" 2>&1 | tee -a "$LOG_FILE"

# Verify batter_game_summary
echo ""
echo "Verifying batter_game_summary..."
bq query --use_legacy_sql=false "
SELECT
    COUNT(*) as total_rows,
    COUNT(DISTINCT player_lookup) as unique_batters,
    MIN(game_date) as start_date,
    MAX(game_date) as end_date
FROM mlb_analytics.batter_game_summary
WHERE game_date BETWEEN '$START_DATE' AND '$END_DATE'
"

# Step 2: Run lineup_k_analysis processor
echo ""
echo "=============================================="
echo "Step 2: Running lineup_k_analysis processor"
echo "=============================================="
echo "This calculates bottom-up K expectations..."

SPORT=mlb PYTHONPATH=. .venv/bin/python -c "
from data_processors.precompute.mlb.lineup_k_analysis_processor import MlbLineupKAnalysisProcessor
from datetime import date, timedelta

processor = MlbLineupKAnalysisProcessor()

start = date.fromisoformat('$START_DATE')
end = date.fromisoformat('$END_DATE')
current = start
total_analyses = 0
days_processed = 0

print(f'Processing lineup_k_analysis from {start} to {end}...')

while current <= end:
    try:
        result = processor.process_date(current)
        analyses = result.get('processed', 0)
        total_analyses += analyses
        days_processed += 1

        if days_processed % 30 == 0:
            print(f'  Progress: {current} - {days_processed} days, {total_analyses} analyses')
    except Exception as e:
        print(f'  Error on {current}: {e}')

    current += timedelta(days=1)

print(f'Lineup K analysis complete: {days_processed} days, {total_analyses} analyses')
" 2>&1 | tee -a "$LOG_FILE"

# Verify lineup_k_analysis
echo ""
echo "Verifying lineup_k_analysis..."
bq query --use_legacy_sql=false "
SELECT
    COUNT(*) as total_analyses,
    COUNT(DISTINCT pitcher_lookup) as unique_pitchers,
    ROUND(AVG(bottom_up_expected_k), 2) as avg_expected_k,
    MIN(game_date) as start_date,
    MAX(game_date) as end_date
FROM mlb_precompute.lineup_k_analysis
WHERE game_date BETWEEN '$START_DATE' AND '$END_DATE'
"

# Step 3: Regenerate predictions with full features
echo ""
echo "=============================================="
echo "Step 3: Regenerating predictions with full features"
echo "=============================================="

PYTHONPATH=. .venv/bin/python scripts/mlb/generate_historical_predictions.py \
    --start-date "$START_DATE" \
    --end-date "$END_DATE" \
    2>&1 | tee -a "$LOG_FILE"

# Final summary
echo ""
echo "=============================================="
echo "BACKFILL COMPLETE"
echo "=============================================="
echo ""
echo "Final verification:"

bq query --use_legacy_sql=false "
SELECT
    'bdl_batter_stats' as table_name,
    COUNT(*) as row_count
FROM mlb_raw.bdl_batter_stats
WHERE game_date BETWEEN '$START_DATE' AND '$END_DATE'
UNION ALL
SELECT
    'batter_game_summary' as table_name,
    COUNT(*) as row_count
FROM mlb_analytics.batter_game_summary
WHERE game_date BETWEEN '$START_DATE' AND '$END_DATE'
UNION ALL
SELECT
    'lineup_k_analysis' as table_name,
    COUNT(*) as row_count
FROM mlb_precompute.lineup_k_analysis
WHERE game_date BETWEEN '$START_DATE' AND '$END_DATE'
UNION ALL
SELECT
    'pitcher_strikeouts' as table_name,
    COUNT(*) as row_count
FROM mlb_predictions.pitcher_strikeouts
WHERE game_date BETWEEN '$START_DATE' AND '$END_DATE'
ORDER BY table_name
"

echo ""
echo "Log file: $LOG_FILE"
echo ""
