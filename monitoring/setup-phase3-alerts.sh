#!/bin/bash
# Setup Cloud Monitoring Alerts for Phase 3 Analytics Processor
# This script creates log-based metrics and alerting policies for Phase 3 scheduler failures
#
# Background:
#   On Jan 17, 2026, Phase 3 created only 1 record instead of 156, causing 14 players
#   to miss predictions. This alert detects failures early to enable manual intervention.
#
# Usage:
#   ./monitoring/setup-phase3-alerts.sh

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"

echo "================================================"
echo "  Setting up Phase 3 Monitoring Alerts"
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
        echo "  ✓ Metric $metric_name already exists, updating..."
        gcloud logging metrics update "$metric_name" \
            --project="$PROJECT_ID" \
            --description="$description" \
            --log-filter="$filter"
    else
        echo "  ✓ Creating new metric: $metric_name"
        gcloud logging metrics create "$metric_name" \
            --project="$PROJECT_ID" \
            --description="$description" \
            --log-filter="$filter"
    fi
}

echo "1. Creating log-based metric for Phase 3 scheduler failures..."
echo ""
create_log_metric \
    "phase3_scheduler_failures" \
    "Phase 3 same-day-phase3-tomorrow scheduler failures or errors" \
    'resource.type="cloud_scheduler_job"
AND resource.labels.job_id="same-day-phase3-tomorrow"
AND (severity>=ERROR
     OR jsonPayload.message:"failed"
     OR jsonPayload.message:"error"
     OR httpRequest.status>=400)'

echo ""
echo "2. Creating log-based metric for Phase 3 processor errors..."
echo ""
create_log_metric \
    "phase3_processor_errors" \
    "Phase 3 analytics processor errors during execution" \
    'resource.labels.service_name="nba-phase3-analytics-processors"
AND severity>=ERROR'

echo ""
echo "================================================"
echo "✓ Log-based metrics created successfully!"
echo ""
echo "Next Steps:"
echo "================================================"
echo ""
echo "1. Get Slack notification channel ID:"
echo "   gcloud alpha monitoring channels list --format=\"table(name,displayName)\""
echo ""
echo "2. Update phase3-scheduler-failure-alert.yaml:"
echo "   - Replace SLACK_ERROR_CHANNEL_ID with actual channel ID"
echo "   - Edit: monitoring/alert-policies/phase3-scheduler-failure-alert.yaml"
echo ""
echo "3. Deploy alert policy:"
echo "   cd monitoring/alert-policies"
echo "   gcloud alpha monitoring policies create \\"
echo "     --policy-from-file=phase3-scheduler-failure-alert.yaml"
echo ""
echo "4. Verify deployment:"
echo "   gcloud alpha monitoring policies list --filter=\"displayName:'Phase 3 Scheduler'\""
echo ""
echo "5. Test the alert (optional - triggers notification):"
echo "   # Manually view recent Phase 3 executions"
echo "   gcloud logging read 'resource.type=\"cloud_scheduler_job\" AND"
echo "     resource.labels.job_id=\"same-day-phase3-tomorrow\"' --limit=5"
echo ""
echo "================================================"
echo ""
echo "📊 Metrics will be available in ~2 minutes at:"
echo "   https://console.cloud.google.com/logs/metrics?project=$PROJECT_ID"
echo ""
echo "🔔 Alert policies at:"
echo "   https://console.cloud.google.com/monitoring/alerting?project=$PROJECT_ID"
echo "================================================"
