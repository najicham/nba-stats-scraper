#!/bin/bash
# File: bin/monitoring/lib/config.sh
# Purpose: Configuration and constants for BettingPros validation

# Project configuration
PROJECT="nba-props-platform"
BUCKET="gs://nba-scraped-data"
BP_EVENTS_PATH="bettingpros/events"
BP_PROPS_PATH="bettingpros/player-props/points"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

# Known missing dates (from the 14 identified issues)
KNOWN_MISSING_DATES=(
    "2021-10-03" "2021-10-04" "2021-10-05" "2021-10-06" "2021-10-07"
    "2021-10-08" "2021-10-09" "2021-10-10" "2021-10-11" "2021-10-12"
    "2021-10-13" "2021-10-14" "2021-10-15" "2021-11-07"
)

# Schedule data cache directory (Mac-compatible)
SCHEDULE_CACHE_DIR="/tmp/bp_schedule_cache_$$"
mkdir -p "$SCHEDULE_CACHE_DIR"