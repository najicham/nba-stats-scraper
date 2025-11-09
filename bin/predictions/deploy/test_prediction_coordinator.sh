#!/bin/bash
# bin/predictions/deploy/test_prediction_coordinator.sh
#
# Test Phase 5 Prediction Coordinator deployment
#
# Usage:
#   ./bin/predictions/deploy/test_prediction_coordinator.sh [environment]

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

ENVIRONMENT="${1:-dev}"

case "$ENVIRONMENT" in
    dev)
        PROJECT_ID="nba-props-platform-dev"
        REGION="us-central1"
        SERVICE_NAME="prediction-coordinator-dev"
        ;;
    staging)
        PROJECT_ID="nba-props-platform-staging"
        REGION="us-central1"
        SERVICE_NAME="prediction-coordinator-staging"
        ;;
    prod)
        PROJECT_ID="nba-props-platform"
        REGION="us-central1"
        SERVICE_NAME="prediction-coordinator"
        ;;
    *)
        echo "Error: Invalid environment '$ENVIRONMENT'"
        exit 1
        ;;
esac

# ============================================================================
# Functions
# ============================================================================

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

error() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
    exit 1
}

test_health_check() {
    log "Testing health check endpoint..."
    
    SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --format "value(status.url)")
    
    TOKEN=$(gcloud auth print-identity-token)
    
    RESPONSE=$(curl -s -w "\n%{http_code}" -H "Authorization: Bearer $TOKEN" "${SERVICE_URL}/health")
    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    BODY=$(echo "$RESPONSE" | head -n-1)
    
    if [ "$HTTP_CODE" = "200" ]; then
        log "✓ Health check passed"
        log "  Response: $BODY"
    else
        error "Health check failed with status $HTTP_CODE"
    fi
}

test_start_batch() {
    log "Testing batch start..."
    
    SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --format "value(status.url)")
    
    TOKEN=$(gcloud auth print-identity-token)
    
    # Start a prediction batch for today
    RESPONSE=$(curl -s -w "\n%{http_code}" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{
            "game_date": "'$(date +%Y-%m-%d)'",
            "min_minutes": 15,
            "use_multiple_lines": false
        }' \
        "${SERVICE_URL}/start")
    
    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    BODY=$(echo "$RESPONSE" | head -n-1)
    
    if [ "$HTTP_CODE" = "202" ] || [ "$HTTP_CODE" = "409" ]; then
        log "✓ Batch start successful"
        echo "$BODY" | jq .
        
        # Extract batch_id for monitoring
        BATCH_ID=$(echo "$BODY" | jq -r '.batch_id // empty')
        
        if [ -n "$BATCH_ID" ]; then
            log "Batch ID: $BATCH_ID"
            echo "$BATCH_ID" > /tmp/last_batch_id.txt
        fi
    else
        log "⚠ Batch start returned status $HTTP_CODE"
        echo "$BODY" | jq .
    fi
}

test_status_check() {
    log "Testing status endpoint..."
    
    SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --format "value(status.url)")
    
    TOKEN=$(gcloud auth print-identity-token)
    
    # Check if we have a batch_id from previous test
    if [ -f /tmp/last_batch_id.txt ]; then
        BATCH_ID=$(cat /tmp/last_batch_id.txt)
        STATUS_URL="${SERVICE_URL}/status?batch_id=${BATCH_ID}"
    else
        STATUS_URL="${SERVICE_URL}/status"
    fi
    
    RESPONSE=$(curl -s -w "\n%{http_code}" \
        -H "Authorization: Bearer $TOKEN" \
        "$STATUS_URL")
    
    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    BODY=$(echo "$RESPONSE" | head -n-1)
    
    if [ "$HTTP_CODE" = "200" ]; then
        log "✓ Status check successful"
        echo "$BODY" | jq .
    else
        error "Status check failed with status $HTTP_CODE"
    fi
}

monitor_progress() {
    log "Monitoring batch progress (30 seconds)..."
    
    SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --format "value(status.url)")
    
    TOKEN=$(gcloud auth print-identity-token)
    
    for i in {1..6}; do
        RESPONSE=$(curl -s -H "Authorization: Bearer $TOKEN" "${SERVICE_URL}/status")
        
        COMPLETED=$(echo "$RESPONSE" | jq -r '.progress.completed // 0')
        EXPECTED=$(echo "$RESPONSE" | jq -r '.progress.expected // 0')
        IS_COMPLETE=$(echo "$RESPONSE" | jq -r '.status == "complete"')
        
        log "Progress: $COMPLETED/$EXPECTED players"
        
        if [ "$IS_COMPLETE" = "true" ]; then
            log "✓ Batch complete!"
            echo "$RESPONSE" | jq '.summary'
            return 0
        fi
        
        sleep 5
    done
    
    log "⏳ Batch still in progress (check status endpoint for updates)"
}

check_bigquery_predictions() {
    log "Checking BigQuery for predictions..."
    
    QUERY="
    SELECT 
        system_id,
        COUNT(*) as predictions,
        COUNT(DISTINCT player_lookup) as unique_players,
        AVG(confidence_score) as avg_confidence
    FROM \`${PROJECT_ID}.nba_predictions.player_prop_predictions\`
    WHERE game_date = CURRENT_DATE()
      AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 10 MINUTE)
    GROUP BY system_id
    ORDER BY system_id
    "
    
    RESULTS=$(bq query --project_id="$PROJECT_ID" --use_legacy_sql=false --format=prettyjson "$QUERY")
    
    if [ "$RESULTS" != "[]" ]; then
        log "✓ Predictions found in BigQuery"
        echo "$RESULTS" | jq -r '.[] | "  - \(.system_id): \(.predictions) predictions for \(.unique_players) players (avg conf: \(.avg_confidence)%)"'
    else
        log "⚠ No recent predictions found (may still be processing)"
    fi
}

check_cloud_run_logs() {
    log "Checking recent Cloud Run logs..."
    
    gcloud run services logs read "$SERVICE_NAME" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --limit 20 \
        --format "table(timestamp,severity,textPayload)"
}

# ============================================================================
# Main
# ============================================================================

main() {
    log "Testing prediction coordinator in environment: $ENVIRONMENT"
    
    test_health_check
    echo ""
    
    test_start_batch
    echo ""
    
    test_status_check
    echo ""
    
    monitor_progress
    echo ""
    
    check_bigquery_predictions
    echo ""
    
    check_cloud_run_logs
    
    log "Testing complete! ✓"
    log ""
    log "Next steps:"
    log "  - View logs: gcloud run services logs read $SERVICE_NAME --project $PROJECT_ID --region $REGION --tail"
    log "  - Check status: curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \"\$(gcloud run services describe $SERVICE_NAME --project $PROJECT_ID --region $REGION --format 'value(status.url)')/status\" | jq ."
    log "  - Trigger manually: curl -X POST -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \"\$(gcloud run services describe $SERVICE_NAME --project $PROJECT_ID --region $REGION --format 'value(status.url)')/start\" | jq ."
}

main
