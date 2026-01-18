#!/bin/bash
# bin/alerts/test_week1_alerts.sh
#
# Week 1 Alert Testing - End-to-End Verification
#
# Tests both critical alerts implemented in Week 1:
# 1. Model Loading Failure Alert
# 2. High Fallback Prediction Rate Alert
#
# WARNING: This script temporarily breaks production prediction-worker!
# - Predictions will use fallback mode (50% confidence) for ~10 minutes
# - Only run during low-traffic periods or in dev/staging environment
#
# Usage:
#   ./bin/alerts/test_week1_alerts.sh
#
# Prerequisites:
#   - gcloud CLI authenticated
#   - Access to nba-props-platform project
#   - Slack channel configured for alerts
#
# Expected Duration: 10-15 minutes

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

PROJECT_ID="nba-props-platform"
REGION="us-west2"
SERVICE_NAME="prediction-worker"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ============================================================================
# Functions
# ============================================================================

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $*"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING:${NC} $*"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR:${NC} $*" >&2
}

confirm() {
    local message="$1"
    local response

    echo -e "${YELLOW}$message${NC}"
    read -p "Type 'yes' to continue: " response

    if [ "$response" != "yes" ]; then
        error "Test cancelled by user"
        exit 1
    fi
}

wait_for_alert() {
    local alert_name="$1"
    local wait_time="$2"

    log "Waiting $wait_time seconds for alert to fire..."
    sleep "$wait_time"

    log "Check your Slack channel for: $alert_name"
    echo ""
    read -p "Did the alert fire in Slack? (yes/no): " response

    if [ "$response" == "yes" ]; then
        log "✅ Alert verified: $alert_name"
        return 0
    else
        warn "❌ Alert did not fire: $alert_name"
        return 1
    fi
}

# ============================================================================
# Pre-flight Checks
# ============================================================================

log "Starting Week 1 Alert Testing"
echo ""

log "Running pre-flight checks..."

# Check gcloud authentication
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
    error "Not logged in to gcloud. Run: gcloud auth login"
    exit 1
fi

# Check project access
if ! gcloud projects describe "$PROJECT_ID" &> /dev/null; then
    error "Cannot access project: $PROJECT_ID"
    exit 1
fi

# Get current service configuration
log "Checking current service state..."

CURRENT_REVISION=$(gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --format="value(status.traffic[0].revisionName)")

log "Current revision: $CURRENT_REVISION"

# Get current environment variables
log "Backing up current environment variables..."

BACKUP_ENV_FILE="/tmp/prediction-worker-env-backup-$(date +%Y%m%d-%H%M%S).json"

gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --format=json | jq '.spec.template.spec.containers[0].env' > "$BACKUP_ENV_FILE"

log "Environment variables backed up to: $BACKUP_ENV_FILE"

# Get CATBOOST_V8_MODEL_PATH
ORIGINAL_MODEL_PATH=$(gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --format=json | jq -r '.spec.template.spec.containers[0].env[] | select(.name == "CATBOOST_V8_MODEL_PATH") | .value')

if [ -z "$ORIGINAL_MODEL_PATH" ]; then
    error "CATBOOST_V8_MODEL_PATH not found! Service may already be broken."
    exit 1
fi

log "Current CATBOOST_V8_MODEL_PATH: $ORIGINAL_MODEL_PATH"

log "✅ Pre-flight checks complete"
echo ""

# ============================================================================
# Safety Confirmation
# ============================================================================

warn "⚠️  PRODUCTION IMPACT WARNING ⚠️"
echo ""
echo "This test will:"
echo "  1. Remove CATBOOST_V8_MODEL_PATH from prediction-worker"
echo "  2. Cause predictions to use fallback mode (50% confidence) for ~10 minutes"
echo "  3. Generate fallback predictions in production database"
echo "  4. Test that alerts fire correctly"
echo "  5. Restore the environment variable"
echo ""
echo "During the test:"
echo "  - All predictions will have 50% confidence (not actual ML predictions)"
echo "  - Users will see conservative 'PASS' recommendations"
echo "  - Quality will be degraded until restoration"
echo ""
echo "Current service:"
echo "  - Revision: $CURRENT_REVISION"
echo "  - Model: $ORIGINAL_MODEL_PATH"
echo ""

confirm "Are you SURE you want to run this test in production?"

echo ""
log "Starting test sequence..."
echo ""

# ============================================================================
# Test 1: Model Loading Failure Alert
# ============================================================================

log "========================================="
log "TEST 1: Model Loading Failure Alert"
log "========================================="
echo ""

log "Step 1: Removing CATBOOST_V8_MODEL_PATH environment variable..."

gcloud run services update "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --remove-env-vars=CATBOOST_V8_MODEL_PATH \
    --quiet

NEW_REVISION=$(gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --format="value(status.traffic[0].revisionName)")

log "New revision deployed: $NEW_REVISION"
echo ""

log "Step 2: Waiting for service to start and model load to fail..."
sleep 30

log "Step 3: Checking logs for startup validation error..."
echo ""

gcloud logging read "resource.labels.service_name=\"$SERVICE_NAME\"
    AND resource.labels.revision_name=\"$NEW_REVISION\"
    AND severity>=ERROR
    AND textPayload=~\"CRITICAL\"" \
    --project="$PROJECT_ID" \
    --limit=5 \
    --format="table(timestamp,textPayload)" || true

echo ""

log "Step 4: Checking for model loading failure logs..."
echo ""

gcloud logging read "resource.labels.service_name=\"$SERVICE_NAME\"
    AND resource.labels.revision_name=\"$NEW_REVISION\"
    AND severity>=ERROR
    AND textPayload=~\"model FAILED\"" \
    --project="$PROJECT_ID" \
    --limit=3 \
    --format="table(timestamp,textPayload)" || true

echo ""

# Wait for alert
if wait_for_alert "[CRITICAL] NBA Model Loading Failures" 300; then
    TEST1_RESULT="PASSED"
else
    TEST1_RESULT="FAILED"
fi

echo ""

# ============================================================================
# Test 2: High Fallback Prediction Rate Alert
# ============================================================================

log "========================================="
log "TEST 2: High Fallback Prediction Rate Alert"
log "========================================="
echo ""

log "Step 1: Checking for fallback prediction logs..."
echo ""

gcloud logging read "resource.labels.service_name=\"$SERVICE_NAME\"
    AND textPayload=~\"FALLBACK_PREDICTION\"" \
    --project="$PROJECT_ID" \
    --limit=5 \
    --format="table(timestamp,textPayload)" || true

echo ""

log "Step 2: Checking fallback rate in BigQuery (if predictions have been generated)..."
echo ""

bq query --use_legacy_sql=false --project_id="$PROJECT_ID" '
SELECT
  COUNT(CASE WHEN confidence_score = 0.5 THEN 1 END) as fallback_count,
  COUNT(*) as total_predictions,
  ROUND(100.0 * COUNT(CASE WHEN confidence_score = 0.5 THEN 1 END) / COUNT(*), 2) as fallback_percent
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = "catboost_v8"
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 15 MINUTE)' || true

echo ""

# Wait for alert (10 minute threshold)
log "Note: This alert requires > 10% fallback rate over 10 minutes"
log "It may not fire if predictions are not being actively generated"
echo ""

if wait_for_alert "[CRITICAL] NBA High Fallback Prediction Rate" 600; then
    TEST2_RESULT="PASSED"
else
    TEST2_RESULT="FAILED (or not enough prediction traffic)"
fi

echo ""

# ============================================================================
# Restore Service
# ============================================================================

log "========================================="
log "RESTORATION: Restoring Service"
log "========================================="
echo ""

log "Step 1: Restoring CATBOOST_V8_MODEL_PATH environment variable..."

gcloud run services update "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --update-env-vars CATBOOST_V8_MODEL_PATH="$ORIGINAL_MODEL_PATH" \
    --quiet

RESTORED_REVISION=$(gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --format="value(status.traffic[0].revisionName)")

log "Service restored to revision: $RESTORED_REVISION"
echo ""

log "Step 2: Waiting for service to reload model..."
sleep 30

log "Step 3: Verifying model loaded successfully..."
echo ""

gcloud logging read "resource.labels.service_name=\"$SERVICE_NAME\"
    AND resource.labels.revision_name=\"$RESTORED_REVISION\"
    AND textPayload=~\"CATBOOST_V8_MODEL_PATH set\"" \
    --project="$PROJECT_ID" \
    --limit=3 \
    --format="table(timestamp,textPayload)" || true

echo ""

log "Step 4: Checking that fallback mode has stopped..."
echo ""

# Wait a bit for new predictions
sleep 60

bq query --use_legacy_sql=false --project_id="$PROJECT_ID" '
SELECT
  ROUND(confidence_score * 100) as confidence,
  COUNT(*) as predictions
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = "catboost_v8"
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 5 MINUTE)
GROUP BY confidence
ORDER BY confidence DESC
LIMIT 10' || true

echo ""
log "Expected: Variety of confidence scores (79-95%), NO 50%"
echo ""

# ============================================================================
# Test Summary
# ============================================================================

log "========================================="
log "TEST SUMMARY"
log "========================================="
echo ""

echo "Test 1 (Model Loading Alert): $TEST1_RESULT"
echo "Test 2 (Fallback Rate Alert): $TEST2_RESULT"
echo ""

if [ "$TEST1_RESULT" == "PASSED" ]; then
    echo "✅ Model loading failure alert is working correctly"
else
    echo "❌ Model loading failure alert did not fire as expected"
    echo "   → Check: gcloud alpha monitoring policies list --project=$PROJECT_ID"
    echo "   → Check: Slack webhook configuration"
    echo "   → Check: Alert policy thresholds"
fi

echo ""

if [ "$TEST2_RESULT" == "PASSED" ]; then
    echo "✅ Fallback prediction rate alert is working correctly"
else
    echo "⚠️  Fallback prediction rate alert did not fire"
    echo "   → This may be normal if prediction traffic is low"
    echo "   → Verify alert during high-traffic period"
    echo "   → Check: Alert policy thresholds (> 10% threshold)"
fi

echo ""

log "Service Status:"
echo "  - Original revision: $CURRENT_REVISION"
echo "  - Test revision (broken): $NEW_REVISION"
echo "  - Restored revision: $RESTORED_REVISION"
echo "  - Original model path: $ORIGINAL_MODEL_PATH"
echo ""

log "Backup file: $BACKUP_ENV_FILE"
log "Keep this file for reference or rollback if needed"
echo ""

log "========================================="
log "Next Steps:"
log "========================================="
echo ""
echo "1. Monitor alerts for next 10-15 minutes to ensure they clear"
echo "2. Verify production predictions have normal confidence scores"
echo "3. Review any fallback predictions generated during test:"
echo "   bq query --use_legacy_sql=false --project_id=$PROJECT_ID \\"
echo "     'SELECT COUNT(*) FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`"
echo "      WHERE system_id = \"catboost_v8\" AND confidence_score = 0.5"
echo "      AND created_at >= TIMESTAMP(\"$(date -u -d '15 minutes ago' '+%Y-%m-%d %H:%M:%S')\")'"
echo ""
echo "4. Clean up test predictions if needed (optional)"
echo "5. Update Week 1 status: Mark alerts as tested and verified"
echo ""

log "Test complete! 🚀"
