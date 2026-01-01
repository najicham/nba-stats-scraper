#!/bin/bash
# Pipeline Health Check Script
# Monitors the prediction pipeline and alerts on failures
# Usage: ./check_pipeline_health.sh [date]

set -euo pipefail

# Configuration
PROJECT_ID="nba-props-platform"
REGION="us-west2"
DATE="${1:-TODAY}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
log_error() {
    echo -e "${RED}✗ ERROR: $1${NC}"
}

log_success() {
    echo -e "${GREEN}✓ SUCCESS: $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠ WARNING: $1${NC}"
}

log_info() {
    echo "ℹ INFO: $1"
}

# Function to get timestamp for queries (1 hour ago)
get_query_timestamp() {
    date -u -d '1 hour ago' '+%Y-%m-%dT%H:%M:%SZ'
}

# Function to check scheduler job status
check_scheduler() {
    local job_name="$1"
    log_info "Checking scheduler: $job_name"

    local status=$(gcloud scheduler jobs describe "$job_name" \
        --location="$REGION" \
        --format="value(status.lastAttemptTime,status.state)" 2>&1)

    if echo "$status" | grep -q "SUCCESS"; then
        log_success "Scheduler $job_name completed successfully"
        return 0
    elif echo "$status" | grep -q "FAILED"; then
        log_error "Scheduler $job_name failed!"
        return 1
    else
        log_warning "Scheduler $job_name status: $status"
        return 2
    fi
}

# Function to check prediction coordinator logs
check_predictions() {
    log_info "Checking prediction generation..."

    local timestamp=$(get_query_timestamp)

    # Check for batch loading
    local batch_logs=$(gcloud logging read \
        "resource.labels.service_name=\"prediction-coordinator\" AND \
         timestamp>=\"$timestamp\" AND \
         textPayload=~\"Batch loaded\"" \
        --limit=1 --format="value(textPayload)" 2>&1)

    if [ -n "$batch_logs" ]; then
        log_success "Batch loader ran: $batch_logs"
    else
        log_error "No batch loading detected in last hour"
        return 1
    fi

    # Check for worker completions
    local worker_logs=$(gcloud logging read \
        "resource.labels.service_name=\"prediction-worker\" AND \
         timestamp>=\"$timestamp\" AND \
         textPayload=~\"Successfully generated\"" \
        --limit=10 --format="value(textPayload)" 2>&1 | wc -l)

    if [ "$worker_logs" -gt 0 ]; then
        log_success "Workers generated predictions: $worker_logs completion events"
    else
        log_error "No worker completions detected"
        return 1
    fi

    return 0
}

# Function to check consolidation
check_consolidation() {
    log_info "Checking consolidation..."

    local timestamp=$(get_query_timestamp)

    # Check for consolidation errors
    local consolidation_errors=$(gcloud logging read \
        "resource.labels.service_name=\"prediction-coordinator\" AND \
         timestamp>=\"$timestamp\" AND \
         textPayload=~\"Consolidation failed\"" \
        --limit=1 --format="value(textPayload)" 2>&1)

    if [ -n "$consolidation_errors" ]; then
        log_error "Consolidation failed: $consolidation_errors"
        return 1
    fi

    # Check for successful consolidation (via staging table cleanup)
    local staging_cleanup=$(gcloud logging read \
        "resource.labels.service_name=\"prediction-coordinator\" AND \
         timestamp>=\"$timestamp\" AND \
         textPayload=~\"Cleaned up staging\"" \
        --limit=1 --format="value(textPayload)" 2>&1)

    if [ -n "$staging_cleanup" ]; then
        log_success "Consolidation completed: $staging_cleanup"
    else
        log_warning "No consolidation completion detected (may still be running)"
        return 2
    fi

    return 0
}

# Function to check Phase 6 export
check_phase6() {
    log_info "Checking Phase 6 export..."

    local timestamp=$(get_query_timestamp)

    # Check Phase 6 orchestrator
    local orchestrator_logs=$(gcloud logging read \
        "resource.labels.service_name=\"phase5-to-phase6-orchestrator\" AND \
         timestamp>=\"$timestamp\"" \
        --limit=5 --format="value(textPayload)" 2>&1)

    if echo "$orchestrator_logs" | grep -q "Skipping Phase 6"; then
        log_error "Phase 6 was skipped: $(echo "$orchestrator_logs" | grep "Skipping")"
        return 1
    fi

    # Check Phase 6 export completion
    local export_logs=$(gcloud logging read \
        "resource.labels.service_name=\"phase6-export\" AND \
         timestamp>=\"$timestamp\" AND \
         textPayload=~\"Export completed\"" \
        --limit=1 --format="value(textPayload)" 2>&1)

    if [ -n "$export_logs" ]; then
        log_success "Phase 6 export completed: $export_logs"
    else
        log_warning "No Phase 6 export completion detected"
        return 2
    fi

    return 0
}

# Function to check front-end data freshness
check_frontend_data() {
    log_info "Checking front-end data freshness..."

    # Get generated_at timestamp from all-players.json
    local generated_at=$(gsutil cat gs://nba-props-platform-api/v1/tonight/all-players.json 2>/dev/null | \
        jq -r '.generated_at' 2>/dev/null)

    if [ -z "$generated_at" ]; then
        log_error "Could not retrieve front-end data"
        return 1
    fi

    # Check if data is recent (within last 2 hours)
    local generated_epoch=$(date -d "$generated_at" +%s)
    local now_epoch=$(date +%s)
    local age_seconds=$((now_epoch - generated_epoch))
    local age_minutes=$((age_seconds / 60))

    if [ $age_minutes -lt 120 ]; then
        log_success "Front-end data is fresh ($age_minutes minutes old)"
        log_info "Generated at: $generated_at"
    else
        log_error "Front-end data is stale ($age_minutes minutes old)"
        return 1
    fi

    # Check player count
    local player_count=$(gsutil cat gs://nba-props-platform-api/v1/tonight/all-players.json 2>/dev/null | \
        jq -r '.total_with_lines' 2>/dev/null)

    if [ -n "$player_count" ] && [ "$player_count" -gt 0 ]; then
        log_success "Front-end has $player_count players with predictions"
    else
        log_error "Front-end has no players with predictions"
        return 1
    fi

    return 0
}

# Main execution
main() {
    echo "================================================"
    echo "  NBA Prediction Pipeline Health Check"
    echo "  Date: $(date)"
    echo "  Target: $DATE"
    echo "================================================"
    echo ""

    local exit_code=0

    # Check predictions
    if ! check_predictions; then
        exit_code=1
    fi
    echo ""

    # Check consolidation
    if ! check_consolidation; then
        exit_code=1
    fi
    echo ""

    # Check Phase 6
    if ! check_phase6; then
        exit_code=1
    fi
    echo ""

    # Check front-end data
    if ! check_frontend_data; then
        exit_code=1
    fi
    echo ""

    # Summary
    echo "================================================"
    if [ $exit_code -eq 0 ]; then
        log_success "Pipeline health check PASSED"
    else
        log_error "Pipeline health check FAILED"
    fi
    echo "================================================"

    return $exit_code
}

# Run main function
main "$@"
