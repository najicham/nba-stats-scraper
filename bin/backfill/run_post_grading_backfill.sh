#!/bin/bash
# Post-Phase 5B Backfill Script
#
# Runs after Phase 5B (prediction_accuracy) grading completes.
# Executes:
#   1. Phase 5C: system_daily_performance aggregation
#   2. Phase 6: Export results to GCS
#
# Usage:
#   ./bin/backfill/run_post_grading_backfill.sh
#   ./bin/backfill/run_post_grading_backfill.sh --phase5c-only
#   ./bin/backfill/run_post_grading_backfill.sh --phase6-only
#
# Prerequisites:
#   - Phase 5B grading must be complete
#   - Virtual environment must exist at .venv/

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

# Parse arguments
RUN_PHASE5C=true
RUN_PHASE6=true
while [[ $# -gt 0 ]]; do
    case $1 in
        --phase5c-only)
            RUN_PHASE6=false
            shift
            ;;
        --phase6-only)
            RUN_PHASE5C=false
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  Post-Grading Backfill (Phase 5C + Phase 6)${NC}"
echo -e "${BLUE}================================================${NC}"

# Check prerequisites
if [ ! -d ".venv" ]; then
    echo -e "${RED}Error: .venv not found. Run from project root.${NC}"
    exit 1
fi

# Check Phase 5B status
echo -e "\n${YELLOW}Checking Phase 5B status...${NC}"
GRADED_DATES=$(bq query --use_legacy_sql=false --format=csv --quiet \
    "SELECT COUNT(DISTINCT game_date) FROM nba_predictions.prediction_accuracy" | tail -1)
echo -e "  Graded dates in prediction_accuracy: ${GREEN}$GRADED_DATES${NC}"

if [ "$GRADED_DATES" -lt 400 ]; then
    echo -e "${RED}Warning: Only $GRADED_DATES dates graded. Phase 5B may not be complete.${NC}"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# ================================================
# Phase 5C: System Daily Performance Aggregation
# ================================================
if [ "$RUN_PHASE5C" = true ]; then
    echo -e "\n${BLUE}================================================${NC}"
    echo -e "${BLUE}  Phase 5C: System Daily Performance${NC}"
    echo -e "${BLUE}================================================${NC}"

    LOG_FILE="/tmp/phase5c_system_daily_perf.log"
    echo -e "Log file: $LOG_FILE"

    PYTHONPATH=. .venv/bin/python -c "
import logging
from datetime import date
from data_processors.grading.system_daily_performance.system_daily_performance_processor import SystemDailyPerformanceProcessor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

processor = SystemDailyPerformanceProcessor()

# Get date range from prediction_accuracy
from google.cloud import bigquery
client = bigquery.Client(project='nba-props-platform')

query = '''
SELECT MIN(game_date) as min_date, MAX(game_date) as max_date
FROM nba_predictions.prediction_accuracy
'''
result = list(client.query(query).result())[0]
start_date = result.min_date
end_date = result.max_date

logger.info(f'Processing system daily performance from {start_date} to {end_date}')

result = processor.process_date_range(start_date, end_date)
logger.info(f'Phase 5C complete: {result}')
" 2>&1 | tee "$LOG_FILE"

    echo -e "\n${GREEN}Phase 5C complete!${NC}"

    # Verify
    PERF_DATES=$(bq query --use_legacy_sql=false --format=csv --quiet \
        "SELECT COUNT(DISTINCT game_date) FROM nba_predictions.system_daily_performance" | tail -1)
    echo -e "  system_daily_performance dates: ${GREEN}$PERF_DATES${NC}"
fi

# ================================================
# Phase 6: Export to GCS
# ================================================
if [ "$RUN_PHASE6" = true ]; then
    echo -e "\n${BLUE}================================================${NC}"
    echo -e "${BLUE}  Phase 6: Export Results to GCS${NC}"
    echo -e "${BLUE}================================================${NC}"

    LOG_FILE="/tmp/phase6_exports.log"
    echo -e "Log file: $LOG_FILE"

    # Run backfill for results and performance
    PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py \
        --backfill-all \
        --only results,performance,best-bets \
        2>&1 | tee "$LOG_FILE"

    echo -e "\n${GREEN}Phase 6 complete!${NC}"

    # Verify
    EXPORT_COUNT=$(gsutil ls gs://nba-props-platform-api/v1/results/*.json 2>/dev/null | wc -l)
    echo -e "  Results exports in GCS: ${GREEN}$EXPORT_COUNT${NC}"
fi

# ================================================
# Final Summary
# ================================================
echo -e "\n${BLUE}================================================${NC}"
echo -e "${BLUE}  Final Summary${NC}"
echo -e "${BLUE}================================================${NC}"

echo -e "\n${YELLOW}BigQuery Tables:${NC}"
bq query --use_legacy_sql=false --format=pretty "
SELECT
    'prediction_accuracy' as table_name,
    COUNT(DISTINCT game_date) as dates,
    COUNT(*) as rows
FROM nba_predictions.prediction_accuracy
UNION ALL
SELECT
    'system_daily_performance',
    COUNT(DISTINCT game_date),
    COUNT(*)
FROM nba_predictions.system_daily_performance
"

echo -e "\n${YELLOW}GCS Exports:${NC}"
echo "  Results: $(gsutil ls gs://nba-props-platform-api/v1/results/*.json 2>/dev/null | wc -l) files"
echo "  Performance: $(gsutil ls gs://nba-props-platform-api/v1/systems/*.json 2>/dev/null | wc -l) files"

echo -e "\n${GREEN}================================================${NC}"
echo -e "${GREEN}  Post-Grading Backfill Complete!${NC}"
echo -e "${GREEN}================================================${NC}"
