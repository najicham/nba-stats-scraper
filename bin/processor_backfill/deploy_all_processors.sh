#!/bin/bash
# Deploy all processor backfill jobs

set -e

SCRIPT_DIR="$(dirname "$0")"
PROCESSOR_BACKFILL_DIR="${SCRIPT_DIR}/../../processor_backfill"
DEPLOY_SCRIPT="${PROCESSOR_BACKFILL_DIR}/deploy_processor_job.sh"

echo "=========================================="
echo "Deploying All Processor Backfill Jobs"
echo "=========================================="

# List of processors to deploy
PROCESSORS=(
    "br_roster_processor"
    # Add more processors here as you create them:
    # "bdl_boxscore_processor"
    # "nbac_schedule_processor"
    # "oddsa_props_processor"
)

# Deploy each processor
for processor in "${PROCESSORS[@]}"; do
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Deploying: $processor"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    if [ -d "${PROCESSOR_BACKFILL_DIR}/${processor}" ]; then
        ${DEPLOY_SCRIPT} ${processor}
        
        if [ $? -eq 0 ]; then
            echo "✓ ${processor} deployed successfully"
        else
            echo "✗ ${processor} deployment failed"
            exit 1
        fi
    else
        echo "⚠ Skipping ${processor} - directory not found"
    fi
done

echo ""
echo "=========================================="
echo "✓ All processors deployed successfully!"
echo "=========================================="