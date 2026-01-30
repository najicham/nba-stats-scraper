#!/bin/bash
# consolidate_cloud_function_shared.sh
#
# PURPOSE:
# Eliminate ~1.5MB of duplicated code across 7 cloud functions by replacing
# duplicated files with symlinks to the root /shared directory.
#
# PROBLEM:
# - completeness_checker.py (68 KB × 7 = 476 KB)
# - bigquery_utils.py (17 KB × 7 = 119 KB)
# - orchestration_config.py (16,142 lines × 7)
# - player_registry/reader.py (1,079 lines × 7)
# - Plus dozens of other utility files duplicated 7x
#
# SOLUTION:
# Replace duplicated files with symlinks pointing to /shared/
#
# USAGE:
#   ./bin/operations/consolidate_cloud_function_shared.sh [--dry-run] [--cloud-function <name>]
#
# OPTIONS:
#   --dry-run              Show what would be done without making changes
#   --cloud-function NAME  Only process the specified cloud function
#   --verify              Verify symlinks after creation
#
# SAFETY:
# - Creates backups before making changes
# - Validates that target files exist in root /shared
# - Can be run in dry-run mode to preview changes
#

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

# Configuration
DRY_RUN=false
VERIFY_ONLY=false
TARGET_FUNCTION=""
BACKUP_DIR="$PROJECT_ROOT/.backups/cloud_function_shared_$(date +%Y%m%d_%H%M%S)"

# Cloud functions to process
CLOUD_FUNCTIONS=(
    "auto_backfill_orchestrator"
    "daily_health_summary"
    "phase2_to_phase3"
    "phase3_to_phase4"
    "phase4_to_phase5"
    "phase5_to_phase6"
    "self_heal"
)

# Files and directories to consolidate
# Format: "relative/path/to/file"
FILES_TO_CONSOLIDATE=(
    # Utils
    "utils/completeness_checker.py"
    "utils/bigquery_utils.py"
    "utils/bigquery_utils_v2.py"
    "utils/completion_tracker.py"
    "utils/phase_execution_logger.py"
    "utils/proxy_health_logger.py"
    "utils/proxy_manager.py"
    "utils/sentry_config.py"
    "utils/alert_types.py"
    "utils/auth_utils.py"
    "utils/bigquery_client.py"
    "utils/bigquery_retry.py"
    "utils/data_freshness_checker.py"
    "utils/email_alerting.py"
    "utils/email_alerting_ses.py"
    "utils/enhanced_error_notifications.py"
    "utils/env_validation.py"
    "utils/game_id_converter.py"
    "utils/hash_utils.py"
    "utils/logging_utils.py"
    "utils/metrics_utils.py"
    "utils/mlb_game_id_converter.py"
    "utils/mlb_team_mapper.py"
    "utils/mlb_travel_info.py"
    "utils/nba_team_mapper.py"
    "utils/notification_system.py"
    "utils/odds_player_props_preference.py"
    "utils/odds_preference.py"
    "utils/player_name_normalizer.py"
    "utils/player_name_resolver.py"
    "utils/processor_alerting.py"
    "utils/prometheus_metrics.py"
    "utils/pubsub_client.py"
    "utils/pubsub_publishers.py"
    "utils/rate_limit_handler.py"
    "utils/rate_limiter.py"
    "utils/result.py"
    "utils/retry_with_jitter.py"
    "utils/roster_manager.py"
    "utils/scraper_logging.py"
    "utils/secrets.py"
    "utils/slack_channels.py"
    "utils/slack_retry.py"
    "utils/smart_alerting.py"
    "utils/storage_client.py"
    "utils/structured_logging.py"
    "utils/travel_team_info.py"
    "utils/validation.py"
    "utils/README.md"
    "utils/__init__.py"

    # Utils subdirectories
    "utils/mlb_player_registry"
    "utils/player_registry"
    "utils/schedule"
    "utils/tests"

    # Config
    "config/orchestration_config.py"
    "config/gcp_config.py"
    "config/feature_flags.py"
    "config/pubsub_topics.py"
    "config/rate_limit_config.py"
    "config/sport_config.py"
    "config/timeout_config.py"
    "config/nba_season_dates.py"
    "config/nba_teams.py"
    "config/espn_nba_team_abbr.py"
    "config/espn_nba_team_ids.py"
    "config/__init__.py"
    "config/data_sources"
    "config/source_coverage"
    "config/sports"

    # Processors
    "processors/patterns/early_exit_mixin.py"
    "processors/patterns/circuit_breaker_mixin.py"
    "processors/patterns/fallback_source_mixin.py"
    "processors/patterns/mlb_early_exit_mixin.py"
    "processors/patterns/quality_columns.py"
    "processors/patterns/quality_mixin.py"
    "processors/patterns/smart_skip_mixin.py"
    "processors/patterns/timeout_mixin.py"
    "processors/patterns/__init__.py"
    "processors/mixins"

    # Validation
    "validation/phase_boundary_validator.py"
    "validation/config.py"
    "validation/chain_config.py"
    "validation/feature_thresholds.py"
    "validation/firestore_state.py"
    "validation/historical_completeness.py"
    "validation/pubsub_models.py"
    "validation/run_history.py"
    "validation/time_awareness.py"
    "validation/README.md"
    "validation/__init__.py"
    "validation/context"
    "validation/output"
    "validation/validators"

    # Other shared directories
    "alerts"
    "backfill"
    "change_detection"
    "clients"
    "endpoints"
    "health"
    "publishers"
)

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --verify)
            VERIFY_ONLY=true
            shift
            ;;
        --cloud-function)
            TARGET_FUNCTION="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [--dry-run] [--verify] [--cloud-function <name>]"
            echo ""
            echo "Options:"
            echo "  --dry-run              Show what would be done without making changes"
            echo "  --verify               Verify symlinks after creation"
            echo "  --cloud-function NAME  Only process the specified cloud function"
            echo "  -h, --help             Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Create backup directory
create_backup_dir() {
    if [[ "$DRY_RUN" == "false" && "$VERIFY_ONLY" == "false" ]]; then
        mkdir -p "$BACKUP_DIR"
        log_info "Created backup directory: $BACKUP_DIR"
    fi
}

# Backup a file before replacing it
backup_file() {
    local file_path="$1"
    local cloud_function="$2"

    if [[ "$DRY_RUN" == "false" && "$VERIFY_ONLY" == "false" ]]; then
        local backup_path="$BACKUP_DIR/$cloud_function/$(dirname "$file_path")"
        mkdir -p "$backup_path"
        cp -a "$file_path" "$backup_path/"
    fi
}

# Check if a path exists and is a symlink
is_symlink() {
    [[ -L "$1" ]]
}

# Check if a path exists and is a regular file or directory
is_regular_path() {
    [[ -e "$1" && ! -L "$1" ]]
}

# Get the target of a symlink
get_symlink_target() {
    readlink "$1"
}

# Create a relative symlink
create_symlink() {
    local source_path="$1"  # Path to the file/dir in cloud function's shared/
    local target_path="$2"  # Path to the file/dir in root shared/

    # Calculate relative path from source to target
    local source_dir="$(dirname "$source_path")"
    local rel_path="$(realpath --relative-to="$source_dir" "$target_path")"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "Would create symlink: $source_path -> $rel_path"
    else
        # Remove existing file/directory
        if [[ -e "$source_path" || -L "$source_path" ]]; then
            rm -rf "$source_path"
        fi

        # Create symlink
        ln -s "$rel_path" "$source_path"
        log_success "Created symlink: $source_path -> $rel_path"
    fi
}

# Verify a symlink points to the correct target
verify_symlink() {
    local source_path="$1"
    local expected_target="$2"

    if is_symlink "$source_path"; then
        local actual_target="$(readlink -f "$source_path")"
        local expected_canonical="$(readlink -f "$expected_target")"

        if [[ "$actual_target" == "$expected_canonical" ]]; then
            log_success "Verified: $source_path -> $expected_target"
            return 0
        else
            log_error "Symlink mismatch: $source_path points to $actual_target, expected $expected_canonical"
            return 1
        fi
    else
        log_error "Not a symlink: $source_path"
        return 1
    fi
}

# Process a single cloud function
process_cloud_function() {
    local cloud_function="$1"
    local cf_shared_dir="$PROJECT_ROOT/orchestration/cloud_functions/$cloud_function/shared"
    local root_shared_dir="$PROJECT_ROOT/shared"

    log_info "Processing cloud function: $cloud_function"

    if [[ ! -d "$cf_shared_dir" ]]; then
        log_warning "Shared directory not found: $cf_shared_dir (skipping)"
        return 0
    fi

    local files_processed=0
    local files_skipped=0
    local files_created=0
    local files_verified=0
    local files_failed=0

    for file_path in "${FILES_TO_CONSOLIDATE[@]}"; do
        local cf_file="$cf_shared_dir/$file_path"
        local root_file="$root_shared_dir/$file_path"

        # Check if root file exists
        if [[ ! -e "$root_file" ]]; then
            log_warning "Root file not found: $root_file (skipping)"
            files_skipped=$((files_skipped + 1))
            continue
        fi

        # Check if cloud function file exists
        if [[ ! -e "$cf_file" && ! -L "$cf_file" ]]; then
            # File doesn't exist in cloud function, skip
            files_skipped=$((files_skipped + 1))
            continue
        fi

        # If verifying, check if symlink is correct
        if [[ "$VERIFY_ONLY" == "true" ]]; then
            if verify_symlink "$cf_file" "$root_file"; then
                files_verified=$((files_verified + 1))
            else
                files_failed=$((files_failed + 1))
            fi
            continue
        fi

        # Check if already a symlink pointing to the right place
        if is_symlink "$cf_file"; then
            if verify_symlink "$cf_file" "$root_file" 2>/dev/null; then
                log_info "Already symlinked: $cf_file"
                files_skipped=$((files_skipped + 1))
                continue
            else
                log_warning "Symlink exists but points to wrong target: $cf_file"
            fi
        fi

        # Backup and create symlink
        if is_regular_path "$cf_file"; then
            backup_file "$cf_file" "$cloud_function"
            create_symlink "$cf_file" "$root_file"
            files_created=$((files_created + 1))
        fi

        files_processed=$((files_processed + 1))
    done

    # Print summary for this cloud function
    echo ""
    log_info "Summary for $cloud_function:"
    log_info "  Files processed: $files_processed"
    log_info "  Symlinks created: $files_created"
    log_info "  Files skipped: $files_skipped"
    if [[ "$VERIFY_ONLY" == "true" ]]; then
        log_info "  Symlinks verified: $files_verified"
        log_info "  Verification failed: $files_failed"
    fi
    echo ""
}

# Main execution
main() {
    log_info "=== Cloud Function Shared Directory Consolidation ==="
    log_info "Project root: $PROJECT_ROOT"
    log_info "Dry run: $DRY_RUN"
    log_info "Verify only: $VERIFY_ONLY"
    echo ""

    # Create backup directory
    if [[ "$VERIFY_ONLY" == "false" ]]; then
        create_backup_dir
    fi

    # Process cloud functions
    if [[ -n "$TARGET_FUNCTION" ]]; then
        # Process only the specified cloud function
        process_cloud_function "$TARGET_FUNCTION"
    else
        # Process all cloud functions
        for cloud_function in "${CLOUD_FUNCTIONS[@]}"; do
            process_cloud_function "$cloud_function"
        done
    fi

    # Final summary
    log_success "=== Consolidation Complete ==="

    if [[ "$DRY_RUN" == "true" ]]; then
        log_warning "This was a dry run. No changes were made."
        log_info "Run without --dry-run to apply changes."
    elif [[ "$VERIFY_ONLY" == "true" ]]; then
        log_info "Verification complete."
    else
        log_success "Backups saved to: $BACKUP_DIR"
        log_info "Next steps:"
        log_info "  1. Test deployment of one cloud function to verify symlinks work"
        log_info "  2. Run with --verify to validate all symlinks"
        log_info "  3. Deploy all cloud functions"
        log_info ""
        log_warning "If you need to rollback, restore from: $BACKUP_DIR"
    fi
}

# Run main function
main
