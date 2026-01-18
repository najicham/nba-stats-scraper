#!/bin/bash
# NBA Phase 3 (Analytics) Backfill Runner
# Runs all Phase 3 processors for a given year or date range
# Created: 2026-01-17
# Usage: ./bin/backfill/run_year_phase3.sh --year 2022
#        ./bin/backfill/run_year_phase3.sh --start-date 2022-01-01 --end-date 2022-12-31

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

YEAR=""
START_DATE=""
END_DATE=""
DRY_RUN=false
PARALLEL=true

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --year)
      YEAR="$2"
      START_DATE="${YEAR}-01-01"
      END_DATE="${YEAR}-12-31"
      shift 2
      ;;
    --start-date)
      START_DATE="$2"
      shift 2
      ;;
    --end-date)
      END_DATE="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --sequential)
      PARALLEL=false
      shift
      ;;
    --help)
      echo "Usage: $0 --year YYYY | --start-date YYYY-MM-DD --end-date YYYY-MM-DD"
      echo ""
      echo "Options:"
      echo "  --year          Process entire year (e.g., 2022)"
      echo "  --start-date    Start date (YYYY-MM-DD)"
      echo "  --end-date      End date (YYYY-MM-DD)"
      echo "  --dry-run       Preview without executing"
      echo "  --sequential    Run processors sequentially (default: parallel)"
      echo "  --help          Show this help message"
      echo ""
      echo "Phase 3 Processors (5):"
      echo "  1. player_game_summary"
      echo "  2. team_offense_game_summary"
      echo "  3. team_defense_game_summary"
      echo "  4. upcoming_player_game_context"
      echo "  5. upcoming_team_game_context"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# Validate inputs
if [ -z "$START_DATE" ] || [ -z "$END_DATE" ]; then
  echo -e "${RED}Error: Must specify either --year or both --start-date and --end-date${NC}"
  exit 1
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}NBA Phase 3 Backfill${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "Date Range: ${GREEN}$START_DATE${NC} to ${GREEN}$END_DATE${NC}"
echo -e "Mode: ${YELLOW}$([ "$DRY_RUN" = true ] && echo "DRY RUN" || echo "LIVE")${NC}"
echo -e "Execution: ${YELLOW}$([ "$PARALLEL" = true ] && echo "PARALLEL" || echo "SEQUENTIAL")${NC}"
echo ""

# Define Phase 3 processors
PROCESSORS=(
  "analytics/player_game_summary"
  "analytics/team_offense_game_summary"
  "analytics/team_defense_game_summary"
  "analytics/upcoming_player_game_context"
  "analytics/upcoming_team_game_context"
)

# Build command arguments
ARGS="--start-date $START_DATE --end-date $END_DATE"
if [ "$DRY_RUN" = true ]; then
  ARGS="$ARGS --dry-run --limit 5"
fi

# Function to run a processor
run_processor() {
  local processor=$1
  local processor_name=$(basename $processor)

  echo -e "${BLUE}Starting: ${processor_name}${NC}"

  if ./bin/run_backfill.sh $processor $ARGS; then
    echo -e "${GREEN}✓ Completed: ${processor_name}${NC}"
    return 0
  else
    echo -e "${RED}✗ Failed: ${processor_name}${NC}"
    return 1
  fi
}

# Run processors
if [ "$PARALLEL" = true ]; then
  echo -e "${YELLOW}Running processors in parallel (5 concurrent)...${NC}"
  echo ""

  # Run all processors in parallel
  pids=()
  for processor in "${PROCESSORS[@]}"; do
    run_processor "$processor" &
    pids+=($!)
  done

  # Wait for all to complete
  failed=0
  for pid in "${pids[@]}"; do
    if ! wait $pid; then
      failed=$((failed + 1))
    fi
  done

  echo ""
  if [ $failed -eq 0 ]; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}✓ All Phase 3 processors completed!${NC}"
    echo -e "${GREEN}========================================${NC}"
  else
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}✗ $failed processor(s) failed${NC}"
    echo -e "${RED}========================================${NC}"
    exit 1
  fi
else
  echo -e "${YELLOW}Running processors sequentially...${NC}"
  echo ""

  for processor in "${PROCESSORS[@]}"; do
    if ! run_processor "$processor"; then
      echo -e "${RED}Stopping due to failure${NC}"
      exit 1
    fi
    echo ""
  done

  echo -e "${GREEN}========================================${NC}"
  echo -e "${GREEN}✓ All Phase 3 processors completed!${NC}"
  echo -e "${GREEN}========================================${NC}"
fi

echo ""
echo "Next steps:"
echo "  1. Run monitor: ./bin/backfill/monitor_backfill_progress.sh --update"
echo "  2. Run Phase 4: ./bin/backfill/run_year_phase4.sh --year $YEAR"
