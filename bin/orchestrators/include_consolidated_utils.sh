#!/bin/bash
# Helper function to include consolidated orchestration.shared.utils in deployment builds
#
# After Session 20 consolidation (125,667 lines eliminated), utilities are centralized at:
# orchestration/shared/utils/
#
# This script should be sourced by deployment scripts AFTER creating BUILD_DIR
# and AFTER initial rsync of the function source.
#
# Usage:
#   source bin/orchestrators/include_consolidated_utils.sh
#   include_consolidated_utils "$BUILD_DIR"

function include_consolidated_utils() {
    local build_dir="$1"

    if [ -z "$build_dir" ]; then
        echo -e "${RED}Error: BUILD_DIR not provided to include_consolidated_utils${NC}"
        return 1
    fi

    if [ ! -d "$build_dir" ]; then
        echo -e "${RED}Error: BUILD_DIR does not exist: $build_dir${NC}"
        return 1
    fi

    echo -e "${YELLOW}Including consolidated orchestration.shared.utils...${NC}"

    # Create orchestration package structure
    mkdir -p "$build_dir/orchestration/shared"

    # Copy consolidated utilities
    if [ -d "orchestration/shared/utils" ]; then
        rsync -aL --exclude='__pycache__' --exclude='*.pyc' \
            "orchestration/shared/utils/" "$build_dir/orchestration/shared/utils/"
    else
        echo -e "${RED}Error: orchestration/shared/utils directory not found${NC}"
        return 1
    fi

    # Copy orchestration/shared/__init__.py if it exists
    if [ -f "orchestration/shared/__init__.py" ]; then
        rsync -aL --exclude='__pycache__' --exclude='*.pyc' \
            "orchestration/shared/__init__.py" "$build_dir/orchestration/shared/__init__.py"
    fi

    # Create __init__.py for orchestration package
    echo "# Orchestration package" > "$build_dir/orchestration/__init__.py"

    echo -e "${GREEN}✓ Consolidated utils included (orchestration.shared.utils)${NC}"
    return 0
}
