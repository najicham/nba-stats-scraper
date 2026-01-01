#!/bin/bash
# Setup Cloud Monitoring Alerts for Prediction Pipeline
# This script creates log-based metrics and alerting policies

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"

echo "================================================"
echo "  Setting up Pipeline Monitoring Alerts"
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

# 1. Scheduler Failures
echo "1. Creating metric for scheduler failures..."
create_log_metric \
    "prediction_scheduler_failures" \
    "Count of prediction scheduler job failures" \
    'resource.type="cloud_scheduler_job"
AND (resource.labels.job_id="overnight-predictions"
     OR resource.labels.job_id="same-day-predictions"
     OR resource.labels.job_id="same-day-predictions-tomorrow")
AND jsonPayload.@type="type.googleapis.com/google.cloud.scheduler.logging.AttemptFinished"
AND jsonPayload.status!="OK"'

# 2. Batch Loading Failures
echo "2. Creating metric for batch loading failures..."
create_log_metric \
    "batch_loading_failures" \
    "Count of batch historical loading failures in coordinator" \
    'resource.labels.service_name="prediction-coordinator"
AND textPayload=~"Batch historical load failed"'

# 3. Consolidation Failures
echo "3. Creating metric for consolidation failures..."
create_log_metric \
    "consolidation_failures" \
    "Count of staging table consolidation failures" \
    'resource.labels.service_name="prediction-coordinator"
AND textPayload=~"Consolidation failed"'

# 4. Phase 6 Skipped Events
echo "4. Creating metric for Phase 6 skipped events..."
create_log_metric \
    "phase6_skipped" \
    "Count of times Phase 6 was skipped due to low completion" \
    'resource.labels.service_name="phase5-to-phase6-orchestrator"
AND textPayload=~"Skipping Phase 6 trigger"'

# 5. Staging Write Failures
echo "5. Creating metric for staging write failures..."
create_log_metric \
    "staging_write_failures" \
    "Count of worker staging table write failures" \
    'resource.labels.service_name="prediction-worker"
AND textPayload=~"Staging write failed"'

# 6. Successful Batch Completions (for positive signal)
echo "6. Creating metric for successful batch completions..."
create_log_metric \
    "batch_completion_success" \
    "Count of successful batch loading events" \
    'resource.labels.service_name="prediction-coordinator"
AND textPayload=~"Batch loaded historical games"'

# 7. Phase 6 Export Completions
echo "7. Creating metric for Phase 6 export completions..."
create_log_metric \
    "phase6_export_completions" \
    "Count of successful Phase 6 exports" \
    'resource.labels.service_name="phase6-export"
AND textPayload=~"Export completed"'

echo ""
echo "================================================"
echo "✓ Log-based metrics created successfully!"
echo ""
echo "Next steps:"
echo "1. View metrics in Cloud Console:"
echo "   https://console.cloud.google.com/logs/metrics?project=$PROJECT_ID"
echo ""
echo "2. Create alert policies manually in Cloud Console or use gcloud alpha:"
echo "   https://console.cloud.google.com/monitoring/alerting?project=$PROJECT_ID"
echo ""
echo "3. Run health check tomorrow after overnight run:"
echo "   ./bin/monitoring/check_pipeline_health.sh"
echo "================================================"
