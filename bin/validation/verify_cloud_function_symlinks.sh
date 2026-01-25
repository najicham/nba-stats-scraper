#!/bin/bash
# verify_cloud_function_symlinks.sh
#
# PURPOSE:
# Verify that all cloud function shared directories have been properly
# consolidated to symlinks pointing to the root /shared/ directory.
#
# USAGE:
#   ./bin/validation/verify_cloud_function_symlinks.sh
#
# EXIT CODES:
#   0 - All symlinks valid
#   1 - One or more symlinks invalid or missing

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Cloud functions to verify
CLOUD_FUNCTIONS=(
    "auto_backfill_orchestrator"
    "daily_health_summary"
    "phase2_to_phase3"
    "phase3_to_phase4"
    "phase4_to_phase5"
    "phase5_to_phase6"
    "self_heal"
)

# Critical files that must be symlinks
CRITICAL_FILES=(
    "utils/completeness_checker.py"
    "utils/bigquery_utils.py"
    "utils/bigquery_utils_v2.py"
    "config/orchestration_config.py"
    "validation/phase_boundary_validator.py"
    "processors/patterns/early_exit_mixin.py"
)

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Cloud Function Symlink Verification${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

total_verified=0
total_failed=0
total_skipped=0

# Verify each cloud function
for cf in "${CLOUD_FUNCTIONS[@]}"; do
    echo -e "${BLUE}Verifying: $cf${NC}"
    cf_dir="$PROJECT_ROOT/orchestration/cloud_functions/$cf"

    if [[ ! -d "$cf_dir/shared" ]]; then
        echo -e "${YELLOW}  ⚠ No shared directory found (skipping)${NC}"
        total_skipped=$((total_skipped + 1))
        continue
    fi

    cf_verified=0
    cf_failed=0

    # Check critical files
    for file in "${CRITICAL_FILES[@]}"; do
        file_path="$cf_dir/shared/$file"

        # Skip if file doesn't exist in this cloud function
        if [[ ! -e "$file_path" && ! -L "$file_path" ]]; then
            continue
        fi

        # Check if it's a symlink
        if [[ -L "$file_path" ]]; then
            # Verify target exists and is readable
            if [[ -r "$file_path" ]]; then
                target=$(readlink -f "$file_path")
                echo -e "${GREEN}  ✓ $file -> $(readlink "$file_path")${NC}"
                cf_verified=$((cf_verified + 1))
            else
                echo -e "${RED}  ✗ $file -> broken symlink${NC}"
                cf_failed=$((cf_failed + 1))
            fi
        else
            echo -e "${RED}  ✗ $file is not a symlink (should be consolidated)${NC}"
            cf_failed=$((cf_failed + 1))
        fi
    done

    total_verified=$((total_verified + cf_verified))
    total_failed=$((total_failed + cf_failed))

    if [[ $cf_failed -eq 0 ]]; then
        echo -e "${GREEN}  Status: OK ($cf_verified verified)${NC}"
    else
        echo -e "${RED}  Status: FAILED ($cf_failed errors)${NC}"
    fi
    echo ""
done

# Final summary
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "Total verified: ${GREEN}$total_verified${NC}"
echo -e "Total failed: ${RED}$total_failed${NC}"
echo -e "Total skipped: ${YELLOW}$total_skipped${NC}"
echo ""

if [[ $total_failed -eq 0 ]]; then
    echo -e "${GREEN}✓ All symlinks valid${NC}"
    exit 0
else
    echo -e "${RED}✗ Some symlinks invalid or missing${NC}"
    echo -e "${YELLOW}Run: ./bin/operations/consolidate_cloud_function_shared.sh${NC}"
    exit 1
fi
