#!/bin/bash
# bin/predictions/deploy/test_prediction_worker.sh
#
# Test Phase 5 Prediction Worker deployment
#
# Usage:
#   ./bin/predictions/deploy/test_prediction_worker.sh [environment]
#
# Arguments:
#   environment - dev, staging, or prod (default: dev)

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

ENVIRONMENT="${1:-dev}"

case "$ENVIRONMENT" in
    dev)
        PROJECT_ID="nba-props-platform-dev"
        REGION="us-central1"
        SERVICE_NAME="prediction-worker-dev"
        PUBSUB_TOPIC="prediction-request-dev"
        ;;
    staging)
        PROJECT_ID="nba-props-platform-staging"
        REGION="us-central1"
        SERVICE_NAME="prediction-worker-staging"
        PUBSUB_TOPIC="prediction-request-staging"
        ;;
    prod)
        PROJECT_ID="nba-props-platform"
        REGION="us-central1"
        SERVICE_NAME="prediction-worker"
        PUBSUB_TOPIC="prediction-request"
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
    
    # Get ID token for authenticated request
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

test_prediction_request() {
    log "Testing prediction via Pub/Sub..."
    
    # Test message for LeBron James
    TEST_MESSAGE='{
        "player_lookup": "lebron-james",
        "game_date": "2025-11-08",
        "game_id": "20251108_LAL_GSW",
        "line_values": [25.5]
    }'
    
    log "Publishing test message to $PUBSUB_TOPIC..."
    
    MESSAGE_ID=$(gcloud pubsub topics publish "$PUBSUB_TOPIC" \
        --project "$PROJECT_ID" \
        --message "$TEST_MESSAGE" \
        --format "value(messageIds[0])")
    
    log "✓ Message published: $MESSAGE_ID"
    log "  Waiting for processing (10 seconds)..."
    
    sleep 10
    
    # Check if prediction was written to BigQuery
    log "Checking BigQuery for prediction..."
    
    QUERY="
    SELECT 
        prediction_id,
        system_id,
        predicted_points,
        confidence_score,
        recommendation,
        created_at
    FROM \`${PROJECT_ID}.nba_predictions.player_prop_predictions\`
    WHERE player_lookup = 'lebron-james'
      AND game_date = '2025-11-08'
      AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 MINUTE)
    ORDER BY created_at DESC
    LIMIT 10
    "
    
    RESULTS=$(bq query --project_id="$PROJECT_ID" --use_legacy_sql=false --format=prettyjson "$QUERY")
    
    if [ "$RESULTS" != "[]" ]; then
        log "✓ Predictions found in BigQuery"
        echo "$RESULTS" | jq -r '.[] | "  - \(.system_id): \(.predicted_points) pts (conf: \(.confidence_score)%, rec: \(.recommendation))"'
    else
        log "⚠ No predictions found yet (may still be processing)"
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

show_metrics() {
    log "Recent metrics..."
    
    # Get service details
    SERVICE_INFO=$(gcloud run services describe "$SERVICE_NAME" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --format json)
    
    echo "$SERVICE_INFO" | jq -r '
        "Status: " + .status.conditions[0].status,
        "URL: " + .status.url,
        "Latest Revision: " + .status.latestReadyRevisionName,
        "Traffic: " + (.status.traffic[0].percent | tostring) + "%"
    '
}

# ============================================================================
# Main
# ============================================================================

main() {
    log "Testing prediction worker in environment: $ENVIRONMENT"
    
    test_health_check
    echo ""
    
    test_prediction_request
    echo ""
    
    check_cloud_run_logs
    echo ""
    
    show_metrics
    
    log "Testing complete! ✓"
    log ""
    log "Next steps:"
    log "  - View logs: gcloud run services logs read $SERVICE_NAME --project $PROJECT_ID --region $REGION --tail"
    log "  - View metrics: https://console.cloud.google.com/run/detail/${REGION}/${SERVICE_NAME}/metrics?project=${PROJECT_ID}"
    log "  - Check BigQuery: https://console.cloud.google.com/bigquery?project=${PROJECT_ID}&ws=!1m5!1m4!4m3!1s${PROJECT_ID}!2snba_predictions!3splayer_prop_predictions"
}

main
