#!/bin/bash
# Test Coverage Analysis for Critical Paths
#
# Identifies test coverage gaps in critical system components.
# Reports coverage for:
#   - Prediction pipeline (worker, coordinator)
#   - Data processors (Phase 2, 3, 4)
#   - Monitoring & validation
#
# Usage:
#   ./bin/test-coverage-critical-paths.sh [--html]
#
# Options:
#   --html    Generate HTML coverage report in htmlcov/

set -euo pipefail

GENERATE_HTML=false
if [ "${1:-}" = "--html" ]; then
    GENERATE_HTML=true
fi

echo "=============================================="
echo "TEST COVERAGE ANALYSIS: CRITICAL PATHS"
echo "=============================================="
echo ""

# Define critical paths
CRITICAL_PATHS=(
    "predictions/worker"
    "predictions/coordinator"
    "data_processors/analytics"
    "data_processors/precompute"
    "data_processors/raw"
    "bin/monitoring"
    "shared/utils"
)

echo "Critical paths to analyze:"
for path in "${CRITICAL_PATHS[@]}"; do
    echo "  - $path"
done
echo ""

# Run pytest with coverage for critical paths
echo "Running tests with coverage..."
echo ""

COVERAGE_PATHS=$(IFS=,; echo "${CRITICAL_PATHS[*]}")

if [ "$GENERATE_HTML" = true ]; then
    PYTHONPATH=. pytest tests/ \
        --cov="$COVERAGE_PATHS" \
        --cov-report=html \
        --cov-report=term-missing \
        --cov-report=term:skip-covered \
        -v \
        --tb=short || true

    echo ""
    echo "HTML coverage report generated: htmlcov/index.html"
    echo "Open with: open htmlcov/index.html"
else
    PYTHONPATH=. pytest tests/ \
        --cov="$COVERAGE_PATHS" \
        --cov-report=term-missing \
        --cov-report=term:skip-covered \
        -v \
        --tb=short || true
fi

echo ""
echo "=============================================="
echo "COVERAGE ANALYSIS COMPLETE"
echo "=============================================="
echo ""

# Identify critical files with low coverage
echo "Analyzing critical files with low coverage (<70%)..."
echo ""

# Extract coverage data
COVERAGE_DATA=$(PYTHONPATH=. pytest tests/ \
    --cov="$COVERAGE_PATHS" \
    --cov-report=term \
    --quiet \
    --tb=no 2>/dev/null || true)

# Parse coverage report
echo "$COVERAGE_DATA" | grep -E "^(predictions|data_processors|bin/monitoring|shared)" | \
    awk '{if ($NF < 70) print}' | sort -t% -k2 -n | \
    while read line; do
        FILE=$(echo "$line" | awk '{print $1}')
        COV=$(echo "$line" | awk '{print $NF}')
        echo "⚠️  $FILE: $COV% coverage"
    done

echo ""
echo "=============================================="
echo "CRITICAL PATH TEST RECOMMENDATIONS"
echo "=============================================="
echo ""

# Check for untested critical functions
echo "Priority areas for additional tests:"
echo ""

echo "1. Vegas Line Coverage Pipeline"
echo "   - VegasLineSummaryProcessor (data_processors/precompute/)"
echo "   - BettingPros scraper integration"
echo "   - Feature store Vegas line feature"
echo ""

echo "2. Prediction Quality"
echo "   - Model loading and inference (predictions/worker/)"
echo "   - Feature validation and quality checks"
echo "   - Batch prediction orchestration"
echo ""

echo "3. Data Pipeline Integrity"
echo "   - Phase 3 processors (player_game_summary)"
echo "   - Phase 4 processors (precompute features)"
echo "   - BigQuery write operations"
echo ""

echo "4. Deployment & Monitoring"
echo "   - Pre-deployment checks (bin/pre-deployment-checklist.sh)"
echo "   - Post-deployment validation"
echo "   - Automated rollback triggers"
echo ""

echo "=============================================="
echo "NEXT STEPS"
echo "=============================================="
echo ""
echo "To improve coverage:"
echo "  1. Run: ./bin/test-coverage-critical-paths.sh --html"
echo "  2. Open htmlcov/index.html to see detailed coverage"
echo "  3. Add tests for red/yellow highlighted code"
echo "  4. Focus on critical paths with <70% coverage"
echo "  5. Run: pytest tests/ --cov-report=term-missing"
echo ""
