#!/bin/bash
# Run backfill jobs locally
# Usage: ./bin/run_backfill.sh <phase/job_name> [args...]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to list all available backfill jobs
list_jobs() {
    echo -e "${BLUE}Available backfill jobs:${NC}\n"
    
    for phase in scrapers raw analytics precompute prediction publishing reference; do
        phase_dir="backfill_jobs/$phase"
        if [ -d "$phase_dir" ]; then
            jobs=$(find "$phase_dir" -maxdepth 1 -type d ! -path "$phase_dir" -exec basename {} \; | sort)
            if [ -n "$jobs" ]; then
                echo -e "${GREEN}$phase/${NC}"
                echo "$jobs" | sed 's/^/  /'
                echo ""
            fi
        fi
    done
}

# Show usage or list jobs
if [ -z "$1" ] || [ "$1" == "--list" ] || [ "$1" == "-l" ]; then
    if [ "$1" == "--list" ] || [ "$1" == "-l" ]; then
        list_jobs
        exit 0
    fi
    
    echo -e "${YELLOW}Usage:${NC} ./bin/run_backfill.sh <phase/job_name> [args...]"
    echo ""
    echo -e "${YELLOW}Examples:${NC}"
    echo "  ./bin/run_backfill.sh raw/bdl_injuries --help"
    echo "  ./bin/run_backfill.sh raw/bdl_injuries --dry-run --limit 5"
    echo "  ./bin/run_backfill.sh analytics/player_game_summary --dry-run"
    echo "  ./bin/run_backfill.sh raw/bettingpros_player_props --dates=2024-11-12,2024-11-15 --dry-run"
    echo ""
    echo -e "${YELLOW}Options:${NC}"
    echo "  --list, -l    List all available backfill jobs"
    echo ""
    list_jobs
    exit 1
fi

JOB_PATH=$1
shift

# Validate job path format
if [[ ! "$JOB_PATH" =~ ^[a-z_]+/[a-z_]+$ ]]; then
    echo -e "${RED}Error:${NC} Invalid job path format: $JOB_PATH"
    echo "Expected format: phase/job_name (e.g., raw/bdl_injuries)"
    exit 1
fi

# Split the path into phase and job name
PHASE=$(echo "$JOB_PATH" | cut -d'/' -f1)
JOB_NAME=$(echo "$JOB_PATH" | cut -d'/' -f2)

# Determine suffix based on phase
case "$PHASE" in
    scrapers)   SUFFIX="scraper" ;;
    raw)        SUFFIX="raw" ;;
    analytics)  SUFFIX="analytics" ;;
    precompute) SUFFIX="precompute" ;;
    prediction) SUFFIX="prediction" ;;
    publishing) SUFFIX="publishing" ;;
    reference)  SUFFIX="reference" ;;
    *)          
        echo -e "${RED}Error:${NC} Unknown phase: $PHASE"
        echo "Valid phases: scrapers, raw, analytics, precompute, prediction, publishing, reference"
        exit 1 
        ;;
esac

# Build the full module path and file path
MODULE="backfill_jobs.${PHASE}.${JOB_NAME}.${JOB_NAME}_${SUFFIX}_backfill"
FILE_PATH="backfill_jobs/${PHASE}/${JOB_NAME}/${JOB_NAME}_${SUFFIX}_backfill.py"

# Check if the backfill file exists
if [ ! -f "$FILE_PATH" ]; then
    echo -e "${RED}Error:${NC} Backfill job not found: $FILE_PATH"
    echo ""
    echo "Available jobs in $PHASE:"
    if [ -d "backfill_jobs/$PHASE" ]; then
        find "backfill_jobs/$PHASE" -maxdepth 1 -type d ! -path "backfill_jobs/$PHASE" -exec basename {} \; | sort | sed 's/^/  /'
    else
        echo "  (no jobs found)"
    fi
    exit 1
fi

# Show what we're running
echo -e "${GREEN}Running backfill job:${NC}"
echo -e "  Phase:  ${BLUE}$PHASE${NC}"
echo -e "  Job:    ${BLUE}$JOB_NAME${NC}"
echo -e "  Module: ${BLUE}$MODULE${NC}"
if [ $# -gt 0 ]; then
    echo -e "  Args:   ${BLUE}$@${NC}"
fi
echo ""

# Run the module
python -m "$MODULE" "$@"