#!/bin/bash
# Common validation utilities for backfill orchestrator
# Shared functions for BigQuery queries, logging, and formatting

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${CYAN}[$(date +'%H:%M:%S')]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[$(date +'%H:%M:%S')] ✅${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[$(date +'%H:%M:%S')] ⚠️${NC}  $1"
}

log_error() {
    echo -e "${RED}[$(date +'%H:%M:%S')] ❌${NC} $1"
}

log_section() {
    echo ""
    echo -e "${BLUE}════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════${NC}"
}

# BigQuery helper - run query and return result
bq_query() {
    local query="$1"
    local format="${2:-value}"  # default to value, can be csv, json, pretty

    bq query --use_legacy_sql=false --format="$format" "$query" 2>&1
}

# BigQuery helper - run query and get single numeric value
bq_query_value() {
    local query="$1"
    local result=$(bq query --use_legacy_sql=false --format=csv "$query" 2>&1 | tail -n 1)

    # Check if result is numeric
    if [[ "$result" =~ ^[0-9]+\.?[0-9]*$ ]]; then
        echo "$result"
        return 0
    else
        log_error "Query failed or returned non-numeric value: $result"
        return 1
    fi
}

# Parse YAML config file (simple key-value parser)
parse_yaml_value() {
    local file="$1"
    local key="$2"

    if [[ ! -f "$file" ]]; then
        log_error "Config file not found: $file"
        return 1
    fi

    # Simple YAML parser - looks for "key: value" pattern
    grep "^[[:space:]]*${key}:" "$file" | head -n 1 | sed 's/.*:[[:space:]]*//' | sed 's/[[:space:]]*#.*//'
}

# Check if a number meets a threshold
check_threshold() {
    local value="$1"
    local threshold="$2"
    local comparison="${3:-ge}"  # ge (>=), le (<=), gt (>), lt (<), eq (==)

    # Use bc for floating point comparison
    case "$comparison" in
        ge|">=")
            result=$(echo "$value >= $threshold" | bc -l)
            ;;
        le|"<=")
            result=$(echo "$value <= $threshold" | bc -l)
            ;;
        gt|">")
            result=$(echo "$value > $threshold" | bc -l)
            ;;
        lt|"<")
            result=$(echo "$value < $threshold" | bc -l)
            ;;
        eq|"==")
            result=$(echo "$value == $threshold" | bc -l)
            ;;
        *)
            log_error "Unknown comparison: $comparison"
            return 2
            ;;
    esac

    if [[ "$result" == "1" ]]; then
        return 0  # Threshold met
    else
        return 1  # Threshold not met
    fi
}

# Format number with commas
format_number() {
    printf "%'d" "$1" 2>/dev/null || echo "$1"
}

# Format percentage
format_pct() {
    printf "%.1f%%" "$1"
}

# Duration formatting (seconds to human readable)
format_duration() {
    local seconds=$1
    local hours=$((seconds / 3600))
    local minutes=$(((seconds % 3600) / 60))
    local secs=$((seconds % 60))

    if [[ $hours -gt 0 ]]; then
        printf "%dh %dm %ds" $hours $minutes $secs
    elif [[ $minutes -gt 0 ]]; then
        printf "%dm %ds" $minutes $secs
    else
        printf "%ds" $secs
    fi
}

# Export functions for use in other scripts
export -f log_info log_success log_warning log_error log_section
export -f bq_query bq_query_value parse_yaml_value check_threshold
export -f format_number format_pct format_duration
