#!/bin/bash
# NBA Phase 4 (Precompute) Backfill Runner
# Runs all Phase 4 processors for a given year or date range
# IMPORTANT: Phase 4 has dependencies and must run in specific order
# Created: 2026-01-17
# Usage: ./bin/backfill/run_year_phase4.sh --year 2022
#        ./bin/backfill/run_year_phase4.sh --start-date 2022-01-01 --end-date 2022-12-31

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
SKIP_VALIDATION=false

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
    --skip-validation)
      SKIP_VALIDATION=true
      shift
      ;;
    --help)
      echo "Usage: $0 --year YYYY | --start-date YYYY-MM-DD --end-date YYYY-MM-DD"
      echo ""
      echo "Options:"
      echo "  --year             Process entire year (e.g., 2022)"
      echo "  --start-date       Start date (YYYY-MM-DD)"
      echo "  --end-date         End date (YYYY-MM-DD)"
      echo "  --dry-run          Preview without executing"
      echo "  --skip-validation  Skip Phase 3 validation check"
      echo "  --help             Show this help message"
      echo ""
      echo "Phase 4 Dependency Order:"
      echo "  Step 1: TDZA + PSZA (parallel - no dependencies)"
      echo "  Step 2: PCF (depends on PSZA + TDZA)"
      echo "  Step 3: MLFS (depends on all above)"
      echo ""
      echo "Processors:"
      echo "  TDZA - team_defense_zone_analysis"
      echo "  PSZA - player_shot_zone_analysis"
      echo "  PCF  - player_composite_factors"
      echo "  MLFS - ml_feature_store"
      echo ""
      echo "Note: player_daily_cache is omitted as it's not date-specific"
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
echo -e "${BLUE}NBA Phase 4 Backfill${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "Date Range: ${GREEN}$START_DATE${NC} to ${GREEN}$END_DATE${NC}"
echo -e "Mode: ${YELLOW}$([ "$DRY_RUN" = true ] && echo "DRY RUN" || echo "LIVE")${NC}"
echo ""

# Build command arguments
ARGS="--start-date $START_DATE --end-date $END_DATE"
if [ "$DRY_RUN" = true ]; then
  ARGS="$ARGS --dry-run --limit 5"
fi

# Validate Phase 3 completion (unless skipped)
if [ "$SKIP_VALIDATION" = false ]; then
  echo -e "${YELLOW}Validating Phase 3 completion...${NC}"

  # Use existing validation script if available
  if [ -f "./bin/backfill/verify_phase3_for_phase4.py" ]; then
    if python3 ./bin/backfill/verify_phase3_for_phase4.py --start-date "$START_DATE" --end-date "$END_DATE"; then
      echo -e "${GREEN}✓ Phase 3 validation passed${NC}"
    else
      echo -e "${RED}✗ Phase 3 validation failed${NC}"
      echo -e "${YELLOW}Some dates are missing Phase 3 data.${NC}"
      echo -e "${YELLOW}Run Phase 3 first: ./bin/backfill/run_year_phase3.sh --year $YEAR${NC}"
      echo -e "${YELLOW}Or use --skip-validation to proceed anyway${NC}"
      exit 1
    fi
  else
    echo -e "${YELLOW}⚠ Validation script not found, skipping...${NC}"
  fi
  echo ""
fi

# Function to run a processor
run_processor() {
  local processor=$1
  local processor_name=$(basename $processor)

  echo -e "${BLUE}========================================${NC}"
  echo -e "${BLUE}Starting: ${processor_name}${NC}"
  echo -e "${BLUE}========================================${NC}"

  if ./bin/run_backfill.sh "$processor" $ARGS; then
    echo -e "${GREEN}✓ Completed: ${processor_name}${NC}"
    echo ""
    return 0
  else
    echo -e "${RED}✗ Failed: ${processor_name}${NC}"
    echo ""
    return 1
  fi
}

# Step 1: Run TDZA and PSZA in parallel (no dependencies)
echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}Step 1: TDZA + PSZA (parallel)${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""

run_processor "precompute/team_defense_zone_analysis" &
pid_tdza=$!

run_processor "precompute/player_shot_zone_analysis" &
pid_psza=$!

# Wait for both to complete
failed=0
if ! wait $pid_tdza; then
  echo -e "${RED}✗ TDZA failed${NC}"
  failed=1
fi
if ! wait $pid_psza; then
  echo -e "${RED}✗ PSZA failed${NC}"
  failed=1
fi

if [ $failed -ne 0 ]; then
  echo -e "${RED}Step 1 failed, aborting${NC}"
  exit 1
fi

echo -e "${GREEN}✓ Step 1 complete (TDZA + PSZA)${NC}"
echo ""

# Step 2: Run PCF (depends on PSZA + TDZA)
echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}Step 2: PCF (depends on PSZA + TDZA)${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""

if ! run_processor "precompute/player_composite_factors"; then
  echo -e "${RED}Step 2 failed, aborting${NC}"
  exit 1
fi

echo -e "${GREEN}✓ Step 2 complete (PCF)${NC}"
echo ""

# Step 3: Run MLFS (depends on all Phase 4)
echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}Step 3: MLFS (depends on all above)${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""

if ! run_processor "precompute/ml_feature_store"; then
  echo -e "${RED}Step 3 failed, aborting${NC}"
  exit 1
fi

echo -e "${GREEN}✓ Step 3 complete (MLFS)${NC}"
echo ""

# Success
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✓ All Phase 4 processors completed!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Next steps:"
echo "  1. Update progress: ./bin/backfill/monitor_backfill_progress.sh --update"
echo "  2. View results: ./bin/backfill/monitor_backfill_progress.sh --year $YEAR"
