#!/bin/bash
#
# Phase 4 Backfill Orchestrator
#
# Runs Phase 4 backfill with proper dependency ordering:
# - Processors #1 and #2 run in PARALLEL (no Phase 4 dependencies)
# - Processors #3, #4, #5 run SEQUENTIALLY (each depends on previous)
#
# v2.0: Added timeout protection, signal handling, and pre-flight checks
#
# Usage:
#   # Full 4-year backfill
#   ./bin/backfill/run_phase4_backfill.sh --start-date 2021-10-19 --end-date 2025-06-22
#
#   # Dry run to check readiness
#   ./bin/backfill/run_phase4_backfill.sh --start-date 2024-01-01 --end-date 2024-03-31 --dry-run
#
#   # Start from specific processor (for resuming)
#   ./bin/backfill/run_phase4_backfill.sh --start-date 2024-01-01 --end-date 2024-03-31 --start-from 3
#

set -euo pipefail

# v2.0: Timeout configuration (in seconds)
# Per-processor timeout: 6 hours (allows for ~400 dates at 50s each + buffer)
PROCESSOR_TIMEOUT=21600
# Pre-flight check timeout: 60 seconds
PREFLIGHT_TIMEOUT=60

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
export PYTHONPATH="$PROJECT_ROOT"

# Default values
DRY_RUN=""
START_FROM=1
NO_RESUME=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# v2.0: Track background PIDs for cleanup
BACKGROUND_PIDS=()

# v2.0: Signal handler for cleanup
cleanup() {
    echo -e "\n${RED}Received interrupt signal. Cleaning up...${NC}"
    for pid in "${BACKGROUND_PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            echo -e "${YELLOW}Killing process $pid...${NC}"
            kill -TERM "$pid" 2>/dev/null || true
        fi
    done
    echo -e "${RED}Backfill interrupted. Use --start-from to resume.${NC}"
    exit 130
}

# Register signal handlers
trap cleanup SIGINT SIGTERM

# v2.0: Pre-flight check function
preflight_check() {
    echo -e "\n${CYAN}=== PRE-FLIGHT CHECKS ===${NC}"

    # Check BigQuery connectivity
    echo -e "${YELLOW}Checking BigQuery connectivity...${NC}"
    if timeout $PREFLIGHT_TIMEOUT bq query --use_legacy_sql=false 'SELECT 1' > /dev/null 2>&1; then
        echo -e "${GREEN}✓ BigQuery connection OK${NC}"
    else
        echo -e "${RED}✗ BigQuery connection failed${NC}"
        echo -e "${RED}Please check your credentials and network connectivity${NC}"
        exit 1
    fi

    # Check Python environment
    echo -e "${YELLOW}Checking Python environment...${NC}"
    if python3 -c "import google.cloud.bigquery" 2>/dev/null; then
        echo -e "${GREEN}✓ Python BigQuery library OK${NC}"
    else
        echo -e "${RED}✗ Python BigQuery library not found${NC}"
        exit 1
    fi

    echo -e "${GREEN}=== PRE-FLIGHT CHECKS PASSED ===${NC}\n"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --start-date)
            START_DATE="$2"
            shift 2
            ;;
        --end-date)
            END_DATE="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN="--dry-run"
            shift
            ;;
        --start-from)
            START_FROM="$2"
            shift 2
            ;;
        --no-resume)
            NO_RESUME="--no-resume"
            shift
            ;;
        -h|--help)
            echo "Phase 4 Backfill Orchestrator"
            echo ""
            echo "Usage: $0 --start-date YYYY-MM-DD --end-date YYYY-MM-DD [options]"
            echo ""
            echo "Options:"
            echo "  --start-date    Start date for backfill (required)"
            echo "  --end-date      End date for backfill (required)"
            echo "  --dry-run       Check data availability without processing"
            echo "  --start-from N  Start from processor N (1-5, for resuming)"
            echo "  --no-resume     Ignore checkpoints, start fresh"
            echo "  -h, --help      Show this help"
            echo ""
            echo "Execution Order:"
            echo "  1. team_defense_zone_analysis  } Run in PARALLEL"
            echo "  2. player_shot_zone_analysis   }"
            echo "  3. player_composite_factors    (depends on #1, #2)"
            echo "  4. player_daily_cache          (depends on #1, #2, #3)"
            echo "  5. ml_feature_store            (depends on ALL)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Validate required arguments
if [[ -z "$START_DATE" ]] || [[ -z "$END_DATE" ]]; then
    echo -e "${RED}Error: --start-date and --end-date are required${NC}"
    exit 1
fi

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}Phase 4 Backfill Orchestrator v2.0${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""
echo -e "Date range: ${GREEN}$START_DATE${NC} to ${GREEN}$END_DATE${NC}"
echo -e "Dry run: ${DRY_RUN:-"No"}"
echo -e "Start from: Processor #$START_FROM"
echo -e "No resume: ${NO_RESUME:-"No (will use checkpoints)"}"
echo -e "Processor timeout: ${CYAN}${PROCESSOR_TIMEOUT}s ($(($PROCESSOR_TIMEOUT / 3600))h)${NC}"
echo ""

# v2.0: Run pre-flight checks before starting
preflight_check

# Backfill job paths
BACKFILL_DIR="$PROJECT_ROOT/backfill_jobs/precompute"
JOB_1="$BACKFILL_DIR/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py"
JOB_2="$BACKFILL_DIR/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py"
JOB_3="$BACKFILL_DIR/player_composite_factors/player_composite_factors_precompute_backfill.py"
JOB_4="$BACKFILL_DIR/player_daily_cache/player_daily_cache_precompute_backfill.py"
JOB_5="$BACKFILL_DIR/ml_feature_store/ml_feature_store_precompute_backfill.py"

COMMON_ARGS="--start-date $START_DATE --end-date $END_DATE $DRY_RUN $NO_RESUME"

# Function to run a job with timeout protection
run_job() {
    local job_num=$1
    local job_path=$2
    local job_name=$3

    echo -e "\n${YELLOW}----------------------------------------${NC}"
    echo -e "${YELLOW}Running #$job_num: $job_name${NC}"
    echo -e "${YELLOW}Timeout: ${PROCESSOR_TIMEOUT}s ($(($PROCESSOR_TIMEOUT / 3600))h)${NC}"
    echo -e "${YELLOW}----------------------------------------${NC}"

    # v2.0: Use timeout command for protection against hangs
    if timeout $PROCESSOR_TIMEOUT python3 "$job_path" $COMMON_ARGS; then
        echo -e "${GREEN}✓ #$job_num $job_name completed${NC}"
    else
        local exit_code=$?
        if [[ $exit_code -eq 124 ]]; then
            echo -e "${RED}✗ #$job_num $job_name TIMED OUT after ${PROCESSOR_TIMEOUT}s${NC}"
            echo -e "${RED}Consider increasing PROCESSOR_TIMEOUT or checking for hung queries${NC}"
        else
            echo -e "${RED}✗ #$job_num $job_name failed with exit code $exit_code${NC}"
        fi
        exit 1
    fi
}

# Run Phase 4 processors in order

if [[ $START_FROM -le 2 ]]; then
    echo -e "\n${BLUE}=== PARALLEL PHASE: Running #1 and #2 concurrently ===${NC}"
    echo -e "${CYAN}Timeout per job: ${PROCESSOR_TIMEOUT}s ($(($PROCESSOR_TIMEOUT / 3600))h)${NC}"

    if [[ $START_FROM -le 1 ]]; then
        # v2.0: Run with timeout protection
        echo -e "${YELLOW}Starting team_defense_zone_analysis (background with timeout)...${NC}"
        timeout $PROCESSOR_TIMEOUT python3 "$JOB_1" $COMMON_ARGS &
        PID_1=$!
        BACKGROUND_PIDS+=($PID_1)
    fi

    if [[ $START_FROM -le 2 ]]; then
        # v2.0: Run with timeout protection
        echo -e "${YELLOW}Starting player_shot_zone_analysis (background with timeout)...${NC}"
        timeout $PROCESSOR_TIMEOUT python3 "$JOB_2" $COMMON_ARGS &
        PID_2=$!
        BACKGROUND_PIDS+=($PID_2)
    fi

    # Wait for parallel jobs to complete
    FAILED=0

    if [[ $START_FROM -le 1 ]]; then
        wait $PID_1
        EXIT_1=$?
        if [[ $EXIT_1 -eq 0 ]]; then
            echo -e "${GREEN}✓ #1 team_defense_zone_analysis completed${NC}"
        elif [[ $EXIT_1 -eq 124 ]]; then
            echo -e "${RED}✗ #1 team_defense_zone_analysis TIMED OUT${NC}"
            FAILED=1
        else
            echo -e "${RED}✗ #1 team_defense_zone_analysis failed (exit: $EXIT_1)${NC}"
            FAILED=1
        fi
    fi

    if [[ $START_FROM -le 2 ]]; then
        wait $PID_2
        EXIT_2=$?
        if [[ $EXIT_2 -eq 0 ]]; then
            echo -e "${GREEN}✓ #2 player_shot_zone_analysis completed${NC}"
        elif [[ $EXIT_2 -eq 124 ]]; then
            echo -e "${RED}✗ #2 player_shot_zone_analysis TIMED OUT${NC}"
            FAILED=1
        else
            echo -e "${RED}✗ #2 player_shot_zone_analysis failed (exit: $EXIT_2)${NC}"
            FAILED=1
        fi
    fi

    # Clear tracked PIDs after parallel phase
    BACKGROUND_PIDS=()

    if [[ $FAILED -eq 1 ]]; then
        echo -e "${RED}Parallel phase failed. Stopping.${NC}"
        exit 1
    fi

    echo -e "${GREEN}=== PARALLEL PHASE COMPLETE ===${NC}"
fi

echo -e "\n${BLUE}=== SEQUENTIAL PHASE: Running #3, #4, #5 in order ===${NC}"

if [[ $START_FROM -le 3 ]]; then
    run_job 3 "$JOB_3" "player_composite_factors"
fi

if [[ $START_FROM -le 4 ]]; then
    run_job 4 "$JOB_4" "player_daily_cache"
fi

if [[ $START_FROM -le 5 ]]; then
    run_job 5 "$JOB_5" "ml_feature_store"
fi

echo -e "\n${GREEN}======================================${NC}"
echo -e "${GREEN}Phase 4 Backfill Complete!${NC}"
echo -e "${GREEN}======================================${NC}"
