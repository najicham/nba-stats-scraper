#!/bin/bash
# Monitor a running process and detect completion
# Usage: monitor_process.sh <PID> <timeout_hours>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../validation/common_validation.sh"

PID=$1
TIMEOUT_HOURS=${2:-8}

if [[ -z "$PID" ]]; then
    log_error "Usage: $0 <PID> [timeout_hours]"
    exit 1
fi

# Check if process exists
if ! kill -0 "$PID" 2>/dev/null; then
    log_error "Process $PID is not running"
    exit 1
fi

log_info "Monitoring process PID $PID (timeout: ${TIMEOUT_HOURS}h)"

# Calculate timeout timestamp
TIMEOUT_SECONDS=$((TIMEOUT_HOURS * 3600))
START_TIME=$(date +%s)
TIMEOUT_TIME=$((START_TIME + TIMEOUT_SECONDS))

# Monitor loop
while true; do
    CURRENT_TIME=$(date +%s)

    # Check if process is still running
    if ! kill -0 "$PID" 2>/dev/null; then
        # Process has exited - get exit code
        wait "$PID" 2>/dev/null
        EXIT_CODE=$?

        ELAPSED=$((CURRENT_TIME - START_TIME))
        DURATION=$(format_duration $ELAPSED)

        if [[ $EXIT_CODE -eq 0 ]]; then
            log_success "Process $PID completed successfully after $DURATION"
            echo "EXIT_CODE=0"
            exit 0
        else
            log_error "Process $PID failed with exit code $EXIT_CODE after $DURATION"
            echo "EXIT_CODE=$EXIT_CODE"
            exit 1
        fi
    fi

    # Check for timeout
    if [[ $CURRENT_TIME -gt $TIMEOUT_TIME ]]; then
        ELAPSED=$((CURRENT_TIME - START_TIME))
        DURATION=$(format_duration $ELAPSED)

        log_error "Process $PID exceeded timeout (${TIMEOUT_HOURS}h, ran for $DURATION)"
        echo "EXIT_CODE=124"  # Timeout exit code
        exit 124
    fi

    # Still running - wait before next check
    sleep 5
done
