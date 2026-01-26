#!/bin/bash
#
# Performance Benchmark Runner Script
#
# Usage:
#   ./scripts/run_benchmarks.sh [options]
#
# Options:
#   --save-baseline     Save results as baseline
#   --compare           Compare with baseline
#   --full              Run all tests including slow benchmarks
#   --scraper-only      Run only scraper benchmarks
#   --processor-only    Run only processor benchmarks
#   --query-only        Run only query benchmarks
#   --pipeline-only     Run only pipeline benchmarks
#   --histogram         Generate histogram
#   --help              Show this help message
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default options
SAVE_BASELINE=false
COMPARE_BASELINE=false
FULL_SUITE=false
TARGET=""
HISTOGRAM=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --save-baseline)
            SAVE_BASELINE=true
            shift
            ;;
        --compare)
            COMPARE_BASELINE=true
            shift
            ;;
        --full)
            FULL_SUITE=true
            shift
            ;;
        --scraper-only)
            TARGET="tests/performance/test_scraper_benchmarks.py"
            shift
            ;;
        --processor-only)
            TARGET="tests/performance/test_processor_throughput.py"
            shift
            ;;
        --query-only)
            TARGET="tests/performance/test_query_performance.py"
            shift
            ;;
        --pipeline-only)
            TARGET="tests/performance/test_pipeline_e2e_performance.py"
            shift
            ;;
        --histogram)
            HISTOGRAM=true
            shift
            ;;
        --help)
            head -n 15 "$0" | tail -n 14
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Set target if not specified
if [ -z "$TARGET" ]; then
    TARGET="tests/performance/"
fi

echo -e "${GREEN}=== NBA Stats Scraper Performance Benchmarks ===${NC}"
echo ""

# Build pytest command
PYTEST_CMD="pytest $TARGET -v --benchmark-only"

# Add benchmark configuration
PYTEST_CMD="$PYTEST_CMD --benchmark-columns=min,max,mean,stddev,median"
PYTEST_CMD="$PYTEST_CMD --benchmark-warmup=on"
PYTEST_CMD="$PYTEST_CMD --benchmark-min-rounds=5"

# Add save baseline option
if [ "$SAVE_BASELINE" = true ]; then
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    echo -e "${YELLOW}Saving baseline as: baseline_${TIMESTAMP}${NC}"
    PYTEST_CMD="$PYTEST_CMD --benchmark-save=baseline_${TIMESTAMP} --benchmark-autosave"
fi

# Add compare baseline option
if [ "$COMPARE_BASELINE" = true ]; then
    echo -e "${YELLOW}Comparing with baseline${NC}"
    PYTEST_CMD="$PYTEST_CMD --benchmark-compare --benchmark-compare-fail=mean:20%"
fi

# Add histogram option
if [ "$HISTOGRAM" = true ]; then
    echo -e "${YELLOW}Generating histogram${NC}"
    PYTEST_CMD="$PYTEST_CMD --benchmark-histogram"
fi

# Add slow benchmarks if full suite requested
if [ "$FULL_SUITE" = true ]; then
    echo -e "${YELLOW}Running full suite including slow benchmarks${NC}"
else
    PYTEST_CMD="$PYTEST_CMD -m 'not slow_benchmark'"
fi

echo ""
echo -e "${GREEN}Running:${NC} $PYTEST_CMD"
echo ""

# Run benchmarks
$PYTEST_CMD

# Check exit code
EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ Benchmarks passed${NC}"
else
    echo -e "${RED}✗ Benchmarks failed (exit code: $EXIT_CODE)${NC}"
fi

exit $EXIT_CODE
