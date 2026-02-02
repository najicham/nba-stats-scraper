#!/bin/bash
# Process recent player trades and update the registry
#
# Usage:
#   ./bin/process-player-movement.sh [OPTIONS]
#
# Options:
#   --lookback-hours N    How many hours back to look for trades (default: 24)
#   --season-year YYYY    NBA season starting year (default: current season)
#   --test-mode           Run in test mode (uses test tables)
#
# Examples:
#   # Process trades from last 24 hours
#   ./bin/process-player-movement.sh
#
#   # Process trades from last 48 hours
#   ./bin/process-player-movement.sh --lookback-hours 48
#
#   # Process trades for specific season
#   ./bin/process-player-movement.sh --season-year 2025
#
#   # Test mode
#   ./bin/process-player-movement.sh --test-mode

set -e

# Change to script directory
cd "$(dirname "$0")/.."

# Run the processor
PYTHONPATH=. python data_processors/reference/player_reference/player_movement_registry_processor.py "$@"
