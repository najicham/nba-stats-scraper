#!/bin/bash
# File: bin/validation/test_validation.sh
# Purpose: Test validation scripts and infrastructure locally
# Usage: ./bin/validation/test_validation.sh [test_name]

set -e

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_SKIPPED=0

print_header() {
    echo -e "${CYAN}========================================"
    echo -e "Validation Test Suite"
    echo -e "========================================${NC}"
    echo -e "Time: $(date)"
    echo -e "Project: ${PROJECT_ID}"
    echo ""
}

show_usage() {
    echo "Usage: $0 [test_name]"
    echo ""
    echo "Available tests:"
    echo "  all          - Run all tests (default)"
    echo "  gcloud       - Test gcloud connectivity"
    echo "  bigquery     - Test BigQuery access"
    echo "  gcs          - Test GCS access"
    echo "  scripts      - Test validation scripts exist and are executable"
    echo "  python       - Test Python validation script"
    echo ""
    echo "Options:"
    echo "  --verbose    - Show detailed output"
}

# Run a single test
run_test() {
    local test_name="$1"
    local test_cmd="$2"
    local description="$3"

    echo -n -e "  ${BLUE}Testing:${NC} ${description}... "

    if eval "$test_cmd" >/dev/null 2>&1; then
        echo -e "${GREEN}PASSED${NC}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        echo -e "${RED}FAILED${NC}"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
}

# Skip a test
skip_test() {
    local description="$1"
    local reason="$2"

    echo -e "  ${YELLOW}Skipping:${NC} ${description} (${reason})"
    TESTS_SKIPPED=$((TESTS_SKIPPED + 1))
}

# Test gcloud connectivity
test_gcloud() {
    echo -e "${CYAN}Testing gcloud connectivity...${NC}"

    run_test "gcloud_installed" "command -v gcloud" "gcloud CLI installed"
    run_test "gcloud_auth" "gcloud auth print-identity-token" "gcloud authenticated"
    run_test "gcloud_project" "gcloud config get-value project" "gcloud project configured"

    echo ""
}

# Test BigQuery access
test_bigquery() {
    echo -e "${CYAN}Testing BigQuery access...${NC}"

    run_test "bq_installed" "command -v bq" "bq CLI installed"

    # Test query execution
    local bq_test="bq query --use_legacy_sql=false --format=json 'SELECT 1 as test'"
    run_test "bq_query" "$bq_test" "BigQuery query execution"

    # Test table access
    local table_check="bq show ${PROJECT_ID}:nba_raw.nbac_gamebook_player_stats"
    run_test "bq_table" "$table_check" "BigQuery table access"

    echo ""
}

# Test GCS access
test_gcs() {
    echo -e "${CYAN}Testing GCS access...${NC}"

    run_test "gsutil_installed" "command -v gcloud" "gcloud storage CLI installed"

    # Test bucket access
    local bucket_check="gcloud storage ls gs://nba-scraped-data/ --project=${PROJECT_ID}"
    run_test "gcs_bucket" "$bucket_check" "GCS bucket access"

    echo ""
}

# Test validation scripts exist and are executable
test_scripts() {
    echo -e "${CYAN}Testing validation scripts...${NC}"

    # List of scripts to check
    local scripts=(
        "${SCRIPT_DIR}/run_validation.sh"
        "${SCRIPT_DIR}/deploy_validation_runner.sh"
        "${SCRIPT_DIR}/setup_validation_schedulers.sh"
        "${SCRIPT_DIR}/validate_gcs_bq_completeness.py"
    )

    for script in "${scripts[@]}"; do
        local script_name=$(basename "$script")
        if [[ -f "$script" ]]; then
            run_test "script_${script_name}" "test -f '$script'" "Script exists: ${script_name}"

            if [[ -x "$script" ]] || [[ "$script" == *.py ]]; then
                echo -e "    ${GREEN}Executable/Python${NC}"
            else
                echo -e "    ${YELLOW}Not executable (chmod +x may be needed)${NC}"
            fi
        else
            echo -e "  ${RED}Missing:${NC} ${script_name}"
            TESTS_FAILED=$((TESTS_FAILED + 1))
        fi
    done

    echo ""
}

# Test Python validation script
test_python() {
    echo -e "${CYAN}Testing Python validation...${NC}"

    run_test "python_installed" "command -v python3" "Python 3 installed"

    # Check Python script syntax
    local py_script="${SCRIPT_DIR}/validate_gcs_bq_completeness.py"
    if [[ -f "$py_script" ]]; then
        run_test "python_syntax" "python3 -m py_compile '$py_script'" "Python syntax valid"

        # Test --help runs without error
        run_test "python_help" "python3 '$py_script' --help" "Python script --help"
    else
        skip_test "Python validation script" "File not found"
    fi

    # Check required Python packages
    local packages=("google-cloud-storage" "google-cloud-bigquery")
    for pkg in "${packages[@]}"; do
        run_test "python_pkg_${pkg}" "python3 -c 'import ${pkg//-/_}' 2>/dev/null || python3 -c 'import google.cloud'" "Python package: ${pkg}"
    done

    echo ""
}

# Print summary
print_summary() {
    local total=$((TESTS_PASSED + TESTS_FAILED + TESTS_SKIPPED))

    echo -e "${CYAN}========================================"
    echo -e "Test Summary"
    echo -e "========================================${NC}"
    echo -e "  ${GREEN}Passed:${NC}  ${TESTS_PASSED}"
    echo -e "  ${RED}Failed:${NC}  ${TESTS_FAILED}"
    echo -e "  ${YELLOW}Skipped:${NC} ${TESTS_SKIPPED}"
    echo -e "  Total:   ${total}"
    echo ""

    if [[ $TESTS_FAILED -eq 0 ]]; then
        echo -e "${GREEN}All tests passed!${NC}"
        return 0
    else
        echo -e "${RED}Some tests failed. Please fix the issues above.${NC}"
        return 1
    fi
}

# Run all tests
run_all_tests() {
    print_header

    test_gcloud
    test_bigquery
    test_gcs
    test_scripts
    test_python

    print_summary
}

# Main command handling
case "${1:-all}" in
    "all")
        run_all_tests
        ;;
    "gcloud")
        print_header
        test_gcloud
        print_summary
        ;;
    "bigquery"|"bq")
        print_header
        test_bigquery
        print_summary
        ;;
    "gcs")
        print_header
        test_gcs
        print_summary
        ;;
    "scripts")
        print_header
        test_scripts
        print_summary
        ;;
    "python")
        print_header
        test_python
        print_summary
        ;;
    "help"|"-h"|"--help")
        show_usage
        ;;
    *)
        echo "Unknown test: $1"
        show_usage
        exit 1
        ;;
esac
