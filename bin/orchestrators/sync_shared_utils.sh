#!/bin/bash
# Sync shared utilities to cloud function directories
#
# Cloud functions have copies of shared utilities that need to be kept in sync
# with the main shared/ directory. This script copies the fixed utilities
# to all cloud function directories.
#
# Run this after making changes to shared/ utilities.
#
# Usage:
#   ./bin/orchestrators/sync_shared_utils.sh
#
# Created: 2026-01-25

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get project root (script location -> bin/orchestrators -> project root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Syncing Shared Utilities to Cloud Functions${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Cloud function directories with shared utilities
CLOUD_FUNCTIONS=(
    "auto_backfill_orchestrator"
    "daily_health_summary"
    "phase2_to_phase3"
    "phase3_to_phase4"
    "phase4_to_phase5"
    "phase5_to_phase6"
    "self_heal"
)

# Utility files to sync (critical for streaming buffer fix)
UTILS_TO_SYNC=(
    "bigquery_utils.py"
    "bigquery_utils_v2.py"
    "phase_execution_logger.py"
    "completion_tracker.py"
    "proxy_health_logger.py"
    "proxy_manager.py"
    "sentry_config.py"
)

# Config files to sync
CONFIG_TO_SYNC=(
    "orchestration_config.py"
)

# Validation files to sync
VALIDATION_TO_SYNC=(
    "phase_boundary_validator.py"
)

# Schedule utils to sync
SCHEDULE_TO_SYNC=(
    "database_reader.py"
)

# Player registry files to sync
PLAYER_REGISTRY_TO_SYNC=(
    "reader.py"
)

# MLB player registry files to sync
MLB_PLAYER_REGISTRY_TO_SYNC=(
    "resolver.py"
)

# Completeness checker
COMPLETENESS_TO_SYNC=(
    "completeness_checker.py"
)

# Track counts
synced=0
skipped=0
errors=0

sync_file() {
    local src="$1"
    local dest="$2"

    if [ ! -f "$src" ]; then
        echo -e "  ${YELLOW}Skip${NC}: Source not found: $src"
        skipped=$((skipped + 1))
        return
    fi

    # Create destination directory if needed
    local dest_dir=$(dirname "$dest")
    if [ ! -d "$dest_dir" ]; then
        echo -e "  ${YELLOW}Skip${NC}: Dest dir not found: $dest_dir"
        skipped=$((skipped + 1))
        return
    fi

    # Copy file
    if cp "$src" "$dest" 2>/dev/null; then
        echo -e "  ${GREEN}Synced${NC}: $(basename $src)"
        synced=$((synced + 1))
    else
        echo -e "  ${RED}Error${NC}: Failed to copy $src"
        errors=$((errors + 1))
    fi
}

echo -e "${YELLOW}Syncing utilities to cloud functions...${NC}"
echo ""

for cf in "${CLOUD_FUNCTIONS[@]}"; do
    cf_path="$PROJECT_ROOT/orchestration/cloud_functions/$cf"

    if [ ! -d "$cf_path" ]; then
        echo -e "${YELLOW}Skipping $cf (directory not found)${NC}"
        continue
    fi

    echo -e "${BLUE}$cf:${NC}"

    # Sync utils
    for util in "${UTILS_TO_SYNC[@]}"; do
        sync_file "$PROJECT_ROOT/shared/utils/$util" "$cf_path/shared/utils/$util"
    done

    # Sync config
    for config in "${CONFIG_TO_SYNC[@]}"; do
        sync_file "$PROJECT_ROOT/shared/config/$config" "$cf_path/shared/config/$config"
    done

    # Sync validation
    for val in "${VALIDATION_TO_SYNC[@]}"; do
        sync_file "$PROJECT_ROOT/shared/validation/$val" "$cf_path/shared/validation/$val"
    done

    # Sync schedule utils
    if [ -d "$cf_path/shared/utils/schedule" ]; then
        for sched in "${SCHEDULE_TO_SYNC[@]}"; do
            sync_file "$PROJECT_ROOT/shared/utils/schedule/$sched" "$cf_path/shared/utils/schedule/$sched"
        done
    fi

    # Sync player registry
    if [ -d "$cf_path/shared/utils/player_registry" ]; then
        for pr in "${PLAYER_REGISTRY_TO_SYNC[@]}"; do
            sync_file "$PROJECT_ROOT/shared/utils/player_registry/$pr" "$cf_path/shared/utils/player_registry/$pr"
        done
    fi

    # Sync MLB player registry
    if [ -d "$cf_path/shared/utils/mlb_player_registry" ]; then
        for mlb in "${MLB_PLAYER_REGISTRY_TO_SYNC[@]}"; do
            sync_file "$PROJECT_ROOT/shared/utils/mlb_player_registry/$mlb" "$cf_path/shared/utils/mlb_player_registry/$mlb"
        done
    fi

    # Sync completeness checker (in utils root)
    for cc in "${COMPLETENESS_TO_SYNC[@]}"; do
        sync_file "$PROJECT_ROOT/shared/utils/$cc" "$cf_path/shared/utils/$cc"
    done

    echo ""
done

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Sync Complete!${NC}"
echo ""
echo "Summary:"
echo -e "  ${GREEN}Synced:${NC}  $synced files"
echo -e "  ${YELLOW}Skipped:${NC} $skipped files"
echo -e "  ${RED}Errors:${NC}  $errors files"
echo ""

if [ $errors -gt 0 ]; then
    echo -e "${RED}Some files failed to sync. Review errors above.${NC}"
    exit 1
fi

echo -e "${GREEN}All utilities synced successfully!${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Review changes: git diff orchestration/cloud_functions/*/shared/"
echo "2. Test locally before deploying"
echo "3. Deploy affected cloud functions"
