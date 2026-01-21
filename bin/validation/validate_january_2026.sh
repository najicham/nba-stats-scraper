#!/bin/bash
#
# Validate January 2026 Backfill Completeness
#
# This script validates every day in January 2026 to ensure backfill completed properly.
# Runs comprehensive validation across all phases and generates summary reports.
#
# Usage:
#   bash bin/validation/validate_january_2026.sh
#   bash bin/validation/validate_january_2026.sh --verbose
#   bash bin/validation/validate_january_2026.sh --json-output
#
# Output:
#   - Per-day validation results
#   - Summary statistics
#   - Missing data report
#   - JSON output (optional)
#

set -e  # Exit on error
set -u  # Exit on undefined variable

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
START_DATE="2026-01-01"
END_DATE="2026-01-21"  # Today
VALIDATION_SCRIPT="bin/validate_pipeline.py"
OUTPUT_DIR="validation_results/january_2026"
VERBOSE=false
JSON_OUTPUT=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --verbose)
            VERBOSE=true
            shift
            ;;
        --json-output)
            JSON_OUTPUT=true
            shift
            ;;
        --help)
            echo "Usage: $0 [--verbose] [--json-output]"
            echo ""
            echo "Options:"
            echo "  --verbose      Show detailed validation output"
            echo "  --json-output  Generate JSON output files"
            echo "  --help         Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Create output directory
mkdir -p "$OUTPUT_DIR"

echo -e "${BLUE}==================================================================${NC}"
echo -e "${BLUE}  Validating January 2026 Backfill (${START_DATE} to ${END_DATE})${NC}"
echo -e "${BLUE}==================================================================${NC}"
echo ""

# Initialize counters
TOTAL_DAYS=0
PASSED_DAYS=0
FAILED_DAYS=0
PARTIAL_DAYS=0
declare -a FAILED_DATES
declare -a PARTIAL_DATES

# Function to validate a single day
validate_day() {
    local game_date=$1
    local verbose_flag=""
    local json_flag=""

    if [ "$VERBOSE" = true ]; then
        verbose_flag="--verbose"
    fi

    if [ "$JSON_OUTPUT" = true ]; then
        json_flag="--json > ${OUTPUT_DIR}/${game_date}.json"
    fi

    echo -e "${BLUE}Validating ${game_date}...${NC}"

    # Run validation
    if python3 "$VALIDATION_SCRIPT" "$game_date" $verbose_flag 2>&1 | tee "${OUTPUT_DIR}/${game_date}.log"; then
        local exit_code=${PIPESTATUS[0]}

        # Check for errors in output
        if grep -q "ERROR" "${OUTPUT_DIR}/${game_date}.log"; then
            echo -e "${RED}✗ FAILED${NC}"
            FAILED_DAYS=$((FAILED_DAYS + 1))
            FAILED_DATES+=("$game_date")
            return 1
        elif grep -q "WARNING" "${OUTPUT_DIR}/${game_date}.log"; then
            echo -e "${YELLOW}⚠ PARTIAL${NC}"
            PARTIAL_DAYS=$((PARTIAL_DAYS + 1))
            PARTIAL_DATES+=("$game_date")
            return 2
        else
            echo -e "${GREEN}✓ PASSED${NC}"
            PASSED_DAYS=$((PASSED_DAYS + 1))
            return 0
        fi
    else
        echo -e "${RED}✗ FAILED (script error)${NC}"
        FAILED_DAYS=$((FAILED_DAYS + 1))
        FAILED_DATES+=("$game_date")
        return 1
    fi

    echo ""
}

# Generate date range
current_date="$START_DATE"
while [[ "$current_date" < "$END_DATE" ]] || [[ "$current_date" == "$END_DATE" ]]; do
    TOTAL_DAYS=$((TOTAL_DAYS + 1))
    validate_day "$current_date"

    # Increment date
    current_date=$(date -I -d "$current_date + 1 day")
done

echo ""
echo -e "${BLUE}==================================================================${NC}"
echo -e "${BLUE}  Validation Summary${NC}"
echo -e "${BLUE}==================================================================${NC}"
echo ""
echo "Total Days Validated: $TOTAL_DAYS"
echo -e "${GREEN}Passed: $PASSED_DAYS${NC}"
echo -e "${YELLOW}Partial (with warnings): $PARTIAL_DAYS${NC}"
echo -e "${RED}Failed: $FAILED_DAYS${NC}"
echo ""

# Show failed dates
if [ ${#FAILED_DATES[@]} -gt 0 ]; then
    echo -e "${RED}Failed Dates:${NC}"
    for failed_date in "${FAILED_DATES[@]}"; do
        echo "  - $failed_date (see ${OUTPUT_DIR}/${failed_date}.log)"
    done
    echo ""
fi

# Show partial dates
if [ ${#PARTIAL_DATES[@]} -gt 0 ]; then
    echo -e "${YELLOW}Partial Dates (with warnings):${NC}"
    for partial_date in "${PARTIAL_DATES[@]}"; do
        echo "  - $partial_date (see ${OUTPUT_DIR}/${partial_date}.log)"
    done
    echo ""
fi

# Calculate success rate
SUCCESS_RATE=$(awk "BEGIN {printf \"%.1f\", ($PASSED_DAYS / $TOTAL_DAYS) * 100}")
echo "Success Rate: ${SUCCESS_RATE}%"
echo ""

# Generate combined report
echo -e "${BLUE}Generating combined report...${NC}"
cat > "${OUTPUT_DIR}/summary.txt" <<EOF
January 2026 Backfill Validation Summary
Generated: $(date -u +"%Y-%m-%d %H:%M:%S UTC")

Date Range: ${START_DATE} to ${END_DATE}
Total Days: ${TOTAL_DAYS}

Results:
  ✓ Passed: ${PASSED_DAYS}
  ⚠ Partial: ${PARTIAL_DAYS}
  ✗ Failed: ${FAILED_DAYS}

Success Rate: ${SUCCESS_RATE}%

Failed Dates:
EOF

for failed_date in "${FAILED_DATES[@]}"; do
    echo "  - $failed_date" >> "${OUTPUT_DIR}/summary.txt"
done

echo "">> "${OUTPUT_DIR}/summary.txt"
echo "Partial Dates:">> "${OUTPUT_DIR}/summary.txt"
for partial_date in "${PARTIAL_DATES[@]}"; do
    echo "  - $partial_date" >> "${OUTPUT_DIR}/summary.txt"
done

echo ""
echo -e "${GREEN}Combined report saved to: ${OUTPUT_DIR}/summary.txt${NC}"
echo -e "${GREEN}Individual logs saved to: ${OUTPUT_DIR}/<date>.log${NC}"
echo ""

# Exit with appropriate code
if [ $FAILED_DAYS -gt 0 ]; then
    echo -e "${RED}⚠ Validation found failures!${NC}"
    exit 1
elif [ $PARTIAL_DAYS -gt 0 ]; then
    echo -e "${YELLOW}⚠ Validation found warnings!${NC}"
    exit 2
else
    echo -e "${GREEN}✓ All validations passed!${NC}"
    exit 0
fi
