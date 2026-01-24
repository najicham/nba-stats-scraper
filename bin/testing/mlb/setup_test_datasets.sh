#!/bin/bash
# bin/testing/mlb/setup_test_datasets.sh
#
# Create test BigQuery datasets for MLB pipeline replay testing.
# These datasets mirror production but with a prefix (default: test_)
# Tables auto-expire after 7 days to prevent stale data accumulation.
#
# Usage:
#   ./bin/testing/mlb/setup_test_datasets.sh              # Use default prefix (test_)
#   ./bin/testing/mlb/setup_test_datasets.sh dev_         # Use custom prefix
#   ./bin/testing/mlb/setup_test_datasets.sh test_ --dry-run  # Preview only
#
# Created: 2026-01-15
# Part of MLB Pipeline Replay System

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

# MLB production datasets to mirror
DATASETS=(
    "mlb_raw"
    "mlb_analytics"
    "mlb_predictions"
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
            echo "created"
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
echo "To run a pipeline replay:"
echo "  PYTHONPATH=. python bin/testing/mlb/replay_mlb_pipeline.py --date 2025-07-15"
echo ""
echo "To clean up test datasets:"
echo "  for d in ${PREFIX}mlb_raw ${PREFIX}mlb_analytics ${PREFIX}mlb_predictions; do"
echo "    bq rm -r -f ${PROJECT_ID}:\$d"
echo "  done"
