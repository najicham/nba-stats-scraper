#!/bin/bash
# ==============================================================================
# Create Cloud Build Auto-Deploy Triggers for Monitoring/Validation Cloud Functions
# ==============================================================================
#
# These Cloud Functions previously lacked auto-deploy triggers, meaning they
# would get stale after code changes were pushed to main. This script creates
# triggers that watch each function's source directory + shared/ and auto-deploy
# on push to main using the shared cloudbuild-functions.yaml template.
#
# Functions covered:
#   1. transition-monitor        - Phase transition health monitoring
#   2. pipeline-health-summary   - Daily pipeline health email summary
#   3. nba-grading-alerts        - Grading coverage/accuracy Slack alerts
#   4. live-freshness-monitor    - Live game data freshness monitoring
#   5. self-heal-predictions     - Auto-heal stalled/missing predictions
#   6. grading-readiness-monitor - Monitors grading readiness after games
#
# All use cloudbuild-functions.yaml (shared Cloud Function deploy template).
# All are HTTP-triggered Cloud Functions invoked by Cloud Scheduler.
#
# Prerequisites:
#   - gcloud CLI authenticated with nba-props-platform project
#   - Repository connection exists:
#     projects/nba-props-platform/locations/us-west2/connections/nba-github-connection/repositories/nba-stats-scraper
#   - Service account: github-actions-deploy@nba-props-platform.iam.gserviceaccount.com
#
# Usage:
#   ./bin/infrastructure/create_monitoring_function_triggers.sh
#   ./bin/infrastructure/create_monitoring_function_triggers.sh --dry-run
#
# Created: 2026-02-12 (Session 220)
# ==============================================================================

set -euo pipefail

# Configuration
PROJECT_ID="nba-props-platform"
REGION="us-west2"
REPO="projects/${PROJECT_ID}/locations/${REGION}/connections/nba-github-connection/repositories/nba-stats-scraper"
SERVICE_ACCOUNT="projects/${PROJECT_ID}/serviceAccounts/github-actions-deploy@${PROJECT_ID}.iam.gserviceaccount.com"
BUILD_CONFIG="cloudbuild-functions.yaml"
DRY_RUN=false

if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "=== DRY RUN MODE - Commands will be printed but not executed ==="
    echo ""
fi

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Create Monitoring Function Deploy Triggers${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# ==============================================================================
# Helper function to create a Cloud Build trigger
# ==============================================================================
create_function_trigger() {
    local trigger_name=$1
    local function_name=$2
    local entry_point=$3
    local source_dir=$4
    local description=$5
    local memory=${6:-512Mi}
    local timeout=${7:-300s}
    # Extra included files beyond source_dir/** and shared/**
    local extra_includes=${8:-}

    echo -e "${YELLOW}Creating trigger: ${trigger_name}${NC}"
    echo "  Function:    ${function_name}"
    echo "  Entry point: ${entry_point}"
    echo "  Source dir:   ${source_dir}"
    echo "  Memory:       ${memory}"
    echo "  Timeout:      ${timeout}"

    # Build included files list
    local included_files="${source_dir}/**,shared/**"
    if [[ -n "${extra_includes}" ]]; then
        included_files="${included_files},${extra_includes}"
    fi
    echo "  Watches:      ${included_files}"

    # Check if trigger already exists
    if gcloud builds triggers describe "${trigger_name}" \
        --project="${PROJECT_ID}" --region="${REGION}" &>/dev/null; then
        echo -e "${YELLOW}  Trigger '${trigger_name}' already exists, skipping.${NC}"
        echo ""
        return 0
    fi

    local cmd=(
        gcloud builds triggers create github
        --name="${trigger_name}"
        --repository="${REPO}"
        --branch-pattern="^main$"
        --build-config="${BUILD_CONFIG}"
        --included-files="${included_files}"
        --description="${description}"
        --service-account="${SERVICE_ACCOUNT}"
        --region="${REGION}"
        --project="${PROJECT_ID}"
        --substitutions="_FUNCTION_NAME=${function_name},_ENTRY_POINT=${entry_point},_SOURCE_DIR=${source_dir},_TRIGGER_TYPE=http,_ALLOW_UNAUTHENTICATED=true,_MEMORY=${memory},_TIMEOUT=${timeout}"
    )

    if [[ "${DRY_RUN}" == "true" ]]; then
        echo ""
        echo "  Would run:"
        echo "    ${cmd[*]}"
    else
        if "${cmd[@]}"; then
            echo -e "${GREEN}  Created successfully.${NC}"
        else
            echo -e "${RED}  FAILED to create trigger.${NC}"
            return 1
        fi
    fi
    echo ""
}

# ==============================================================================
# Create triggers for all 6 monitoring/validation Cloud Functions
# ==============================================================================

# 1. transition-monitor
#    Monitors phase transitions, detects stalls, sends alerts
create_function_trigger \
    "deploy-transition-monitor" \
    "transition-monitor" \
    "monitor_transitions" \
    "orchestration/cloud_functions/transition_monitor" \
    "Auto-deploy transition-monitor Cloud Function on push to main" \
    "512Mi" \
    "300s"

# 2. pipeline-health-summary
#    Generates daily pipeline health email summary via AWS SES
create_function_trigger \
    "deploy-pipeline-health-summary" \
    "pipeline-health-summary" \
    "pipeline_health_summary" \
    "monitoring/health_summary" \
    "Auto-deploy pipeline-health-summary Cloud Function on push to main" \
    "512Mi" \
    "300s"

# 3. nba-grading-alerts
#    Monitors grading coverage/accuracy, sends Slack alerts
create_function_trigger \
    "deploy-nba-grading-alerts" \
    "nba-grading-alerts" \
    "main" \
    "services/nba_grading_alerts" \
    "Auto-deploy nba-grading-alerts Cloud Function on push to main" \
    "512Mi" \
    "300s"

# 4. live-freshness-monitor
#    Monitors live game data freshness during active games
create_function_trigger \
    "deploy-live-freshness-monitor" \
    "live-freshness-monitor" \
    "main" \
    "orchestration/cloud_functions/live_freshness_monitor" \
    "Auto-deploy live-freshness-monitor Cloud Function on push to main" \
    "512Mi" \
    "300s"

# 5. self-heal-predictions
#    Auto-heals stalled/missing predictions, triggers backfills
create_function_trigger \
    "deploy-self-heal-predictions" \
    "self-heal-predictions" \
    "self_heal_check" \
    "orchestration/cloud_functions/self_heal" \
    "Auto-deploy self-heal-predictions Cloud Function on push to main" \
    "512Mi" \
    "540s"

# 6. grading-readiness-monitor
#    Monitors post-game grading readiness, triggers grading when ready
create_function_trigger \
    "deploy-grading-readiness-monitor" \
    "grading-readiness-monitor" \
    "main" \
    "orchestration/cloud_functions/grading_readiness_monitor" \
    "Auto-deploy grading-readiness-monitor Cloud Function on push to main" \
    "512Mi" \
    "300s"

# ==============================================================================
# Summary
# ==============================================================================
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
if [[ "${DRY_RUN}" == "true" ]]; then
    echo -e "${YELLOW}DRY RUN complete. No triggers were created.${NC}"
    echo "Run without --dry-run to create triggers."
else
    echo -e "${GREEN}All monitoring function triggers created.${NC}"
fi
echo ""
echo "These triggers will auto-deploy on push to main when files change in:"
echo "  - Each function's source directory"
echo "  - shared/ (shared utilities used by all functions)"
echo ""
echo "Verify with:"
echo "  gcloud builds triggers list --project=${PROJECT_ID} --region=${REGION} --format='table(name)' | grep deploy-"
echo ""
