#!/bin/bash
# Parse backfill log file and extract metrics
# Usage: parse_backfill_log.sh <log_file>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../validation/common_validation.sh"

LOG_FILE=$1

if [[ -z "$LOG_FILE" || ! -f "$LOG_FILE" ]]; then
    log_error "Usage: $0 <log_file>"
    log_error "Log file not found: $LOG_FILE"
    exit 1
fi

# Extract metrics from log file

# Success count: lines with "✓ Success"
SUCCESS_COUNT=$(grep -c "✓ Success" "$LOG_FILE" 2>/dev/null || echo "0")

# Failed count: lines with "✗ Failed"
FAILED_COUNT=$(grep -c "✗ Failed" "$LOG_FILE" 2>/dev/null || echo "0")

# Total days being processed (look for "Processing day X/Y")
TOTAL_DAYS=$(grep -oP "Processing day \d+/\K\d+" "$LOG_FILE" | head -1 || echo "0")

# Current progress (last "Processing day X/Y" line)
CURRENT_DAY=$(grep -oP "Processing day \K\d+(?=/)" "$LOG_FILE" | tail -1 || echo "0")

# Total records processed (sum all "Success: N records" lines)
TOTAL_RECORDS=0
while read -r count; do
    TOTAL_RECORDS=$((TOTAL_RECORDS + count))
done < <(grep -oP "✓ Success: \K\d+" "$LOG_FILE" 2>/dev/null || true)

# Calculate success rate
if [[ $CURRENT_DAY -gt 0 ]]; then
    SUCCESS_RATE=$(echo "scale=2; ($SUCCESS_COUNT / $CURRENT_DAY) * 100" | bc -l)
else
    SUCCESS_RATE=0
fi

# Check for completion (look for "DAY-BY-DAY BACKFILL SUMMARY" or "BACKFILL SUMMARY")
if grep -q "BACKFILL SUMMARY" "$LOG_FILE" 2>/dev/null; then
    COMPLETED=true

    # Extract final stats from summary
    FINAL_SUCCESS=$(grep -oP "Successful days: \K\d+" "$LOG_FILE" | tail -1 || echo "$SUCCESS_COUNT")
    FINAL_FAILED=$(grep -oP "Failed days: \K\d+" "$LOG_FILE" | tail -1 || echo "$FAILED_COUNT")
    FINAL_TOTAL=$(grep -oP "Total days: \K\d+" "$LOG_FILE" | tail -1 || echo "$TOTAL_DAYS")
    FINAL_RECORDS=$(grep -oP "Total records processed: \K\d+" "$LOG_FILE" | tail -1 || echo "$TOTAL_RECORDS")

    if [[ $FINAL_TOTAL -gt 0 ]]; then
        FINAL_SUCCESS_RATE=$(echo "scale=2; ($FINAL_SUCCESS / $FINAL_TOTAL) * 100" | bc -l)
    else
        FINAL_SUCCESS_RATE=0
    fi
else
    COMPLETED=false
    FINAL_SUCCESS=$SUCCESS_COUNT
    FINAL_FAILED=$FAILED_COUNT
    FINAL_TOTAL=$TOTAL_DAYS
    FINAL_RECORDS=$TOTAL_RECORDS
    FINAL_SUCCESS_RATE=$SUCCESS_RATE
fi

# Check for fatal errors
FATAL_ERRORS=$(grep -c "FATAL\|CRITICAL ERROR\|Traceback" "$LOG_FILE" 2>/dev/null || echo "0")

# Output results as JSON-like format for easy parsing
cat <<EOF
{
  "completed": $COMPLETED,
  "current_day": $CURRENT_DAY,
  "total_days": $FINAL_TOTAL,
  "successful_days": $FINAL_SUCCESS,
  "failed_days": $FINAL_FAILED,
  "success_rate": $FINAL_SUCCESS_RATE,
  "total_records": $FINAL_RECORDS,
  "fatal_errors": $FATAL_ERRORS,
  "progress_pct": $(echo "scale=2; ($CURRENT_DAY / $FINAL_TOTAL) * 100" | bc -l 2>/dev/null || echo "0")
}
EOF
