#!/bin/bash
#
# Phase 4 Backfill Orchestrator
#
# Runs Phase 4 backfill with proper dependency ordering:
# - Processors #1 and #2 run in PARALLEL (no Phase 4 dependencies)
# - Processors #3, #4, #5 run SEQUENTIALLY (each depends on previous)
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

set -e

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
NC='\033[0m' # No Color

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
echo -e "${BLUE}Phase 4 Backfill Orchestrator${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""
echo -e "Date range: ${GREEN}$START_DATE${NC} to ${GREEN}$END_DATE${NC}"
echo -e "Dry run: ${DRY_RUN:-"No"}"
echo -e "Start from: Processor #$START_FROM"
echo -e "No resume: ${NO_RESUME:-"No (will use checkpoints)"}"
echo ""

# Backfill job paths
BACKFILL_DIR="$PROJECT_ROOT/backfill_jobs/precompute"
JOB_1="$BACKFILL_DIR/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py"
JOB_2="$BACKFILL_DIR/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py"
JOB_3="$BACKFILL_DIR/player_composite_factors/player_composite_factors_precompute_backfill.py"
JOB_4="$BACKFILL_DIR/player_daily_cache/player_daily_cache_precompute_backfill.py"
JOB_5="$BACKFILL_DIR/ml_feature_store/ml_feature_store_precompute_backfill.py"

COMMON_ARGS="--start-date $START_DATE --end-date $END_DATE $DRY_RUN $NO_RESUME"

# Function to run a job
run_job() {
    local job_num=$1
    local job_path=$2
    local job_name=$3

    echo -e "\n${YELLOW}----------------------------------------${NC}"
    echo -e "${YELLOW}Running #$job_num: $job_name${NC}"
    echo -e "${YELLOW}----------------------------------------${NC}"

    python3 "$job_path" $COMMON_ARGS

    if [[ $? -eq 0 ]]; then
        echo -e "${GREEN}✓ #$job_num $job_name completed${NC}"
    else
        echo -e "${RED}✗ #$job_num $job_name failed${NC}"
        exit 1
    fi
}

# Run Phase 4 processors in order

if [[ $START_FROM -le 2 ]]; then
    echo -e "\n${BLUE}=== PARALLEL PHASE: Running #1 and #2 concurrently ===${NC}"

    if [[ $START_FROM -le 1 ]]; then
        # Run #1 and #2 in parallel
        echo -e "${YELLOW}Starting team_defense_zone_analysis (background)...${NC}"
        python3 "$JOB_1" $COMMON_ARGS &
        PID_1=$!
    fi

    if [[ $START_FROM -le 2 ]]; then
        echo -e "${YELLOW}Starting player_shot_zone_analysis (background)...${NC}"
        python3 "$JOB_2" $COMMON_ARGS &
        PID_2=$!
    fi

    # Wait for parallel jobs to complete
    FAILED=0

    if [[ $START_FROM -le 1 ]]; then
        wait $PID_1
        if [[ $? -eq 0 ]]; then
            echo -e "${GREEN}✓ #1 team_defense_zone_analysis completed${NC}"
        else
            echo -e "${RED}✗ #1 team_defense_zone_analysis failed${NC}"
            FAILED=1
        fi
    fi

    if [[ $START_FROM -le 2 ]]; then
        wait $PID_2
        if [[ $? -eq 0 ]]; then
            echo -e "${GREEN}✓ #2 player_shot_zone_analysis completed${NC}"
        else
            echo -e "${RED}✗ #2 player_shot_zone_analysis failed${NC}"
            FAILED=1
        fi
    fi

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
