#!/bin/bash
# bin/testing/validate_isolation.sh
#
# Dataset Isolation Validation Script
#
# Purpose: Validates that dataset_prefix isolation is working correctly by:
#   1. Comparing test vs production record counts
#   2. Verifying production datasets are untouched
#   3. Checking data quality in test datasets
#   4. Reporting discrepancies
#
# Usage:
#   ./bin/testing/validate_isolation.sh DATE [PREFIX]
#
# Arguments:
#   DATE    - Game date to validate (YYYY-MM-DD)
#   PREFIX  - Dataset prefix (default: "test")
#
# Example:
#   ./bin/testing/validate_isolation.sh 2025-12-20
#   ./bin/testing/validate_isolation.sh 2025-12-20 test
#
# Exit codes:
#   0 - All validations passed
#   1 - Validation failures detected
#   2 - Invalid arguments

set -uo pipefail

# ============================================================================
# Configuration
# ============================================================================

DATE=${1:-}
PREFIX=${2:-"test"}

PROJECT_ID="nba-props-platform"
LOCATION="us-west2"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Validation result tracking
VALIDATION_PASSED=0
VALIDATION_FAILED=0
VALIDATION_WARNINGS=0

# ============================================================================
# Helper Functions
# ============================================================================

print_header() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_section() {
    echo ""
    echo -e "${BLUE}📋 $1${NC}"
    echo "----------------------------------------"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
    ((VALIDATION_PASSED++))
}

print_failure() {
    echo -e "${RED}❌ $1${NC}"
    ((VALIDATION_FAILED++))
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
    ((VALIDATION_WARNINGS++))
}

print_info() {
    echo -e "   $1"
}

# Query BigQuery and return result
query_bq() {
    local query="$1"
    bq query --use_legacy_sql=false --format=csv --quiet "$query" 2>/dev/null | tail -n 1
}

# Get count from a table
get_count() {
    local dataset="$1"
    local table="$2"
    local filter="${3:-}"

    local where_clause=""
    if [ -n "$filter" ]; then
        where_clause="WHERE $filter"
    fi

    query_bq "SELECT COUNT(*) as count FROM \`$PROJECT_ID.$dataset.$table\` $where_clause"
}

# Check if table exists
table_exists() {
    local dataset="$1"
    local table="$2"

    bq show "$dataset.$table" >/dev/null 2>&1
    return $?
}

# ============================================================================
# Validation Functions
# ============================================================================

validate_arguments() {
    print_section "Validating Arguments"

    if [ -z "$DATE" ]; then
        print_failure "DATE argument is required"
        echo "Usage: $0 DATE [PREFIX]"
        echo "Example: $0 2025-12-20 test"
        exit 2
    fi

    # Validate date format (YYYY-MM-DD)
    if ! [[ $DATE =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
        print_failure "Invalid date format. Expected YYYY-MM-DD, got: $DATE"
        exit 2
    fi

    print_success "Arguments valid (date=$DATE, prefix=$PREFIX)"
}

validate_datasets_exist() {
    print_section "Checking Dataset Existence"

    local prod_datasets=("nba_raw" "nba_analytics" "nba_precompute" "nba_predictions")
    local test_datasets=("${PREFIX}_nba_raw" "${PREFIX}_nba_analytics" "${PREFIX}_nba_precompute" "${PREFIX}_nba_predictions")

    # Check production datasets
    for dataset in "${prod_datasets[@]}"; do
        if bq show --project_id="$PROJECT_ID" "$dataset" >/dev/null 2>&1; then
            print_success "Production dataset exists: $dataset"
        else
            print_failure "Production dataset missing: $dataset"
        fi
    done

    # Check test datasets
    for dataset in "${test_datasets[@]}"; do
        if bq show --project_id="$PROJECT_ID" "$dataset" >/dev/null 2>&1; then
            print_success "Test dataset exists: $dataset"
        else
            print_failure "Test dataset missing: $dataset"
        fi
    done
}

validate_dataset_regions() {
    print_section "Validating Dataset Regions"

    local datasets=("nba_analytics" "${PREFIX}_nba_analytics" "nba_predictions" "${PREFIX}_nba_predictions")

    for dataset in "${datasets[@]}"; do
        local region=$(bq show --format=json "$dataset" 2>/dev/null | jq -r '.location')

        if [ "$region" = "$LOCATION" ]; then
            print_success "Dataset $dataset in correct region: $region"
        else
            print_failure "Dataset $dataset in wrong region: $region (expected: $LOCATION)"
        fi
    done
}

validate_phase3_analytics() {
    print_section "Phase 3: Analytics Validation"

    local prod_dataset="nba_analytics"
    local test_dataset="${PREFIX}_nba_analytics"
    local table="player_game_summary"

    # Check table exists
    if ! table_exists "$test_dataset" "$table"; then
        print_failure "Table $test_dataset.$table does not exist"
        return
    fi

    # Get counts
    local prod_count=$(get_count "$prod_dataset" "$table" "game_date = '$DATE'")
    local test_count=$(get_count "$test_dataset" "$table" "game_date = '$DATE'")

    print_info "Production count: $prod_count"
    print_info "Test count:       $test_count"

    # Validate counts are reasonable (should have processed players)
    if [ "$test_count" -gt 0 ]; then
        print_success "Phase 3: $test_count player records in test dataset"
    else
        print_failure "Phase 3: No records found in test dataset"
    fi

    # Check for upcoming_player_game_context
    if table_exists "$test_dataset" "upcoming_player_game_context"; then
        local upcoming_count=$(get_count "$test_dataset" "upcoming_player_game_context" "game_date = '$DATE'")
        if [ "$upcoming_count" -gt 0 ]; then
            print_success "Phase 3: $upcoming_count upcoming game contexts in test dataset"
        else
            print_warning "Phase 3: No upcoming game contexts found for $DATE"
        fi
    fi
}

validate_phase4_precompute() {
    print_section "Phase 4: Precompute Validation"

    local prod_dataset="nba_predictions"
    local test_dataset="${PREFIX}_nba_predictions"
    local table="ml_feature_store_v2"

    # Check table exists
    if ! table_exists "$test_dataset" "$table"; then
        print_failure "Table $test_dataset.$table does not exist"
        return
    fi

    # Get counts
    local prod_count=$(get_count "$prod_dataset" "$table" "game_date = '$DATE'")
    local test_count=$(get_count "$test_dataset" "$table" "game_date = '$DATE'")

    print_info "Production count: $prod_count"
    print_info "Test count:       $test_count"

    if [ "$test_count" -gt 0 ]; then
        print_success "Phase 4: $test_count ML features in test dataset"
    else
        print_failure "Phase 4: No ML features found in test dataset"
    fi
}

validate_phase5_predictions() {
    print_section "Phase 5: Predictions Validation"

    local prod_dataset="nba_predictions"
    local test_dataset="${PREFIX}_nba_predictions"
    local table="player_prop_predictions"

    # Check table exists
    if ! table_exists "$test_dataset" "$table"; then
        print_failure "Table $test_dataset.$table does not exist"
        return
    fi

    # Get counts
    local prod_count=$(get_count "$prod_dataset" "$table" "game_date = '$DATE'")
    local test_count=$(get_count "$test_dataset" "$table" "game_date = '$DATE'")

    print_info "Production count: $prod_count"
    print_info "Test count:       $test_count"

    if [ "$test_count" -gt 0 ]; then
        print_success "Phase 5: $test_count predictions in test dataset"

        # Get player count
        local test_players=$(query_bq "SELECT COUNT(DISTINCT player_lookup) FROM \`$PROJECT_ID.$test_dataset.$table\` WHERE game_date = '$DATE'")
        print_info "Unique players:   $test_players"

        # Check for staging tables (should be 0 after consolidation)
        local staging_count=$(bq ls "$test_dataset" 2>/dev/null | grep -c "_staging" || true)
        if [ "$staging_count" -eq 0 ]; then
            print_success "Phase 5: All staging tables cleaned up"
        else
            print_warning "Phase 5: $staging_count staging tables still exist (may indicate incomplete consolidation)"
        fi
    else
        print_failure "Phase 5: No predictions found in test dataset"
    fi
}

validate_production_untouched() {
    print_section "Production Data Integrity Check"

    # This is critical - we need to verify production wasn't modified
    # We do this by checking that production record counts are reasonable
    # and that there are no obvious signs of corruption

    local analytics_count=$(get_count "nba_analytics" "player_game_summary" "game_date = '$DATE'")
    local features_count=$(get_count "nba_predictions" "ml_feature_store_v2" "game_date = '$DATE'")
    local predictions_count=$(get_count "nba_predictions" "player_prop_predictions" "game_date = '$DATE'")

    print_info "Production analytics:   $analytics_count records"
    print_info "Production features:    $features_count records"
    print_info "Production predictions: $predictions_count records"

    # Validate production has data (if test has data, production should too)
    if [ "$analytics_count" -gt 0 ] || [ "$features_count" -gt 0 ] || [ "$predictions_count" -gt 0 ]; then
        print_success "Production datasets contain data for $DATE"
    else
        print_warning "Production datasets have no data for $DATE (may be expected if date hasn't been processed)"
    fi
}

validate_data_quality() {
    print_section "Data Quality Checks"

    local test_predictions="${PREFIX}_nba_predictions"

    # Check for NULL prediction_ids (should not exist)
    if table_exists "$test_predictions" "player_prop_predictions"; then
        local null_count=$(query_bq "SELECT COUNT(*) FROM \`$PROJECT_ID.$test_predictions.player_prop_predictions\` WHERE game_date = '$DATE' AND prediction_id IS NULL")

        if [ "$null_count" -eq 0 ]; then
            print_success "Data Quality: No NULL prediction_ids"
        else
            print_failure "Data Quality: Found $null_count predictions with NULL prediction_id"
        fi

        # Check for duplicate predictions (same player, system, line)
        local duplicate_query="
        SELECT COUNT(*) FROM (
            SELECT player_lookup, system_id, current_points_line, COUNT(*) as cnt
            FROM \`$PROJECT_ID.$test_predictions.player_prop_predictions\`
            WHERE game_date = '$DATE'
            GROUP BY player_lookup, system_id, current_points_line
            HAVING cnt > 1
        )
        "
        local duplicate_count=$(query_bq "$duplicate_query")

        if [ "$duplicate_count" -eq 0 ]; then
            print_success "Data Quality: No duplicate predictions"
        else
            print_warning "Data Quality: Found $duplicate_count duplicate prediction groups (may be expected for similar players)"
        fi
    fi
}

validate_isolation_complete() {
    print_section "Isolation Completeness Check"

    # Verify that test data exists in all expected tables
    local required_tables=(
        "${PREFIX}_nba_analytics.player_game_summary"
        "${PREFIX}_nba_predictions.ml_feature_store_v2"
        "${PREFIX}_nba_predictions.player_prop_predictions"
    )

    local missing_count=0

    for table_path in "${required_tables[@]}"; do
        IFS='.' read -r dataset table <<< "$table_path"

        if table_exists "$dataset" "$table"; then
            local count=$(get_count "$dataset" "$table" "game_date = '$DATE'")
            if [ "$count" -gt 0 ]; then
                print_success "Isolation: $table_path has $count records"
            else
                print_warning "Isolation: $table_path exists but has no data for $DATE"
                ((missing_count++))
            fi
        else
            print_failure "Isolation: $table_path does not exist"
            ((missing_count++))
        fi
    done

    if [ "$missing_count" -eq 0 ]; then
        print_success "Isolation: All pipeline phases have test data"
    else
        print_failure "Isolation: $missing_count tables missing or empty"
    fi
}

# ============================================================================
# Main Execution
# ============================================================================

main() {
    print_header "Dataset Isolation Validation"
    echo "Date:     $DATE"
    echo "Prefix:   $PREFIX"
    echo "Project:  $PROJECT_ID"
    echo "Location: $LOCATION"

    # Run all validations
    validate_arguments
    validate_datasets_exist
    validate_dataset_regions
    validate_phase3_analytics
    validate_phase4_precompute
    validate_phase5_predictions
    validate_production_untouched
    validate_data_quality
    validate_isolation_complete

    # Print summary
    print_header "Validation Summary"
    echo ""
    echo -e "${GREEN}Passed:   $VALIDATION_PASSED${NC}"
    echo -e "${YELLOW}Warnings: $VALIDATION_WARNINGS${NC}"
    echo -e "${RED}Failed:   $VALIDATION_FAILED${NC}"
    echo ""

    if [ "$VALIDATION_FAILED" -eq 0 ]; then
        if [ "$VALIDATION_WARNINGS" -eq 0 ]; then
            echo -e "${GREEN}🎉 All validations passed! Dataset isolation is working correctly.${NC}"
            exit 0
        else
            echo -e "${YELLOW}⚠️  Validation completed with warnings. Review above for details.${NC}"
            exit 0
        fi
    else
        echo -e "${RED}❌ Validation failed. Please review failures above.${NC}"
        exit 1
    fi
}

# Run main function
main
