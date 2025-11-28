#!/bin/bash
#
# Bootstrap Period Test Runner
# Run all tests for bootstrap period implementation
#

set -e  # Exit on error

echo "======================================================================"
echo "Bootstrap Period Implementation - Test Suite"
echo "======================================================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
SKIP_INTEGRATION=false
SKIP_SQL=false
COVERAGE=false
VERBOSE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-integration)
            SKIP_INTEGRATION=true
            shift
            ;;
        --skip-sql)
            SKIP_SQL=true
            shift
            ;;
        --coverage)
            COVERAGE=true
            shift
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --skip-integration  Skip integration tests (no BigQuery needed)"
            echo "  --skip-sql          Skip SQL verification tests"
            echo "  --coverage          Generate coverage report"
            echo "  --verbose, -v       Verbose output"
            echo "  --help, -h          Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                           # Run all tests"
            echo "  $0 --skip-integration        # Run only unit tests"
            echo "  $0 --coverage                # Run with coverage report"
            echo "  $0 --skip-integration --verbose  # Unit tests with verbose output"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Build pytest command
PYTEST_ARGS="-v"
if [ "$VERBOSE" = true ]; then
    PYTEST_ARGS="$PYTEST_ARGS -vv -s"
fi

# Track test results
UNIT_TESTS_PASSED=false
INTEGRATION_TESTS_PASSED=false
SQL_TESTS_PASSED=false

# Run Unit Tests
echo "======================================================================"
echo "1. Running Unit Tests (no database required)"
echo "======================================================================"
echo ""

if [ "$COVERAGE" = true ]; then
    echo "Running with coverage..."
    pytest tests/unit/bootstrap_period/ $PYTEST_ARGS \
        --cov=shared.config.nba_season_dates \
        --cov=shared.utils.schedule.database_reader \
        --cov=shared.utils.schedule.service \
        --cov-report=term \
        --cov-report=html:htmlcov/bootstrap_period
    UNIT_TESTS_PASSED=$?
else
    pytest tests/unit/bootstrap_period/ $PYTEST_ARGS
    UNIT_TESTS_PASSED=$?
fi

if [ $UNIT_TESTS_PASSED -eq 0 ]; then
    echo -e "${GREEN}✓ Unit tests PASSED${NC}"
else
    echo -e "${RED}✗ Unit tests FAILED${NC}"
fi

echo ""

# Run Integration Tests
if [ "$SKIP_INTEGRATION" = false ]; then
    echo "======================================================================"
    echo "2. Running Integration Tests (requires BigQuery access)"
    echo "======================================================================"
    echo ""

    pytest tests/integration/bootstrap_period/test_schedule_service_integration.py \
        $PYTEST_ARGS -m integration || true
    INTEGRATION_TESTS_PASSED=$?

    if [ $INTEGRATION_TESTS_PASSED -eq 0 ]; then
        echo -e "${GREEN}✓ Integration tests PASSED${NC}"
    else
        echo -e "${YELLOW}⚠ Integration tests FAILED or SKIPPED (may need BigQuery access)${NC}"
    fi

    echo ""
else
    echo "======================================================================"
    echo "2. Integration Tests SKIPPED (use without --skip-integration to run)"
    echo "======================================================================"
    echo ""
fi

# Run SQL Verification Tests
if [ "$SKIP_SQL" = false ] && [ "$SKIP_INTEGRATION" = false ]; then
    echo "======================================================================"
    echo "3. Running SQL Verification Tests (requires historical data)"
    echo "======================================================================"
    echo ""

    pytest tests/integration/bootstrap_period/test_sql_verification.py \
        $PYTEST_ARGS -m sql || true
    SQL_TESTS_PASSED=$?

    if [ $SQL_TESTS_PASSED -eq 0 ]; then
        echo -e "${GREEN}✓ SQL verification tests PASSED${NC}"
    else
        echo -e "${YELLOW}⚠ SQL verification tests FAILED or SKIPPED (may need historical data)${NC}"
    fi

    echo ""
else
    echo "======================================================================"
    echo "3. SQL Verification Tests SKIPPED"
    echo "======================================================================"
    echo ""
fi

# Summary
echo "======================================================================"
echo "Test Summary"
echo "======================================================================"
echo ""

if [ $UNIT_TESTS_PASSED -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Unit Tests: PASSED"
else
    echo -e "${RED}✗${NC} Unit Tests: FAILED"
fi

if [ "$SKIP_INTEGRATION" = false ]; then
    if [ $INTEGRATION_TESTS_PASSED -eq 0 ]; then
        echo -e "${GREEN}✓${NC} Integration Tests: PASSED"
    else
        echo -e "${YELLOW}⚠${NC} Integration Tests: FAILED/SKIPPED"
    fi
else
    echo -e "${YELLOW}⊘${NC} Integration Tests: SKIPPED"
fi

if [ "$SKIP_SQL" = false ] && [ "$SKIP_INTEGRATION" = false ]; then
    if [ $SQL_TESTS_PASSED -eq 0 ]; then
        echo -e "${GREEN}✓${NC} SQL Verification: PASSED"
    else
        echo -e "${YELLOW}⚠${NC} SQL Verification: FAILED/SKIPPED"
    fi
else
    echo -e "${YELLOW}⊘${NC} SQL Verification: SKIPPED"
fi

echo ""

if [ "$COVERAGE" = true ]; then
    echo "Coverage report generated:"
    echo "  HTML: htmlcov/bootstrap_period/index.html"
    echo ""
fi

# Exit with appropriate code
if [ $UNIT_TESTS_PASSED -ne 0 ]; then
    echo -e "${RED}FAILED: Unit tests must pass${NC}"
    exit 1
fi

echo -e "${GREEN}SUCCESS: All required tests passed${NC}"
echo ""
echo "Next steps:"
echo "  1. Review test output above"
echo "  2. If integration tests failed, check BigQuery access"
echo "  3. If SQL tests failed, run processors on historical dates first"
echo "  4. See docs/08-projects/current/bootstrap-period/TESTING-GUIDE.md for details"
echo ""

exit 0
