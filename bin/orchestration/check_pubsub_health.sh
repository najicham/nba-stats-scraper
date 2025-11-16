#!/bin/bash

# bin/orchestration/check_pubsub_health.sh
#
# Pub/Sub Integration Health Check
#
# Comprehensive monitoring script for Phase 1 → Phase 2 Pub/Sub integration.
# Checks scrapers publishing, processors receiving, DLQ status, and end-to-end flow.
#
# Usage:
#   ./bin/orchestration/check_pubsub_health.sh [--detailed] [--last-N-hours=24]
#
# Options:
#   --detailed          Show detailed logs and message examples
#   --last-N-hours=N    Check last N hours (default: 1)
#   --test-scraper      Trigger test scraper execution to verify flow
#
# Exit codes:
#   0 - Healthy (all checks passed)
#   1 - Warning (some issues detected)
#   2 - Unhealthy (critical issues)

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

HOURS_BACK="${HOURS_BACK:-1}"
DETAILED="${DETAILED:-false}"
TEST_SCRAPER="${TEST_SCRAPER:-false}"

# Parse command line arguments
for arg in "$@"; do
    case $arg in
        --detailed)
            DETAILED=true
            shift
            ;;
        --last-N-hours=*)
            HOURS_BACK="${arg#*=}"
            shift
            ;;
        --test-scraper)
            TEST_SCRAPER=true
            shift
            ;;
        *)
            echo "Unknown option: $arg"
            echo "Usage: $0 [--detailed] [--last-N-hours=N] [--test-scraper]"
            exit 1
            ;;
    esac
done

# ============================================================================
# Helper Functions
# ============================================================================

print_header() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  $1"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

print_section() {
    echo ""
    echo "▶ $1"
    echo "─────────────────────────────────────────────────────────────────────"
}

print_status() {
    local status=$1
    local message=$2

    case $status in
        OK)
            echo "✅ $message"
            ;;
        WARNING)
            echo "⚠️  $message"
            ;;
        ERROR)
            echo "❌ $message"
            ;;
        INFO)
            echo "ℹ️  $message"
            ;;
    esac
}

# ============================================================================
# Main Health Checks
# ============================================================================

EXIT_CODE=0

print_header "Pub/Sub Integration Health Check"
echo "Checking last ${HOURS_BACK} hour(s) of activity..."
echo "Time: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"

# ----------------------------------------------------------------------------
# Check 1: Scrapers Publishing Events
# ----------------------------------------------------------------------------

print_section "1. Scrapers Publishing Pub/Sub Events"

# Count scrapers that published
SCRAPERS_PUBLISHED=$(gcloud logging read \
    "resource.labels.service_name=nba-scrapers AND textPayload:\"Published Pub/Sub event\"" \
    --limit=500 \
    --format=json \
    --freshness="${HOURS_BACK}h" 2>/dev/null \
    | jq -r '.[] | .textPayload' \
    | grep -oP '(?<=event: )[^ ]+' \
    | sort -u \
    | wc -l)

# Count total Pub/Sub events published
EVENTS_PUBLISHED=$(gcloud logging read \
    "resource.labels.service_name=nba-scrapers AND textPayload:\"Phase 2 notified\"" \
    --limit=500 \
    --format=json \
    --freshness="${HOURS_BACK}h" 2>/dev/null \
    | wc -l)

if [ "$EVENTS_PUBLISHED" -gt 0 ]; then
    print_status "OK" "Scrapers are publishing: ${EVENTS_PUBLISHED} events from ${SCRAPERS_PUBLISHED} unique scrapers"

    if [ "$DETAILED" = true ]; then
        echo ""
        echo "Recent publications:"
        gcloud logging read \
            "resource.labels.service_name=nba-scrapers AND textPayload:\"Published Pub/Sub event\"" \
            --limit=5 \
            --format="table(timestamp,textPayload)" \
            --freshness="${HOURS_BACK}h" 2>/dev/null | head -8
    fi
else
    print_status "WARNING" "No Pub/Sub events published in last ${HOURS_BACK} hour(s)"
    print_status "INFO" "This may be normal if no scrapers ran recently"
    EXIT_CODE=1
fi

# ----------------------------------------------------------------------------
# Check 2: Processors Receiving Events
# ----------------------------------------------------------------------------

print_section "2. Processors Receiving Pub/Sub Events"

# Count processor messages received
MESSAGES_RECEIVED=$(gcloud logging read \
    "resource.labels.service_name=nba-processors AND textPayload:\"Processing Scraper Completion\"" \
    --limit=500 \
    --format=json \
    --freshness="${HOURS_BACK}h" 2>/dev/null \
    | wc -l)

if [ "$MESSAGES_RECEIVED" -gt 0 ]; then
    print_status "OK" "Processors receiving events: ${MESSAGES_RECEIVED} messages processed"

    # Check ratio of published vs received
    if [ "$EVENTS_PUBLISHED" -gt 0 ]; then
        RATIO=$((MESSAGES_RECEIVED * 100 / EVENTS_PUBLISHED))
        if [ "$RATIO" -lt 90 ]; then
            print_status "WARNING" "Message loss detected: ${RATIO}% delivery rate (${MESSAGES_RECEIVED}/${EVENTS_PUBLISHED})"
            EXIT_CODE=1
        else
            print_status "OK" "Delivery rate: ${RATIO}% (${MESSAGES_RECEIVED}/${EVENTS_PUBLISHED})"
        fi
    fi

    if [ "$DETAILED" = true ]; then
        echo ""
        echo "Recent processor activity:"
        gcloud logging read \
            "resource.labels.service_name=nba-processors AND textPayload:\"Processing Scraper Completion\"" \
            --limit=5 \
            --format="table(timestamp,textPayload)" \
            --freshness="${HOURS_BACK}h" 2>/dev/null | head -8
    fi
else
    if [ "$EVENTS_PUBLISHED" -gt 0 ]; then
        print_status "ERROR" "Processors not receiving events (${EVENTS_PUBLISHED} published but 0 received)"
        EXIT_CODE=2
    else
        print_status "INFO" "No events to process (scrapers not publishing)"
    fi
fi

# ----------------------------------------------------------------------------
# Check 3: Data Loading to BigQuery
# ----------------------------------------------------------------------------

print_section "3. Data Loading to BigQuery"

# Check if any data was actually loaded (not just no_data events)
DATA_LOADS=$(gcloud logging read \
    "resource.labels.service_name=nba-processors AND textPayload:\"Successfully loaded\"" \
    --limit=100 \
    --format=json \
    --freshness="${HOURS_BACK}h" 2>/dev/null \
    | wc -l)

if [ "$DATA_LOADS" -gt 0 ]; then
    print_status "OK" "Data being loaded to BigQuery: ${DATA_LOADS} successful loads"

    if [ "$DETAILED" = true ]; then
        echo ""
        echo "Recent data loads:"
        gcloud logging read \
            "resource.labels.service_name=nba-processors AND textPayload:\"Successfully loaded\"" \
            --limit=5 \
            --format="table(timestamp,textPayload)" \
            --freshness="${HOURS_BACK}h" 2>/dev/null | head -8
    fi
else
    # Check if this is due to no_data events
    NO_DATA_SKIPS=$(gcloud logging read \
        "resource.labels.service_name=nba-processors AND textPayload:\"Skipping processing\" AND textPayload:\"status=no_data\"" \
        --limit=100 \
        --format=json \
        --freshness="${HOURS_BACK}h" 2>/dev/null \
        | wc -l)

    if [ "$NO_DATA_SKIPS" -gt 0 ]; then
        print_status "INFO" "No data loads (${NO_DATA_SKIPS} no_data events skipped - expected during offseason)"
    else
        print_status "WARNING" "No data loads and no no_data events - check scraper executions"
        EXIT_CODE=1
    fi
fi

# ----------------------------------------------------------------------------
# Check 4: Error Detection
# ----------------------------------------------------------------------------

print_section "4. Error Detection"

# Check for processor errors
PROCESSOR_ERRORS=$(gcloud logging read \
    "resource.labels.service_name=nba-processors AND severity>=ERROR" \
    --limit=100 \
    --format=json \
    --freshness="${HOURS_BACK}h" 2>/dev/null \
    | wc -l)

if [ "$PROCESSOR_ERRORS" -eq 0 ]; then
    print_status "OK" "No processor errors detected"
else
    print_status "ERROR" "${PROCESSOR_ERRORS} processor errors detected in last ${HOURS_BACK} hour(s)"
    EXIT_CODE=2

    echo ""
    echo "Recent errors:"
    gcloud logging read \
        "resource.labels.service_name=nba-processors AND severity>=ERROR" \
        --limit=3 \
        --format="table(timestamp,severity,textPayload)" \
        --freshness="${HOURS_BACK}h" 2>/dev/null | head -8
fi

# Check for schema errors specifically
SCHEMA_ERRORS=$(gcloud logging read \
    "resource.labels.service_name=nba-processors AND textPayload:\"Missing required field\"" \
    --limit=100 \
    --format=json \
    --freshness="${HOURS_BACK}h" 2>/dev/null \
    | wc -l)

if [ "$SCHEMA_ERRORS" -gt 0 ]; then
    print_status "ERROR" "Schema mismatch errors detected: ${SCHEMA_ERRORS} events"
    print_status "INFO" "See docs/orchestration/pubsub-schema-management-2025-11-14.md for remediation"
    EXIT_CODE=2
fi

# ----------------------------------------------------------------------------
# Check 5: Dead Letter Queue Status
# ----------------------------------------------------------------------------

print_section "5. Dead Letter Queue (DLQ) Status"

DLQ_MESSAGES=$(gcloud pubsub subscriptions describe nba-scraper-complete-dlq-sub \
    --format="value(numUndeliveredMessages)" 2>/dev/null || echo "0")

if [ "$DLQ_MESSAGES" = "0" ] || [ -z "$DLQ_MESSAGES" ]; then
    print_status "OK" "DLQ is empty (no failed messages)"
else
    print_status "WARNING" "${DLQ_MESSAGES} messages in Dead Letter Queue"
    print_status "INFO" "Failed messages detected - check processor errors above"
    print_status "INFO" "After fixing issues, purge DLQ: gcloud pubsub subscriptions seek nba-scraper-complete-dlq-sub --time=\$(date -u --iso-8601=seconds)"
    EXIT_CODE=1
fi

# ----------------------------------------------------------------------------
# Check 6: Infrastructure Status
# ----------------------------------------------------------------------------

print_section "6. Infrastructure Status"

# Check Pub/Sub subscription
SUBSCRIPTION_STATE=$(gcloud pubsub subscriptions describe nba-processors-sub \
    --format="value(state)" 2>/dev/null || echo "UNKNOWN")

if [ "$SUBSCRIPTION_STATE" = "ACTIVE" ]; then
    print_status "OK" "Pub/Sub subscription is ACTIVE"
else
    print_status "ERROR" "Pub/Sub subscription state: ${SUBSCRIPTION_STATE}"
    EXIT_CODE=2
fi

# Check Cloud Run services
SCRAPER_REVISION=$(gcloud run services describe nba-scrapers --platform=managed \
    --format="value(status.latestCreatedRevisionName)" 2>/dev/null || echo "UNKNOWN")
PROCESSOR_REVISION=$(gcloud run services describe nba-processors --platform=managed \
    --format="value(status.latestCreatedRevisionName)" 2>/dev/null || echo "UNKNOWN")

print_status "INFO" "Scraper revision: ${SCRAPER_REVISION}"
print_status "INFO" "Processor revision: ${PROCESSOR_REVISION}"

if [[ "$SCRAPER_REVISION" < "nba-scrapers-00073" ]]; then
    print_status "WARNING" "Scraper revision is old (Pub/Sub code added in 00073)"
    EXIT_CODE=1
fi

# ----------------------------------------------------------------------------
# Check 7: Coverage Analysis
# ----------------------------------------------------------------------------

print_section "7. Scraper Coverage Analysis"

# Get scrapers that ran
SCRAPERS_RAN=$(mktemp)
bq query --use_legacy_sql=false --format=csv --quiet \
    "SELECT DISTINCT scraper_name FROM \`nba-props-platform.nba_orchestration.scraper_execution_log\`
     WHERE TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), triggered_at, HOUR) <= ${HOURS_BACK}
     ORDER BY scraper_name" 2>/dev/null | tail -n +2 > "$SCRAPERS_RAN" || echo "" > "$SCRAPERS_RAN"

RAN_COUNT=$(wc -l < "$SCRAPERS_RAN")

if [ "$RAN_COUNT" -gt 0 ]; then
    print_status "INFO" "${RAN_COUNT} unique scrapers executed in last ${HOURS_BACK} hour(s)"
    print_status "INFO" "${SCRAPERS_PUBLISHED} unique scrapers published Pub/Sub events"

    # Calculate coverage
    if [ "$SCRAPERS_PUBLISHED" -eq "$RAN_COUNT" ]; then
        print_status "OK" "100% Pub/Sub coverage (all scrapers publishing)"
    elif [ "$SCRAPERS_PUBLISHED" -gt 0 ]; then
        COVERAGE=$((SCRAPERS_PUBLISHED * 100 / RAN_COUNT))
        print_status "WARNING" "${COVERAGE}% Pub/Sub coverage (${SCRAPERS_PUBLISHED}/${RAN_COUNT} scrapers)"

        if [ "$DETAILED" = true ]; then
            # Show which scrapers didn't publish
            SCRAPERS_PUBLISHED_FILE=$(mktemp)
            gcloud logging read \
                "resource.labels.service_name=nba-scrapers AND textPayload:\"Published Pub/Sub event\"" \
                --limit=500 \
                --format=json \
                --freshness="${HOURS_BACK}h" 2>/dev/null \
                | jq -r '.[] | .textPayload' \
                | grep -oP '(?<=event: )[^ ]+' \
                | sort -u > "$SCRAPERS_PUBLISHED_FILE" || echo "" > "$SCRAPERS_PUBLISHED_FILE"

            MISSING=$(comm -23 "$SCRAPERS_RAN" "$SCRAPERS_PUBLISHED_FILE")
            if [ -n "$MISSING" ]; then
                echo ""
                echo "Scrapers that ran but didn't publish:"
                echo "$MISSING"
            fi

            rm "$SCRAPERS_PUBLISHED_FILE"
        fi

        EXIT_CODE=1
    fi
else
    print_status "INFO" "No scrapers executed in last ${HOURS_BACK} hour(s)"
fi

rm "$SCRAPERS_RAN"

# ----------------------------------------------------------------------------
# Optional: Test Scraper Execution
# ----------------------------------------------------------------------------

if [ "$TEST_SCRAPER" = true ]; then
    print_section "8. Test Scraper Execution"

    echo "Triggering test scraper (nbac_schedule_api)..."
    TEST_RESPONSE=$(curl -s -X POST https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape \
        -H "Content-Type: application/json" \
        -d '{"scraper": "nbac_schedule_api", "sport": "basketball", "season": "2025", "group": "prod"}')

    RUN_ID=$(echo "$TEST_RESPONSE" | jq -r '.run_id // "FAILED"')

    if [ "$RUN_ID" != "FAILED" ]; then
        print_status "OK" "Test scraper executed (run_id: ${RUN_ID})"

        # Wait for Pub/Sub event
        echo "Waiting for Pub/Sub event..."
        sleep 3

        # Check if event was published
        PUB_CHECK=$(gcloud logging read \
            "resource.labels.service_name=nba-scrapers AND textPayload:\"${RUN_ID}\" AND textPayload:\"Phase 2 notified\"" \
            --limit=1 \
            --format=json \
            --freshness=2m 2>/dev/null | jq '. | length')

        if [ "$PUB_CHECK" -gt 0 ]; then
            print_status "OK" "Pub/Sub event published"
        else
            print_status "WARNING" "Pub/Sub event not found in logs (may be delayed)"
        fi

        # Check if processor received it
        PROC_CHECK=$(gcloud logging read \
            "resource.labels.service_name=nba-processors AND textPayload:\"nbac_schedule_api\"" \
            --limit=1 \
            --format=json \
            --freshness=2m 2>/dev/null | jq '. | length')

        if [ "$PROC_CHECK" -gt 0 ]; then
            print_status "OK" "Processor received event"
        else
            print_status "WARNING" "Processor event not found in logs (may be delayed)"
        fi
    else
        print_status "ERROR" "Test scraper execution failed"
        echo "Response: $TEST_RESPONSE"
        EXIT_CODE=2
    fi
fi

# ============================================================================
# Summary
# ============================================================================

print_header "Health Check Summary"

case $EXIT_CODE in
    0)
        print_status "OK" "All Pub/Sub integration checks passed ✅"
        echo ""
        echo "System is healthy. Scrapers are publishing, processors are receiving,"
        echo "and the integration is working as expected."
        ;;
    1)
        print_status "WARNING" "Some issues detected ⚠️"
        echo ""
        echo "The system is mostly working but has some warnings."
        echo "Review the checks above for details."
        ;;
    2)
        print_status "ERROR" "Critical issues detected ❌"
        echo ""
        echo "The Pub/Sub integration has critical issues that need attention."
        echo "Review the errors above and see docs/orchestration/pubsub-integration-verification-guide.md"
        ;;
esac

echo ""
echo "For more details, run with --detailed flag"
echo "To test end-to-end flow, run with --test-scraper flag"
echo ""
echo "Related documentation:"
echo "  - docs/orchestration/pubsub-integration-verification-guide.md"
echo "  - docs/orchestration/pubsub-schema-management-2025-11-14.md"
echo ""

exit $EXIT_CODE
