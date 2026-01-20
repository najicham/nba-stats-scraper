#!/bin/bash
#
# Deployment Script: Robustness Improvements (Week 0 Fixes)
# Deploys all new alerting and monitoring infrastructure
#
# Usage: ./bin/deploy_robustness_improvements.sh [--dry-run]
#
# Created: 2026-01-20
# Version: 1.0

set -e

PROJECT_ID="nba-props-platform"
REGION_WEST="us-west1"
REGION_CENTRAL="us-central1"

DRY_RUN=false
if [[ "$1" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "=========================================="
    echo "  DRY RUN MODE - No changes will be made"
    echo "=========================================="
    echo ""
fi

function run_command() {
    if $DRY_RUN; then
        echo "[DRY RUN] $@"
    else
        echo "Running: $@"
        "$@"
    fi
}

echo "=========================================="
echo "  NBA Pipeline Robustness Improvements"
echo "=========================================="
echo "Project: $PROJECT_ID"
echo "Date: $(date)"
echo ""

# ==================================================
# Phase 1: Deploy Alert Functions
# ==================================================
echo "Phase 1: Deploying Alert Functions"
echo "--------------------------------------------------"

echo "1/3: Deploying box-score-completeness-alert..."
run_command gcloud functions deploy box-score-completeness-alert \
    --gen2 \
    --runtime python311 \
    --region $REGION_WEST \
    --source orchestration/cloud_functions/box_score_completeness_alert \
    --entry-point check_box_score_completeness \
    --trigger-http \
    --allow-unauthenticated \
    --set-env-vars GCP_PROJECT=$PROJECT_ID \
    --timeout 180 \
    --memory 256MB \
    --quiet

echo "2/3: Deploying phase4-failure-alert..."
run_command gcloud functions deploy phase4-failure-alert \
    --gen2 \
    --runtime python311 \
    --region $REGION_WEST \
    --source orchestration/cloud_functions/phase4_failure_alert \
    --entry-point check_phase4_status \
    --trigger-http \
    --allow-unauthenticated \
    --set-env-vars GCP_PROJECT=$PROJECT_ID \
    --timeout 180 \
    --memory 256MB \
    --quiet

echo "3/3: Alert functions deployed ✅"
echo ""

# ==================================================
# Phase 2: Create Cloud Schedulers
# ==================================================
echo "Phase 2: Creating Cloud Schedulers"
echo "--------------------------------------------------"

echo "1/2: Creating box-score-completeness-alert scheduler (every 6 hours)..."
run_command gcloud scheduler jobs create http box-score-alert-job \
    --location=$REGION_CENTRAL \
    --schedule="0 */6 * * *" \
    --time-zone="America/New_York" \
    --uri="https://$REGION_WEST-$PROJECT_ID.cloudfunctions.net/box-score-completeness-alert" \
    --http-method=POST \
    --description="Check box score completeness every 6 hours" \
    --attempt-deadline=180s \
    --quiet || echo "Scheduler already exists (skipping)"

echo "2/2: Creating phase4-failure-alert scheduler (daily 12 PM ET)..."
run_command gcloud scheduler jobs create http phase4-alert-job \
    --location=$REGION_CENTRAL \
    --schedule="0 12 * * *" \
    --time-zone="America/New_York" \
    --uri="https://$REGION_WEST-$PROJECT_ID.cloudfunctions.net/phase4-failure-alert" \
    --http-method=POST \
    --description="Check Phase 4 processor completion daily" \
    --attempt-deadline=180s \
    --quiet || echo "Scheduler already exists (skipping)"

echo "Cloud Schedulers created ✅"
echo ""

# ==================================================
# Phase 3: Verification
# ==================================================
echo "Phase 3: Verification"
echo "--------------------------------------------------"

echo "Checking deployed functions..."
FUNCTIONS=(
    "box-score-completeness-alert"
    "phase4-failure-alert"
)

for func in "${FUNCTIONS[@]}"; do
    if gcloud functions describe "$func" --region=$REGION_WEST --gen2 &>/dev/null; then
        echo "  ✅ $func deployed"
    else
        echo "  ❌ $func NOT DEPLOYED"
        exit 1
    fi
done

echo ""
echo "Checking schedulers..."
SCHEDULERS=(
    "box-score-alert-job"
    "phase4-alert-job"
)

for scheduler in "${SCHEDULERS[@]}"; do
    if gcloud scheduler jobs describe "$scheduler" --location=$REGION_CENTRAL &>/dev/null; then
        echo "  ✅ $scheduler created"
    else
        echo "  ❌ $scheduler NOT CREATED"
        exit 1
    fi
done

echo ""
echo "=========================================="
echo "  ✅ ALL DEPLOYMENTS SUCCESSFUL"
echo "=========================================="
echo ""
echo "Next Steps:"
echo "1. Test alerts with dry-run:"
echo "   curl 'https://$REGION_WEST-$PROJECT_ID.cloudfunctions.net/box-score-completeness-alert?dry_run=true'"
echo "   curl 'https://$REGION_WEST-$PROJECT_ID.cloudfunctions.net/phase4-failure-alert?dry_run=true'"
echo ""
echo "2. Monitor first scheduled runs:"
echo "   - Box score alert: Every 6 hours"
echo "   - Phase 4 alert: Daily at 12 PM ET"
echo ""
echo "3. Check logs:"
echo "   gcloud functions logs read box-score-completeness-alert --gen2 --region=$REGION_WEST --limit=50"
echo "   gcloud functions logs read phase4-failure-alert --gen2 --region=$REGION_WEST --limit=50"
echo ""
