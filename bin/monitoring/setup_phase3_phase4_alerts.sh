#!/bin/bash
# Setup Cloud Monitoring Alerts for Phase 3 and Phase 4 Services
# Created: January 21, 2026
# Purpose: Prevent future 25+ hour detection gaps like the HealthChecker incident

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
NOTIFICATION_CHANNEL="projects/nba-props-platform/notificationChannels/13444328261517403081"

echo "================================================"
echo "  Setting up Phase 3/4 Service Monitoring"
echo "  Project: $PROJECT_ID"
echo "================================================"
echo ""

# Function to create or update log-based metric
create_log_metric() {
    local metric_name="$1"
    local description="$2"
    local filter="$3"

    echo "Creating log metric: $metric_name"

    # Check if metric exists
    if gcloud logging metrics describe "$metric_name" --project="$PROJECT_ID" &>/dev/null; then
        echo "  Metric $metric_name already exists, updating..."
        gcloud logging metrics update "$metric_name" \
            --project="$PROJECT_ID" \
            --description="$description" \
            --log-filter="$filter" || true
    else
        echo "  Creating new metric: $metric_name"
        gcloud logging metrics create "$metric_name" \
            --project="$PROJECT_ID" \
            --description="$description" \
            --log-filter="$filter" || true
    fi
}

# 1. Phase 3 Analytics Errors
echo "1. Creating metric for Phase 3 Analytics errors..."
create_log_metric \
    "phase3_analytics_errors" \
    "Count of errors in Phase 3 Analytics service" \
    'resource.type="cloud_run_revision"
AND resource.labels.service_name="nba-phase3-analytics-processors"
AND severity>=ERROR'

# 2. Phase 4 Precompute Errors
echo "2. Creating metric for Phase 4 Precompute errors..."
create_log_metric \
    "phase4_precompute_errors" \
    "Count of errors in Phase 4 Precompute service" \
    'resource.type="cloud_run_revision"
AND resource.labels.service_name="nba-phase4-precompute-processors"
AND severity>=ERROR'

# 3. Phase 3 HTTP 5xx Errors
echo "3. Creating metric for Phase 3 HTTP 5xx errors..."
create_log_metric \
    "phase3_5xx_errors" \
    "Count of 5xx HTTP errors from Phase 3 Analytics" \
    'resource.type="cloud_run_revision"
AND resource.labels.service_name="nba-phase3-analytics-processors"
AND httpRequest.status>=500'

# 4. Phase 4 HTTP 5xx Errors
echo "4. Creating metric for Phase 4 HTTP 5xx errors..."
create_log_metric \
    "phase4_5xx_errors" \
    "Count of 5xx HTTP errors from Phase 4 Precompute" \
    'resource.type="cloud_run_revision"
AND resource.labels.service_name="nba-phase4-precompute-processors"
AND httpRequest.status>=500'

# 5. Admin Dashboard Errors
echo "5. Creating metric for Admin Dashboard errors..."
create_log_metric \
    "admin_dashboard_errors" \
    "Count of errors in Admin Dashboard service" \
    'resource.type="cloud_run_revision"
AND resource.labels.service_name="nba-admin-dashboard"
AND severity>=ERROR'

echo ""
echo "================================================"
echo "✓ Log-based metrics created successfully!"
echo ""
echo "Next steps to create alert policies:"
echo ""
echo "1. Phase 3 Error Rate Alert:"
echo "   gcloud alpha monitoring policies create \\"
echo "     --notification-channels=$NOTIFICATION_CHANNEL \\"
echo "     --display-name='Phase 3 Analytics Error Rate' \\"
echo "     --condition-display-name='Phase 3 Error Rate >5% in 5 min' \\"
echo "     --condition-threshold-value=0.05 \\"
echo "     --condition-threshold-duration=300s \\"
echo "     --project=$PROJECT_ID"
echo ""
echo "2. Phase 4 Error Rate Alert:"
echo "   gcloud alpha monitoring policies create \\"
echo "     --notification-channels=$NOTIFICATION_CHANNEL \\"
echo "     --display-name='Phase 4 Precompute Error Rate' \\"
echo "     --condition-display-name='Phase 4 Error Rate >5% in 5 min' \\"
echo "     --condition-threshold-value=0.05 \\"
echo "     --condition-threshold-duration=300s \\"
echo "     --project=$PROJECT_ID"
echo ""
echo "Or create alerts in Cloud Console:"
echo "https://console.cloud.google.com/monitoring/alerting?project=$PROJECT_ID"
echo ""
echo "View metrics:"
echo "https://console.cloud.google.com/logs/metrics?project=$PROJECT_ID"
echo "================================================"
