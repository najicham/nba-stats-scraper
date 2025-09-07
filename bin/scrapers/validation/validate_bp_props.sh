#!/bin/bash
# File: bin/validation/validate_bp_props.sh
# Purpose: Main script for NBA BettingPros data validation
# Modular design - imports functionality from lib/ directory

set -e

# Get script directory for relative imports
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$SCRIPT_DIR/lib"

# Import library modules
source "$LIB_DIR/config.sh"
source "$LIB_DIR/utils.sh"
source "$LIB_DIR/gcs.sh"
source "$LIB_DIR/validation.sh"
source "$LIB_DIR/schedule.sh"
source "$LIB_DIR/commands.sh"

# Main command handling
main() {
    case "${1:-summary}" in
        "test")
            cmd_test
            ;;
        "summary")
            cmd_summary
            ;;
        "missing")
            cmd_missing
            ;;
        "recent")
            cmd_recent "${2:-3}"
            ;;
        "dates")
            shift  # Remove 'dates' command
            cmd_dates "$@"
            ;;
        "seasons")
            cmd_seasons
            ;;
        "debug")
            cmd_debug_schedule "${2:-2021-10-03}"
            ;;
        "help"|"-h"|"--help")
            show_usage
            ;;
        *)
            echo "Unknown command: $1"
            show_usage
            exit 1
            ;;
    esac
}

# Set up cleanup on exit
trap cleanup_temp_files EXIT

# Run main function with all arguments
main "$@"