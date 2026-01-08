#!/bin/bash
# Deploy all MLB Orchestrator Cloud Functions
#
# This script deploys all MLB phase transition orchestrators:
# - mlb_phase3_to_phase4: Tracks analytics completion, triggers precompute
# - mlb_phase4_to_phase5: Tracks precompute completion, triggers predictions
# - mlb_phase5_to_phase6: Tracks predictions completion, triggers grading
# - mlb_self_heal: Checks for missing predictions and auto-heals
#
# Usage: ./bin/orchestrators/mlb/deploy_all_mlb_orchestrators.sh
#
# Created: 2026-01-08

set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"
REGION="us-west2"
RUNTIME="python311"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
FUNCTIONS_DIR="$PROJECT_ROOT/orchestration/cloud_functions"

echo "========================================"
echo " Deploying MLB Orchestrators"
echo "========================================"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo ""

# Function to deploy a Cloud Function
deploy_function() {
    local FUNCTION_NAME=$1
    local ENTRY_POINT=$2
    local TRIGGER_TOPIC=$3
    local SOURCE_DIR=$4

    echo "Deploying $FUNCTION_NAME..."

    if [ -n "$TRIGGER_TOPIC" ]; then
        # Pub/Sub triggered function
        gcloud functions deploy "$FUNCTION_NAME" \
            --gen2 \
            --runtime="$RUNTIME" \
            --region="$REGION" \
            --source="$SOURCE_DIR" \
            --entry-point="$ENTRY_POINT" \
            --trigger-topic="$TRIGGER_TOPIC" \
            --memory=512Mi \
            --timeout=300s \
            --min-instances=0 \
            --max-instances=5 \
            --set-env-vars="GCP_PROJECT=$PROJECT_ID" \
            --project="$PROJECT_ID" \
            --quiet
    else
        # HTTP triggered function
        gcloud functions deploy "$FUNCTION_NAME" \
            --gen2 \
            --runtime="$RUNTIME" \
            --region="$REGION" \
            --source="$SOURCE_DIR" \
            --entry-point="$ENTRY_POINT" \
            --trigger-http \
            --allow-unauthenticated \
            --memory=512Mi \
            --timeout=300s \
            --min-instances=0 \
            --max-instances=1 \
            --set-env-vars="GCP_PROJECT=$PROJECT_ID" \
            --project="$PROJECT_ID" \
            --quiet
    fi

    echo "  ✓ $FUNCTION_NAME deployed"
}

# Deploy Phase 3 → Phase 4 Orchestrator
echo ""
echo "=== Phase 3 → Phase 4 Orchestrator ==="
deploy_function \
    "mlb-phase3-to-phase4" \
    "orchestrate_mlb_phase3_to_phase4" \
    "mlb-phase3-analytics-complete" \
    "$FUNCTIONS_DIR/mlb_phase3_to_phase4"

# Deploy Phase 4 → Phase 5 Orchestrator
echo ""
echo "=== Phase 4 → Phase 5 Orchestrator ==="
deploy_function \
    "mlb-phase4-to-phase5" \
    "orchestrate_mlb_phase4_to_phase5" \
    "mlb-phase4-precompute-complete" \
    "$FUNCTIONS_DIR/mlb_phase4_to_phase5"

# Deploy Phase 5 → Phase 6 Orchestrator
echo ""
echo "=== Phase 5 → Phase 6 Orchestrator ==="
deploy_function \
    "mlb-phase5-to-phase6" \
    "orchestrate_mlb_phase5_to_phase6" \
    "mlb-phase5-predictions-complete" \
    "$FUNCTIONS_DIR/mlb_phase5_to_phase6"

# Deploy Self-Heal Function
echo ""
echo "=== Self-Heal Function ==="
deploy_function \
    "mlb-self-heal" \
    "mlb_self_heal_check" \
    "" \
    "$FUNCTIONS_DIR/mlb_self_heal"

# Create scheduler for self-heal (paused)
echo ""
echo "=== Creating Self-Heal Scheduler (PAUSED) ==="
SELF_HEAL_URL=$(gcloud functions describe mlb-self-heal \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --gen2 \
    --format="value(serviceConfig.uri)")

if gcloud scheduler jobs describe mlb-self-heal-daily --location="$REGION" --project="$PROJECT_ID" &>/dev/null; then
    echo "Scheduler job exists, updating..."
    gcloud scheduler jobs update http mlb-self-heal-daily \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --schedule="45 12 * * *" \
        --time-zone="America/New_York" \
        --uri="$SELF_HEAL_URL" \
        --http-method=POST \
        --description="MLB Self-heal check - 15 min before exports" \
        --quiet
else
    echo "Creating scheduler job..."
    gcloud scheduler jobs create http mlb-self-heal-daily \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --schedule="45 12 * * *" \
        --time-zone="America/New_York" \
        --uri="$SELF_HEAL_URL" \
        --http-method=POST \
        --description="MLB Self-heal check - 15 min before exports" \
        --quiet
fi

# Pause scheduler (MLB off-season)
gcloud scheduler jobs pause mlb-self-heal-daily --location="$REGION" --project="$PROJECT_ID" --quiet
echo "  ✓ Scheduler created and paused"

echo ""
echo "========================================"
echo " Deployment Complete"
echo "========================================"
echo ""
echo "Deployed Functions:"
echo "  - mlb-phase3-to-phase4 (Pub/Sub: mlb-phase3-analytics-complete)"
echo "  - mlb-phase4-to-phase5 (Pub/Sub: mlb-phase4-precompute-complete)"
echo "  - mlb-phase5-to-phase6 (Pub/Sub: mlb-phase5-predictions-complete)"
echo "  - mlb-self-heal (HTTP, Scheduler: mlb-self-heal-daily PAUSED)"
echo ""
echo "All orchestrators are deployed but schedulers are PAUSED (MLB off-season)."
echo ""
echo "To enable before MLB season:"
echo "  gcloud scheduler jobs resume mlb-self-heal-daily --location=$REGION"
echo ""
