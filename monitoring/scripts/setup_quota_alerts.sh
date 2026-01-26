#!/bin/bash
# Setup script for Pipeline Quota Usage Monitoring
# Creates BigQuery tables, scheduled queries, and alert policies
#
# Usage: ./setup_quota_alerts.sh [PROJECT_ID] [NOTIFICATION_CHANNEL_EMAIL]
#
# Prerequisites:
# - gcloud CLI installed and authenticated
# - bq CLI installed
# - Appropriate permissions: bigquery.admin, monitoring.admin
#
# Example:
#   ./setup_quota_alerts.sh my-gcp-project projects/my-project/notificationChannels/123456

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ID="${1:-}"
NOTIFICATION_CHANNEL="${2:-}"
DATASET="nba_orchestration"
QUOTA_TABLE="quota_usage_hourly"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITORING_DIR="$(dirname "$SCRIPT_DIR")"

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_prerequisites() {
    log_info "Checking prerequisites..."

    if [[ -z "$PROJECT_ID" ]]; then
        log_error "PROJECT_ID not provided. Usage: $0 [PROJECT_ID] [NOTIFICATION_CHANNEL]"
        exit 1
    fi

    if [[ -z "$NOTIFICATION_CHANNEL" ]]; then
        log_warn "NOTIFICATION_CHANNEL not provided. Alert policies will be created without notifications."
        log_warn "You can add notification channels later in Cloud Console."
    fi

    # Check gcloud
    if ! command -v gcloud &> /dev/null; then
        log_error "gcloud CLI not found. Please install: https://cloud.google.com/sdk/install"
        exit 1
    fi

    # Check bq
    if ! command -v bq &> /dev/null; then
        log_error "bq CLI not found. Please install: https://cloud.google.com/bigquery/docs/bq-command-line-tool"
        exit 1
    fi

    # Set project
    gcloud config set project "$PROJECT_ID" --quiet
    log_info "Using project: $PROJECT_ID"
}

create_quota_table() {
    log_info "Creating BigQuery table: ${DATASET}.${QUOTA_TABLE}..."

    # Check if table already exists
    if bq show "${PROJECT_ID}:${DATASET}.${QUOTA_TABLE}" &> /dev/null; then
        log_warn "Table ${DATASET}.${QUOTA_TABLE} already exists. Skipping creation."
        return 0
    fi

    # Create table
    bq mk \
        --table \
        --project_id="$PROJECT_ID" \
        --description="Hourly quota usage tracking for pipeline event logging" \
        --time_partitioning_field=hour_timestamp \
        --time_partitioning_type=DAY \
        --label=purpose:monitoring \
        --label=component:pipeline_logger \
        "${DATASET}.${QUOTA_TABLE}" \
        hour_timestamp:TIMESTAMP,partition_modifications:INTEGER,events_logged:INTEGER,avg_batch_size:FLOAT,failed_flushes:INTEGER,unique_processors:INTEGER,unique_game_dates:INTEGER,error_events:INTEGER

    if [[ $? -eq 0 ]]; then
        log_info "Table created successfully!"
    else
        log_error "Failed to create table"
        return 1
    fi
}

create_scheduled_query() {
    log_info "Creating BigQuery scheduled query..."

    # Check if transfer already exists (by name)
    EXISTING_TRANSFER=$(bq ls --transfer_config --transfer_location=US --project_id="$PROJECT_ID" | grep "Pipeline Quota Usage Tracking" || true)

    if [[ -n "$EXISTING_TRANSFER" ]]; then
        log_warn "Scheduled query 'Pipeline Quota Usage Tracking' already exists. Skipping creation."
        log_warn "To update, delete the existing transfer and run this script again."
        return 0
    fi

    # Read query from file
    QUERY_FILE="${MONITORING_DIR}/queries/quota_usage_tracking.sql"
    if [[ ! -f "$QUERY_FILE" ]]; then
        log_error "Query file not found: $QUERY_FILE"
        return 1
    fi

    # Extract the main query (exclude comments and setup instructions)
    QUERY=$(sed -n '/^WITH hourly_events/,/ORDER BY es.hour_timestamp DESC;/p' "$QUERY_FILE")

    # Create transfer config
    bq mk \
        --transfer_config \
        --project_id="$PROJECT_ID" \
        --data_source=scheduled_query \
        --schedule='every 1 hours' \
        --display_name='Pipeline Quota Usage Tracking' \
        --target_dataset="$DATASET" \
        --params="{
            \"query\":\"$QUERY\",
            \"destination_table_name_template\":\"$QUOTA_TABLE\",
            \"write_disposition\":\"WRITE_APPEND\",
            \"partitioning_type\":\"DAY\"
        }"

    if [[ $? -eq 0 ]]; then
        log_info "Scheduled query created successfully!"
    else
        log_error "Failed to create scheduled query"
        return 1
    fi
}

create_log_metrics() {
    log_info "Creating log-based metrics..."

    # Note: Log-based metrics need to be created via Cloud Console or REST API
    # The gcloud CLI doesn't support creating log metrics directly
    log_warn "Log-based metrics must be created manually in Cloud Console."
    log_warn "See: ${MONITORING_DIR}/docs/quota_monitoring_setup.md (Part 3)"

    log_info "Metrics to create:"
    echo "  1. pipeline/events_buffered (Counter)"
    echo "  2. pipeline/batch_flushes (Counter)"
    echo "  3. pipeline/flush_latency_ms (Distribution)"
    echo "  4. pipeline/flush_failures (Counter)"
    echo ""
    log_info "After creating metrics, re-run alert policy creation."
}

create_alert_policies() {
    log_info "Creating alert policies..."

    if [[ -z "$NOTIFICATION_CHANNEL" ]]; then
        log_warn "Skipping alert policy creation (no notification channel provided)"
        log_warn "Run: gcloud alpha monitoring channels list --project=$PROJECT_ID"
        log_warn "Then re-run this script with the channel ID"
        return 0
    fi

    # Alert 1: High Quota Usage (80%)
    log_info "Creating alert: Pipeline Quota Usage Warning (80%)..."
    gcloud alpha monitoring policies create \
        --project="$PROJECT_ID" \
        --notification-channels="$NOTIFICATION_CHANNEL" \
        --display-name="Pipeline Quota Usage Warning" \
        --condition-display-name="Partition modifications > 80/hour" \
        --condition-threshold-value=80 \
        --condition-threshold-duration=300s \
        --condition-threshold-comparison=COMPARISON_GT \
        --condition-metric="custom.googleapis.com/bigquery/partition_modifications" \
        --condition-filter='resource.type="bigquery_table" AND resource.labels.table_id="pipeline_event_log"' \
        --documentation-content="Pipeline approaching quota limit. See monitoring/docs/quota_monitoring_setup.md" \
        || log_warn "Failed to create warning alert policy (may already exist)"

    # Alert 2: Critical Quota Usage (90%)
    log_info "Creating alert: Pipeline Quota Usage CRITICAL (90%)..."
    gcloud alpha monitoring policies create \
        --project="$PROJECT_ID" \
        --notification-channels="$NOTIFICATION_CHANNEL" \
        --display-name="Pipeline Quota Usage CRITICAL" \
        --condition-display-name="Partition modifications > 90/hour" \
        --condition-threshold-value=90 \
        --condition-threshold-duration=60s \
        --condition-threshold-comparison=COMPARISON_GT \
        --condition-metric="custom.googleapis.com/bigquery/partition_modifications" \
        --condition-filter='resource.type="bigquery_table" AND resource.labels.table_id="pipeline_event_log"' \
        --documentation-content="CRITICAL: Quota nearly exceeded. Immediate action required!" \
        || log_warn "Failed to create critical alert policy (may already exist)"

    # Alert 3: Failed Flushes
    log_info "Creating alert: Pipeline Event Buffer Flush Failures..."
    gcloud alpha monitoring policies create \
        --project="$PROJECT_ID" \
        --notification-channels="$NOTIFICATION_CHANNEL" \
        --display-name="Pipeline Event Buffer Flush Failures" \
        --condition-display-name="Flush failures > 0" \
        --condition-threshold-value=0 \
        --condition-threshold-duration=300s \
        --condition-threshold-comparison=COMPARISON_GT \
        --condition-metric="logging.googleapis.com/user/pipeline/flush_failures" \
        --condition-filter='resource.type="cloud_function"' \
        --documentation-content="Pipeline event buffer experiencing flush failures. Check logs." \
        || log_warn "Failed to create flush failures alert policy (may already exist)"

    log_info "Alert policies created (or already exist)!"
}

verify_setup() {
    log_info "Verifying setup..."

    # Check table exists
    if bq show "${PROJECT_ID}:${DATASET}.${QUOTA_TABLE}" &> /dev/null; then
        log_info "✓ BigQuery table exists: ${DATASET}.${QUOTA_TABLE}"
    else
        log_error "✗ BigQuery table not found: ${DATASET}.${QUOTA_TABLE}"
    fi

    # Check scheduled query
    TRANSFER_COUNT=$(bq ls --transfer_config --transfer_location=US --project_id="$PROJECT_ID" | grep "Pipeline Quota Usage Tracking" | wc -l)
    if [[ $TRANSFER_COUNT -gt 0 ]]; then
        log_info "✓ Scheduled query exists: Pipeline Quota Usage Tracking"
    else
        log_warn "✗ Scheduled query not found"
    fi

    # Check alert policies
    ALERT_COUNT=$(gcloud alpha monitoring policies list --project="$PROJECT_ID" --filter="displayName:'Pipeline Quota'" | grep "displayName:" | wc -l)
    if [[ $ALERT_COUNT -gt 0 ]]; then
        log_info "✓ Alert policies exist (count: $ALERT_COUNT)"
    else
        log_warn "✗ No alert policies found (may need notification channel)"
    fi

    log_info ""
    log_info "Setup verification complete!"
    log_info ""
    log_info "Next steps:"
    echo "  1. Create log-based metrics in Cloud Console (see docs)"
    echo "  2. Import dashboard: monitoring/dashboards/pipeline_quota_dashboard.json"
    echo "  3. Test alert policies by generating events"
    echo ""
    log_info "Documentation: ${MONITORING_DIR}/docs/quota_monitoring_setup.md"
}

# Main execution
main() {
    log_info "=== Pipeline Quota Usage Monitoring Setup ==="
    log_info ""

    check_prerequisites
    create_quota_table
    create_scheduled_query
    create_log_metrics
    create_alert_policies
    verify_setup

    log_info ""
    log_info "Setup complete!"
}

# Run main function
main
