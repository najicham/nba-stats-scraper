#!/bin/bash
# Post-Deployment Monitoring with Automated Rollback
#
# Monitors critical metrics after deployment and triggers rollback if degradation detected.
# Run this after deploying critical services (prediction-worker, phase4-processors, etc.)
#
# Usage:
#   ./bin/monitoring/post-deployment-monitor.sh <service-name> [--auto-rollback]
#
# Example:
#   ./bin/monitoring/post-deployment-monitor.sh prediction-worker --auto-rollback
#
# Monitors for 30 minutes with checks every 5 minutes.
# Triggers rollback if:
#   - Error rate >5%
#   - Service health check fails
#   - Critical metric degradation (service-specific)

set -euo pipefail

SERVICE=$1
AUTO_ROLLBACK=${2:-""}
REGION="us-west2"
PROJECT="nba-props-platform"

MONITOR_DURATION=1800  # 30 minutes
CHECK_INTERVAL=300     # 5 minutes
CHECKS_COUNT=$((MONITOR_DURATION / CHECK_INTERVAL))

ERROR_THRESHOLD=5  # Max error rate %
ROLLBACK_TRIGGERED=false

if [ -z "$SERVICE" ]; then
    echo "Usage: $0 <service-name> [--auto-rollback]"
    echo ""
    echo "Examples:"
    echo "  $0 prediction-worker --auto-rollback"
    echo "  $0 nba-phase4-precompute-processors"
    exit 1
fi

echo "=============================================="
echo "POST-DEPLOYMENT MONITORING: $SERVICE"
echo "=============================================="
echo "Duration: $MONITOR_DURATION seconds ($CHECKS_COUNT checks)"
echo "Interval: $CHECK_INTERVAL seconds"
echo "Auto-rollback: $([ \"$AUTO_ROLLBACK\" = \"--auto-rollback\" ] && echo \"ENABLED\" || echo \"DISABLED\")"
echo "=============================================="
echo ""

# Get current and previous revision
CURRENT_REVISION=$(gcloud run services describe "$SERVICE" --region="$REGION" \
    --format="value(status.latestReadyRevisionName)" 2>/dev/null)

PREVIOUS_REVISION=$(gcloud run revisions list --service="$SERVICE" --region="$REGION" \
    --format="value(metadata.name)" --limit=2 2>/dev/null | tail -1)

echo "Current revision: $CURRENT_REVISION"
echo "Previous revision: $PREVIOUS_REVISION"
echo ""

# Function to check error rate
check_error_rate() {
    local start_time=$1

    ERROR_COUNT=$(gcloud logging read \
        "resource.type=\"cloud_run_revision\"
         AND resource.labels.service_name=\"$SERVICE\"
         AND resource.labels.revision_name=\"$CURRENT_REVISION\"
         AND severity>=ERROR
         AND timestamp>=\"$start_time\"" \
        --limit=1000 \
        --format="value(severity)" \
        --project="$PROJECT" 2>/dev/null | wc -l)

    TOTAL_REQUESTS=$(gcloud logging read \
        "resource.type=\"cloud_run_revision\"
         AND resource.labels.service_name=\"$SERVICE\"
         AND resource.labels.revision_name=\"$CURRENT_REVISION\"
         AND timestamp>=\"$start_time\"" \
        --limit=1000 \
        --format="value(severity)" \
        --project="$PROJECT" 2>/dev/null | wc -l)

    if [ "$TOTAL_REQUESTS" -gt 0 ]; then
        ERROR_RATE=$(awk "BEGIN {printf \"%.1f\", ($ERROR_COUNT / $TOTAL_REQUESTS) * 100}")
    else
        ERROR_RATE=0
    fi

    echo "$ERROR_RATE"
}

# Function to check service health
check_service_health() {
    SERVICE_URL=$(gcloud run services describe "$SERVICE" --region="$REGION" \
        --format="value(status.url)" 2>/dev/null)

    if [ -n "$SERVICE_URL" ]; then
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -m 10 "$SERVICE_URL/health" 2>/dev/null || echo "000")
        echo "$HTTP_CODE"
    else
        echo "000"
    fi
}

# Function to check service-specific metrics
check_service_specific_metrics() {
    case $SERVICE in
        prediction-worker)
            # Check if predictions are being generated
            RECENT_PREDS=$(bq query --use_legacy_sql=false --format=csv --quiet \
                "SELECT COUNT(*) FROM nba_predictions.player_prop_predictions
                 WHERE created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)" \
                2>/dev/null | tail -1)

            if [ "$RECENT_PREDS" = "0" ] && [ "$(date +%H)" -ge 7 ]; then
                echo "FAIL: No predictions in last 30 minutes (during active hours)"
                return 1
            fi
            ;;

        nba-phase4-precompute-processors)
            # Check Vegas line coverage
            ./bin/monitoring/check_vegas_line_coverage.sh --days 1 > /dev/null 2>&1
            if [ $? -eq 2 ]; then
                echo "FAIL: Vegas line coverage below critical threshold"
                return 1
            fi
            ;;

        nba-phase3-analytics-processors)
            # Check processor heartbeats
            RECENT_HEARTBEAT=$(gcloud logging read \
                "resource.labels.service_name=\"$SERVICE\"
                 AND jsonPayload.message=~\"Heartbeat\"
                 AND timestamp>=\"$(date -u -d '30 minutes ago' +%Y-%m-%dT%H:%M:%SZ)\"" \
                --limit=1 --format="value(timestamp)" --project="$PROJECT" 2>/dev/null)

            if [ -z "$RECENT_HEARTBEAT" ]; then
                echo "FAIL: No heartbeats in last 30 minutes"
                return 1
            fi
            ;;
    esac

    echo "PASS"
    return 0
}

# Function to trigger rollback
trigger_rollback() {
    echo ""
    echo "=============================================="
    echo "🚨 TRIGGERING AUTOMATIC ROLLBACK"
    echo "=============================================="
    echo "Service: $SERVICE"
    echo "Current (failing): $CURRENT_REVISION"
    echo "Rolling back to: $PREVIOUS_REVISION"
    echo ""

    if [ "$AUTO_ROLLBACK" = "--auto-rollback" ]; then
        gcloud run services update-traffic "$SERVICE" \
            --region="$REGION" \
            --to-revisions="$PREVIOUS_REVISION=100" \
            --quiet

        echo "✅ Rollback complete"
        echo ""
        echo "Verify rollback:"
        echo "  curl \$(gcloud run services describe $SERVICE --region=$REGION --format='value(status.url)')/health | jq ."
    else
        echo "⚠️  AUTO-ROLLBACK NOT ENABLED"
        echo ""
        echo "To rollback manually, run:"
        echo "  gcloud run services update-traffic $SERVICE \\"
        echo "    --region=$REGION \\"
        echo "    --to-revisions=$PREVIOUS_REVISION=100"
    fi

    ROLLBACK_TRIGGERED=true
}

# Monitoring loop
for i in $(seq 1 $CHECKS_COUNT); do
    echo "----------------------------------------"
    echo "Check $i/$CHECKS_COUNT ($(date))"
    echo "----------------------------------------"

    START_TIME=$(date -u -d "$CHECK_INTERVAL seconds ago" +%Y-%m-%dT%H:%M:%SZ)

    # 1. Check error rate
    ERROR_RATE=$(check_error_rate "$START_TIME")
    echo "Error rate: $ERROR_RATE%"

    if (( $(awk "BEGIN {print ($ERROR_RATE > $ERROR_THRESHOLD)}") )); then
        echo "❌ ERROR RATE ABOVE THRESHOLD ($ERROR_THRESHOLD%)"
        trigger_rollback
        break
    fi

    # 2. Check service health
    HEALTH_CODE=$(check_service_health)
    echo "Health check: HTTP $HEALTH_CODE"

    if [ "$HEALTH_CODE" != "200" ]; then
        echo "❌ HEALTH CHECK FAILED"
        trigger_rollback
        break
    fi

    # 3. Check service-specific metrics
    METRIC_CHECK=$(check_service_specific_metrics)
    echo "Service metrics: $METRIC_CHECK"

    if [ "$METRIC_CHECK" != "PASS" ]; then
        echo "❌ SERVICE METRICS DEGRADED: $METRIC_CHECK"
        trigger_rollback
        break
    fi

    echo "✅ All checks passed"

    # Sleep until next check (unless last iteration)
    if [ $i -lt $CHECKS_COUNT ]; then
        echo "Next check in $CHECK_INTERVAL seconds..."
        echo ""
        sleep $CHECK_INTERVAL
    fi
done

echo ""
echo "=============================================="
if [ "$ROLLBACK_TRIGGERED" = true ]; then
    echo "MONITORING COMPLETE - ROLLBACK TRIGGERED"
    echo "=============================================="
    exit 1
else
    echo "✅ MONITORING COMPLETE - DEPLOYMENT STABLE"
    echo "=============================================="
    echo "Service: $SERVICE"
    echo "Revision: $CURRENT_REVISION"
    echo "All checks passed for $MONITOR_DURATION seconds"
    exit 0
fi
