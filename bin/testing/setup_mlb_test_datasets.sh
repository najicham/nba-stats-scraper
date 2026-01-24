#!/bin/bash
# bin/testing/setup_mlb_test_datasets.sh
#
# Create test BigQuery datasets for MLB pipeline replay testing.
# These datasets mirror production but with a prefix (default: test_)
# Tables auto-expire after 7 days to prevent stale data accumulation.
#
# Usage:
#   ./bin/testing/setup_mlb_test_datasets.sh              # Use default prefix (test_)
#   ./bin/testing/setup_mlb_test_datasets.sh dev_         # Use custom prefix
#   ./bin/testing/setup_mlb_test_datasets.sh test_ --dry-run  # Preview only
#
# Created: 2026-01-07

set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"
PREFIX="${1:-test_}"
DRY_RUN=false

# Check for --dry-run flag
for arg in "$@"; do
    if [[ "$arg" == "--dry-run" ]]; then
        DRY_RUN=true
    fi
done

# MLB datasets to create for testing
DATASETS=(
    "mlb_raw"
    "mlb_analytics"
    "mlb_precompute"
    "mlb_predictions"
    "mlb_orchestration"
)

# Table expiration in seconds (7 days)
TABLE_EXPIRATION=604800

echo "=============================================="
echo "  MLB Test Dataset Setup"
echo "=============================================="
echo "Project:     $PROJECT_ID"
echo "Prefix:      $PREFIX"
echo "Expiration:  $TABLE_EXPIRATION seconds (7 days)"
echo "Dry Run:     $DRY_RUN"
echo "=============================================="
echo ""

for dataset in "${DATASETS[@]}"; do
    test_dataset="${PREFIX}${dataset}"

    echo -n "Creating $test_dataset... "

    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[DRY RUN] Would create ${PROJECT_ID}:${test_dataset}"
    else
        # Check if exists
        if bq show --dataset "${PROJECT_ID}:${test_dataset}" &>/dev/null; then
            echo "already exists"
        else
            bq mk --dataset \
                --default_table_expiration "$TABLE_EXPIRATION" \
                --description "MLB test dataset for pipeline replay - auto-expires in 7 days" \
                "${PROJECT_ID}:${test_dataset}" 2>/dev/null
            echo "created ✓"
        fi
    fi
done

echo ""
echo "=============================================="
echo "  Setup Complete"
echo "=============================================="
echo ""
echo "Test datasets created:"
for dataset in "${DATASETS[@]}"; do
    echo "  - ${PREFIX}${dataset}"
done
echo ""
echo "To run a pipeline replay test:"
echo "  # Trigger Phase 3 analytics"
echo "  curl -X POST https://mlb-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"game_date\": \"2025-06-15\", \"dataset_prefix\": \"${PREFIX}\"}'"
echo ""
echo "To clean up test datasets:"
echo "  for d in ${DATASETS[*]/#/${PREFIX}}; do"
echo "    bq rm -r -f ${PROJECT_ID}:\$d"
echo "  done"
