#!/bin/bash
# check_morning_run.sh
#
# Health check script for morning prediction runs
# Verifies that the automatic 7 AM prediction batch completed successfully
#
# Usage:
#   ./bin/monitoring/check_morning_run.sh              # Check last 30 minutes
#   ./bin/monitoring/check_morning_run.sh 60           # Check last 60 minutes
#   ./bin/monitoring/check_morning_run.sh 120 verbose  # Check last 2 hours with details
#
# Exit codes:
#   0 - All checks passed
#   1 - Some checks failed (warnings)
#   2 - Critical failures detected

set -euo pipefail

# Configuration
FRESHNESS="${1:-30}"  # Default to last 30 minutes
VERBOSE="${2:-}"      # Set to "verbose" for detailed output
PROJECT_ID="nba-props-platform"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Counters
WARNINGS=0
ERRORS=0

# Helper functions
print_header() {
    echo -e "\n${BOLD}${BLUE}=== $1 ===${NC}"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
    ((WARNINGS++))
}

print_error() {
    echo -e "${RED}✗${NC} $1"
    ((ERRORS++))
}

print_info() {
    if [[ "$VERBOSE" == "verbose" ]]; then
        echo -e "${BLUE}ℹ${NC} $1"
    fi
}

# Main script
echo -e "${BOLD}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   Morning Prediction Run Health Check                     ║${NC}"
echo -e "${BOLD}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "Checking logs from last ${FRESHNESS} minutes..."
echo "Project: ${PROJECT_ID}"
echo ""

# Check 1: Batch Started
print_header "1. Batch Initialization"

BATCH_START=$(gcloud logging read \
    'resource.labels.service_name="prediction-coordinator"
     AND textPayload=~"🚀 Pre-loading"' \
    --limit=1 \
    --freshness="${FRESHNESS}m" \
    --format="value(timestamp,textPayload)" \
    --project="${PROJECT_ID}" 2>/dev/null || echo "")

if [[ -n "$BATCH_START" ]]; then
    print_success "Batch initialization detected"
    print_info "  $BATCH_START"
else
    print_warning "No batch initialization found in last ${FRESHNESS} minutes"
    print_info "  This may be normal if no games are scheduled"
fi

# Check 2: Completion Events
print_header "2. Worker Completions"

COMPLETION_COUNT=$(gcloud logging read \
    'resource.labels.service_name="prediction-coordinator"
     AND textPayload=~"📥 Completion"' \
    --limit=500 \
    --freshness="${FRESHNESS}m" \
    --format="value(textPayload)" \
    --project="${PROJECT_ID}" 2>/dev/null | wc -l)

if [[ "$COMPLETION_COUNT" -gt 0 ]]; then
    print_success "Received ${COMPLETION_COUNT} worker completion events"

    if [[ "$COMPLETION_COUNT" -lt 10 ]]; then
        print_warning "Low completion count - expected 30-200 for typical game day"
    fi
else
    print_warning "No completion events found"
fi

# Check 3: Batch Completion
print_header "3. Batch Completion"

BATCH_COMPLETE=$(gcloud logging read \
    'resource.labels.service_name="prediction-coordinator"
     AND textPayload=~"🎉 Batch.*complete"' \
    --limit=1 \
    --freshness="${FRESHNESS}m" \
    --format="value(timestamp,textPayload)" \
    --project="${PROJECT_ID}" 2>/dev/null || echo "")

if [[ -n "$BATCH_COMPLETE" ]]; then
    print_success "Batch completed successfully"
    print_info "  $BATCH_COMPLETE"

    # Extract batch ID
    BATCH_ID=$(echo "$BATCH_COMPLETE" | grep -oP 'batch_\d{4}-\d{2}-\d{2}_\d+' | head -1)
    if [[ -n "$BATCH_ID" ]]; then
        print_info "  Batch ID: $BATCH_ID"
    fi
else
    if [[ "$COMPLETION_COUNT" -gt 0 ]]; then
        print_warning "Workers completed but batch not marked complete (may still be running)"
    else
        print_info "No batch completion (normal if no games today)"
    fi
fi

# Check 4: Consolidation
print_header "4. Consolidation"

CONSOLIDATION=$(gcloud logging read \
    'resource.labels.service_name="prediction-coordinator"
     AND textPayload=~"✅ Consolidation SUCCESS"' \
    --limit=1 \
    --freshness="${FRESHNESS}m" \
    --format="value(timestamp,textPayload)" \
    --project="${PROJECT_ID}" 2>/dev/null || echo "")

if [[ -n "$CONSOLIDATION" ]]; then
    print_success "Consolidation completed successfully"
    print_info "  $CONSOLIDATION"

    # Extract row count
    ROWS=$(echo "$CONSOLIDATION" | grep -oP '\d+(?= rows merged)' || echo "unknown")
    TABLES=$(echo "$CONSOLIDATION" | grep -oP '\d+(?= staging tables)' || echo "unknown")
    print_info "  Merged: $ROWS rows from $TABLES tables"
else
    if [[ -n "$BATCH_COMPLETE" ]]; then
        print_error "Batch completed but consolidation not found"
    else
        print_info "No consolidation (normal if batch not complete)"
    fi
fi

# Check 5: MERGE Performance
print_header "5. MERGE Performance"

MERGE_STATS=$(gcloud logging read \
    'resource.labels.service_name="prediction-coordinator"
     AND textPayload=~"✅ MERGE complete"' \
    --limit=1 \
    --freshness="${FRESHNESS}m" \
    --format="value(textPayload)" \
    --project="${PROJECT_ID}" 2>/dev/null || echo "")

if [[ -n "$MERGE_STATS" ]]; then
    ROWS=$(echo "$MERGE_STATS" | grep -oP '\d+(?= rows affected)' || echo "0")
    DURATION=$(echo "$MERGE_STATS" | grep -oP '\d+\.\d+(?=ms)' || echo "unknown")

    if [[ "$ROWS" -gt 0 ]]; then
        print_success "MERGE executed: $ROWS rows in ${DURATION}ms"

        # Performance check
        if [[ "$DURATION" != "unknown" ]] && (( $(echo "$DURATION > 10000" | bc -l) )); then
            print_warning "MERGE took ${DURATION}ms (>10s) - performance degradation?"
        fi
    else
        print_error "MERGE returned 0 rows - potential data loss!"
    fi
else
    print_info "No MERGE statistics found"
fi

# Check 6: Phase 5 Publishing
print_header "6. Phase 5 Publishing"

PUBLISHING=$(gcloud logging read \
    'resource.labels.service_name="prediction-coordinator"
     AND textPayload=~"✅ Phase 5 completion published"' \
    --limit=1 \
    --freshness="${FRESHNESS}m" \
    --format="value(timestamp,textPayload)" \
    --project="${PROJECT_ID}" 2>/dev/null || echo "")

if [[ -n "$PUBLISHING" ]]; then
    print_success "Phase 5 completion published to Pub/Sub"
else
    if [[ -n "$CONSOLIDATION" ]]; then
        print_warning "Consolidation succeeded but publishing not detected"
    else
        print_info "No publishing events (normal if consolidation not run)"
    fi
fi

# Check 7: Errors
print_header "7. Error Detection"

ERRORS_FOUND=$(gcloud logging read \
    'resource.labels.service_name="prediction-coordinator"
     AND (textPayload=~"❌" OR severity>=ERROR)' \
    --limit=10 \
    --freshness="${FRESHNESS}m" \
    --format="value(timestamp,severity,textPayload)" \
    --project="${PROJECT_ID}" 2>/dev/null || echo "")

if [[ -z "$ERRORS_FOUND" ]]; then
    print_success "No errors detected"
else
    ERROR_COUNT=$(echo "$ERRORS_FOUND" | wc -l)
    print_error "Found $ERROR_COUNT error(s) in logs"

    if [[ "$VERBOSE" == "verbose" ]]; then
        echo -e "${RED}Error details:${NC}"
        echo "$ERRORS_FOUND" | head -5 | while IFS= read -r line; do
            echo "  $line"
        done
        if [[ "$ERROR_COUNT" -gt 5 ]]; then
            echo "  ... and $(($ERROR_COUNT - 5)) more"
        fi
    else
        echo "  Run with 'verbose' flag to see error details"
    fi
fi

# Check 8: BigQuery Verification
print_header "8. BigQuery Predictions"

echo "Querying BigQuery for predictions..."

BQ_RESULT=$(bq query \
    --use_legacy_sql=false \
    --format=csv \
    --project_id="${PROJECT_ID}" \
    "SELECT
       COUNT(*) as total_predictions,
       COUNT(DISTINCT player_lookup) as unique_players,
       FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', MAX(updated_at)) as latest_update
     FROM nba_predictions.player_prop_predictions
     WHERE DATE(updated_at) = CURRENT_DATE()
       AND updated_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL ${FRESHNESS} MINUTE)" 2>/dev/null || echo "")

if [[ -n "$BQ_RESULT" ]]; then
    # Parse CSV output (skip header)
    DATA=$(echo "$BQ_RESULT" | tail -n +2)
    PRED_COUNT=$(echo "$DATA" | cut -d',' -f1)
    PLAYER_COUNT=$(echo "$DATA" | cut -d',' -f2)
    LATEST=$(echo "$DATA" | cut -d',' -f3)

    if [[ "$PRED_COUNT" -gt 0 ]]; then
        print_success "Found $PRED_COUNT predictions for $PLAYER_COUNT players"
        print_info "  Latest update: $LATEST"

        if [[ "$PRED_COUNT" -lt 50 ]] && [[ "$COMPLETION_COUNT" -gt 30 ]]; then
            print_warning "Prediction count ($PRED_COUNT) lower than expected based on completions ($COMPLETION_COUNT)"
        fi
    else
        if [[ "$COMPLETION_COUNT" -gt 0 ]]; then
            print_error "No predictions in BigQuery despite $COMPLETION_COUNT completions"
        else
            print_info "No predictions today (normal if no games scheduled)"
        fi
    fi
else
    print_error "Failed to query BigQuery"
fi

# Check 9: Staging Table Cleanup
print_header "9. Staging Table Cleanup"

echo "Checking for orphaned staging tables (this may take a moment)..."

# Use a simpler, faster query approach
STAGING_COUNT=$(bq query --use_legacy_sql=false --format=csv --max_rows=1000 \
    "SELECT table_name FROM nba_predictions.INFORMATION_SCHEMA.TABLES
     WHERE table_name LIKE '_staging_batch_$(date +%Y_%m_%d)%'" 2>/dev/null | tail -n +2 | wc -l)

STAGING_COUNT=${STAGING_COUNT:-0}

if [[ "$STAGING_COUNT" -eq 0 ]]; then
    print_success "No orphaned staging tables from today"
else
    print_warning "Found $STAGING_COUNT staging tables from today still present"
    print_info "  This may indicate consolidation hasn't run yet or failed"
fi

# Check 10: Current Revision
print_header "10. Deployed Revision"

CURRENT_REVISION=$(gcloud run services describe prediction-coordinator --region=us-west2 --project="${PROJECT_ID}" --format="value(status.latestReadyRevisionName)" 2>/dev/null || echo "unknown")

EXPECTED_REVISION="prediction-coordinator-00031-97k"

if [[ "$CURRENT_REVISION" == "$EXPECTED_REVISION" ]]; then
    print_success "Running expected revision: $CURRENT_REVISION"
elif [[ "$CURRENT_REVISION" > "$EXPECTED_REVISION" ]]; then
    print_success "Running newer revision: $CURRENT_REVISION (expected: $EXPECTED_REVISION)"
else
    print_error "Running old revision: $CURRENT_REVISION (expected: $EXPECTED_REVISION or newer)"
    echo "  Redeploy latest with: gcloud run deploy prediction-coordinator --image=gcr.io/nba-props-platform/prediction-coordinator:logging-fix --region=us-west2"
fi

# Summary
print_header "Summary"

echo ""
if [[ $ERRORS -eq 0 ]] && [[ $WARNINGS -eq 0 ]]; then
    echo -e "${GREEN}${BOLD}✓ All checks passed! Pipeline is healthy.${NC}"
    EXIT_CODE=0
elif [[ $ERRORS -eq 0 ]]; then
    echo -e "${YELLOW}${BOLD}⚠ $WARNINGS warning(s) - Pipeline may need attention${NC}"
    EXIT_CODE=1
else
    echo -e "${RED}${BOLD}✗ $ERRORS error(s), $WARNINGS warning(s) - Investigation needed${NC}"
    EXIT_CODE=2
fi

echo ""
echo "Checks completed at $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo ""

# Recommendations
if [[ $ERRORS -gt 0 ]] || [[ $WARNINGS -gt 0 ]]; then
    echo -e "${BOLD}Recommendations:${NC}"

    if [[ "$COMPLETION_COUNT" -gt 0 ]] && [[ -z "$BATCH_COMPLETE" ]]; then
        echo "  • Batch may still be running - wait a few minutes and re-run"
    fi

    if [[ -n "$BATCH_COMPLETE" ]] && [[ -z "$CONSOLIDATION" ]]; then
        echo "  • Check Firestore batch state for completion status"
        echo "  • Consider manual consolidation trigger if needed"
    fi

    if [[ "$STAGING_COUNT" -gt 0 ]]; then
        echo "  • Check consolidation logs for failures"
        echo "  • Staging tables may contain un-merged predictions"
    fi

    if [[ -n "$ERRORS_FOUND" ]]; then
        echo "  • Review error logs with: gcloud logging read 'resource.labels.service_name=\"prediction-coordinator\" AND severity>=ERROR' --limit=20 --freshness=30m"
    fi

    echo ""
fi

exit $EXIT_CODE
