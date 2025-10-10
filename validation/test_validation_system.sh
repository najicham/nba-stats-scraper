#!/bin/bash
# File: validation/test_validation_system.sh
# Description: Test runner for validation system - runs validators and checks results
# Usage: ./test_validation_system.sh [--verbose] [--processor NAME]

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default settings
VERBOSE=false
SPECIFIC_PROCESSOR=""
TEST_DAYS=7

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --processor|-p)
            SPECIFIC_PROCESSOR="$2"
            shift 2
            ;;
        --days|-d)
            TEST_DAYS="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --verbose, -v          Enable verbose logging"
            echo "  --processor, -p NAME   Test specific processor only"
            echo "  --days, -d N           Test last N days (default: 7)"
            echo "  --help, -h             Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                                # Test all validators (last 7 days)"
            echo "  $0 --verbose --days 30            # Test all validators (last 30 days, verbose)"
            echo "  $0 --processor bdl_boxscores      # Test only BDL boxscores"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}NBA Validation System Test Runner${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""
echo "Test Configuration:"
echo "  Date Range: Last $TEST_DAYS days"
echo "  Verbose: $VERBOSE"
if [ -n "$SPECIFIC_PROCESSOR" ]; then
    echo "  Processor: $SPECIFIC_PROCESSOR"
else
    echo "  Processor: All"
fi
echo ""

# Check if we're in the right directory
if [ ! -d "validation" ]; then
    echo -e "${RED}Error: Must be run from project root (nba-stats-scraper)${NC}"
    exit 1
fi

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo -e "${YELLOW}Warning: Virtual environment not activated${NC}"
    echo "Activating .venv..."
    source .venv/bin/activate || {
        echo -e "${RED}Error: Could not activate virtual environment${NC}"
        exit 1
    }
fi

# Results tracking
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0
WARNED_TESTS=0

# Function to run a single validator
run_validator() {
    local validator_name=$1
    local validator_script=$2
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    
    echo ""
    echo -e "${BLUE}Testing: ${validator_name}${NC}"
    echo "Script: $validator_script"
    echo "----------------------------------------"
    
    # Build command
    local cmd="python $validator_script --last-days $TEST_DAYS --no-notify"
    if [ "$VERBOSE" = true ]; then
        cmd="$cmd --verbose"
    fi
    
    # Run validator
    local exit_code=0
    if [ "$VERBOSE" = true ]; then
        $cmd || exit_code=$?
    else
        $cmd > /tmp/validation_output.txt 2>&1 || exit_code=$?
    fi
    
    # Check result
    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}✅ PASSED${NC}"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    elif [ $exit_code -eq 2 ]; then
        echo -e "${YELLOW}⚠️  WARNINGS${NC}"
        WARNED_TESTS=$((WARNED_TESTS + 1))
        if [ "$VERBOSE" = false ]; then
            echo "  (Run with --verbose to see details)"
        fi
    else
        echo -e "${RED}❌ FAILED${NC}"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        if [ "$VERBOSE" = false ]; then
            echo "Last 20 lines of output:"
            tail -20 /tmp/validation_output.txt
        fi
    fi
}

# Define validators to test
declare -A VALIDATORS=(
    ["espn_scoreboard"]="validation/validators/raw/espn_scoreboard_validator.py"
    ["bdl_boxscores"]="validation/validators/raw/bdl_boxscores_validator.py"
    ["nbac_gamebook"]="validation/validators/raw/nbac_gamebook_validator.py"
    ["nbac_schedule"]="validation/validators/raw/nbac_schedule_validator.py"
    ["odds_api_props"]="validation/validators/raw/odds_api_props_validator.py"
)

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}Running Validation Tests${NC}"
echo -e "${BLUE}================================================${NC}"

# Run tests
if [ -n "$SPECIFIC_PROCESSOR" ]; then
    # Test specific processor
    if [ -n "${VALIDATORS[$SPECIFIC_PROCESSOR]}" ]; then
        run_validator "$SPECIFIC_PROCESSOR" "${VALIDATORS[$SPECIFIC_PROCESSOR]}"
    else
        echo -e "${RED}Error: Unknown processor '$SPECIFIC_PROCESSOR'${NC}"
        echo "Available processors:"
        for key in "${!VALIDATORS[@]}"; do
            echo "  - $key"
        done
        exit 1
    fi
else
    # Test all processors
    for processor in "${!VALIDATORS[@]}"; do
        script="${VALIDATORS[$processor]}"
        
        # Check if validator script exists
        if [ ! -f "$script" ]; then
            echo -e "${YELLOW}⚠️  Skipping $processor (script not found: $script)${NC}"
            continue
        fi
        
        run_validator "$processor" "$script"
    done
fi

# Summary
echo ""
echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}Test Summary${NC}"
echo -e "${BLUE}================================================${NC}"
echo "Total Tests: $TOTAL_TESTS"
echo -e "${GREEN}Passed: $PASSED_TESTS${NC}"
echo -e "${YELLOW}Warnings: $WARNED_TESTS${NC}"
echo -e "${RED}Failed: $FAILED_TESTS${NC}"
echo ""

# Calculate pass rate
if [ $TOTAL_TESTS -gt 0 ]; then
    PASS_RATE=$((($PASSED_TESTS + $WARNED_TESTS) * 100 / $TOTAL_TESTS))
    echo "Pass Rate: $PASS_RATE%"
fi

# Check BigQuery results
echo ""
echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}Recent Validation Results (BigQuery)${NC}"
echo -e "${BLUE}================================================${NC}"

bq query --use_legacy_sql=false --format=pretty "
SELECT 
  validation_timestamp,
  processor_name,
  overall_status,
  total_checks,
  passed_checks,
  failed_checks
FROM \`nba-props-platform.nba_processing.validation_runs\`
WHERE validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
ORDER BY validation_timestamp DESC
LIMIT 10
" 2>/dev/null || echo "Could not query BigQuery (check credentials)"

# Exit with appropriate code
if [ $FAILED_TESTS -gt 0 ]; then
    echo ""
    echo -e "${RED}Some tests failed. Review output above.${NC}"
    exit 1
elif [ $WARNED_TESTS -gt 0 ]; then
    echo ""
    echo -e "${YELLOW}All tests passed with warnings.${NC}"
    exit 2
else
    echo ""
    echo -e "${GREEN}All tests passed successfully!${NC}"
    exit 0
fi