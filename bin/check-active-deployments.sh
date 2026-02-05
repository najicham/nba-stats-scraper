#!/bin/bash
# Check for active Cloud Build and deployment operations
# Usage: ./bin/check-active-deployments.sh [--watch]

set -euo pipefail

PROJECT="nba-props-platform"
REGION="us-west2"
WATCH_MODE=false

if [[ "${1:-}" == "--watch" ]]; then
    WATCH_MODE=true
fi

check_deployments() {
    echo "=== Active Deployments Check ==="
    echo "Time: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    echo ""

    # Check for ongoing Cloud Builds
    echo "--- Ongoing Cloud Builds ---"
    ONGOING_BUILDS=$(gcloud builds list --ongoing --format="table(id,status,createTime,tags)" --project="$PROJECT" 2>&1)

    if [[ -z "$ONGOING_BUILDS" ]] || [[ "$ONGOING_BUILDS" == *"Listed 0 items"* ]]; then
        echo "✅ No active builds"
    else
        echo "$ONGOING_BUILDS"
    fi
    echo ""

    # Check recent builds (last 5 minutes)
    echo "--- Recent Builds (last 5 min) ---"
    FIVE_MIN_AGO=$(date -u -d '5 minutes ago' '+%Y-%m-%dT%H:%M:%S' 2>/dev/null || date -u -v-5M '+%Y-%m-%dT%H:%M:%S' 2>/dev/null || echo "")

    if [[ -n "$FIVE_MIN_AGO" ]]; then
        RECENT_BUILDS=$(gcloud builds list \
            --filter="createTime>\"$FIVE_MIN_AGO\"" \
            --format="table(id,status,createTime,tags)" \
            --project="$PROJECT" 2>&1)

        if [[ -z "$RECENT_BUILDS" ]] || [[ "$RECENT_BUILDS" == *"Listed 0 items"* ]]; then
            echo "✅ No recent builds"
        else
            echo "$RECENT_BUILDS"
        fi
    else
        echo "⚠️  Could not calculate 5 minutes ago (date command incompatible)"
    fi
    echo ""

    # Check Cloud Run services being updated
    echo "--- Cloud Run Service Status ---"
    SERVICES=("prediction-worker" "prediction-coordinator" "nba-scrapers"
              "nba-phase2-processors" "nba-phase3-analytics-processors"
              "nba-phase4-precompute-processors")

    for service in "${SERVICES[@]}"; do
        # Get latest revision creation time
        LATEST_REV=$(gcloud run revisions list \
            --service="$service" \
            --region="$REGION" \
            --limit=1 \
            --format="value(metadata.name,metadata.creationTimestamp)" \
            --project="$PROJECT" 2>/dev/null || echo "")

        if [[ -n "$LATEST_REV" ]]; then
            REV_NAME=$(echo "$LATEST_REV" | awk '{print $1}')
            REV_TIME=$(echo "$LATEST_REV" | awk '{print $2}')

            # Check if revision is less than 5 minutes old
            REV_EPOCH=$(date -d "$REV_TIME" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%S" "$REV_TIME" +%s 2>/dev/null || echo "0")
            NOW_EPOCH=$(date +%s)
            AGE_SECONDS=$((NOW_EPOCH - REV_EPOCH))

            if [[ $AGE_SECONDS -lt 300 ]]; then
                echo "🚀 $service: NEW REVISION $REV_NAME (${AGE_SECONDS}s ago)"
            fi
        fi
    done
    echo ""
}

if [[ "$WATCH_MODE" == true ]]; then
    echo "👀 Watching for deployments (Ctrl+C to stop)..."
    echo ""
    while true; do
        check_deployments
        echo "Checking again in 10 seconds..."
        echo "---"
        sleep 10
    done
else
    check_deployments
fi
