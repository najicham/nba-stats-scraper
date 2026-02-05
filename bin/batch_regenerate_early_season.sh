#!/bin/bash
# Batch regenerate player_daily_cache for early season dates (2025-11-01 to 2025-12-02)
# Bypasses bootstrap check to reprocess P1 dates with DNP pollution bug

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PYTHON_SCRIPT="$SCRIPT_DIR/regenerate_cache_bypass_bootstrap.py"

# P1 dates: 2025-11-01 through 2025-12-02 (31 dates)
DATES=(
    "2025-11-01" "2025-11-02" "2025-11-03" "2025-11-04" "2025-11-05"
    "2025-11-06" "2025-11-07" "2025-11-08" "2025-11-09" "2025-11-10"
    "2025-11-11" "2025-11-12" "2025-11-13" "2025-11-14" "2025-11-15"
    "2025-11-16" "2025-11-17" "2025-11-18" "2025-11-19" "2025-11-20"
    "2025-11-21" "2025-11-22" "2025-11-23" "2025-11-24" "2025-11-25"
    "2025-11-26" "2025-11-27" "2025-11-28" "2025-11-29" "2025-11-30"
    "2025-12-01" "2025-12-02"
)

SUCCESS_COUNT=0
FAIL_COUNT=0
FAILED_DATES=()

echo "========================================"
echo "Batch Regenerate Player Daily Cache"
echo "Processing ${#DATES[@]} early season dates"
echo "========================================"
echo ""

for date in "${DATES[@]}"; do
    echo "Processing: $date"

    if python "$PYTHON_SCRIPT" "$date" > "/tmp/cache_regen_${date}.log" 2>&1; then
        echo "  ✓ Success"
        ((SUCCESS_COUNT++))
    else
        echo "  ✗ Failed (see /tmp/cache_regen_${date}.log)"
        ((FAIL_COUNT++))
        FAILED_DATES+=("$date")
    fi
done

echo ""
echo "========================================"
echo "Batch Processing Complete"
echo "========================================"
echo "Successful: $SUCCESS_COUNT / ${#DATES[@]}"
echo "Failed: $FAIL_COUNT / ${#DATES[@]}"

if [ $FAIL_COUNT -gt 0 ]; then
    echo ""
    echo "Failed dates:"
    for failed_date in "${FAILED_DATES[@]}"; do
        echo "  - $failed_date"
    done
    exit 1
else
    echo ""
    echo "✓ All dates processed successfully!"
    exit 0
fi
