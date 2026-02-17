#!/bin/bash
# ==============================================================================
# Setup Retrain Reminder Infrastructure
# ==============================================================================
#
# Creates the Cloud Build trigger and Cloud Scheduler job for the
# retrain-reminder Cloud Function.
#
# Components:
#   1. Cloud Build trigger - auto-deploys CF on push to main
#   2. Cloud Scheduler job - runs every Monday at 9 AM ET
#
# The CF runs weekly and alerts if any model is >= 7 days old,
# matching the 7-day retrain cadence (Session 284: +$7,670 P&L).
# Urgency: ROUTINE (7-10d), OVERDUE (11-14d), URGENT (15d+).
#
# Prerequisites:
#   - gcloud CLI authenticated with nba-props-platform project
#   - Repository connection exists (same as other CF triggers)
#   - retrain-reminder CF already deployed (or will be deployed by trigger)
#
# Usage:
#   ./bin/infrastructure/setup_retrain_reminder.sh
#   ./bin/infrastructure/setup_retrain_reminder.sh --dry-run
#
# Created: 2026-02-16 (Session 272)
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
echo -e "${BLUE}Setup Retrain Reminder Infrastructure${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# ==============================================================================
# 1. Cloud Build Trigger (auto-deploy on push to main)
# ==============================================================================
TRIGGER_NAME="deploy-retrain-reminder"
FUNCTION_NAME="retrain-reminder"
ENTRY_POINT="main"
SOURCE_DIR="orchestration/cloud_functions/retrain_reminder"
MEMORY="512Mi"
TIMEOUT="120s"
INCLUDED_FILES="${SOURCE_DIR}/**,shared/**"

echo -e "${YELLOW}[1/2] Creating Cloud Build trigger: ${TRIGGER_NAME}${NC}"
echo "  Function:    ${FUNCTION_NAME}"
echo "  Entry point: ${ENTRY_POINT}"
echo "  Source dir:  ${SOURCE_DIR}"
echo "  Memory:      ${MEMORY}"
echo "  Timeout:     ${TIMEOUT}"
echo "  Watches:     ${INCLUDED_FILES}"
echo ""

# Check if trigger already exists
if gcloud builds triggers describe "${TRIGGER_NAME}" \
    --project="${PROJECT_ID}" --region="${REGION}" &>/dev/null; then
    echo -e "${YELLOW}  Trigger '${TRIGGER_NAME}' already exists, skipping.${NC}"
else
    CMD_TRIGGER=(
        gcloud builds triggers create github
        --name="${TRIGGER_NAME}"
        --repository="${REPO}"
        --branch-pattern="^main$"
        --build-config="${BUILD_CONFIG}"
        --included-files="${INCLUDED_FILES}"
        --description="Auto-deploy retrain-reminder Cloud Function on push to main"
        --service-account="${SERVICE_ACCOUNT}"
        --region="${REGION}"
        --project="${PROJECT_ID}"
        --substitutions="_FUNCTION_NAME=${FUNCTION_NAME},_ENTRY_POINT=${ENTRY_POINT},_SOURCE_DIR=${SOURCE_DIR},_TRIGGER_TYPE=http,_ALLOW_UNAUTHENTICATED=true,_MEMORY=${MEMORY},_TIMEOUT=${TIMEOUT}"
    )

    if [[ "${DRY_RUN}" == "true" ]]; then
        echo "  Would run:"
        echo "    ${CMD_TRIGGER[*]}"
    else
        if "${CMD_TRIGGER[@]}"; then
            echo -e "${GREEN}  Cloud Build trigger created successfully.${NC}"
        else
            echo -e "${RED}  FAILED to create Cloud Build trigger.${NC}"
            exit 1
        fi
    fi
fi
echo ""

# ==============================================================================
# 2. Cloud Scheduler Job (every Monday 9 AM ET)
# ==============================================================================
SCHEDULER_NAME="retrain-reminder-weekly"
SCHEDULE="0 9 * * 1"  # Every Monday at 9 AM
TIMEZONE="America/New_York"
CF_URL="https://${REGION}-${PROJECT_ID}.cloudfunctions.net/${FUNCTION_NAME}"

echo -e "${YELLOW}[2/2] Creating Cloud Scheduler job: ${SCHEDULER_NAME}${NC}"
echo "  Schedule:  ${SCHEDULE} (${TIMEZONE})"
echo "  Target:    ${CF_URL}"
echo ""

# Check if scheduler job already exists
if gcloud scheduler jobs describe "${SCHEDULER_NAME}" \
    --project="${PROJECT_ID}" --location="${REGION}" &>/dev/null; then
    echo -e "${YELLOW}  Scheduler job '${SCHEDULER_NAME}' already exists, skipping.${NC}"
    echo "  To update: gcloud scheduler jobs update http ${SCHEDULER_NAME} --schedule='${SCHEDULE}' --location=${REGION} --project=${PROJECT_ID}"
else
    CMD_SCHEDULER=(
        gcloud scheduler jobs create http "${SCHEDULER_NAME}"
        --schedule="${SCHEDULE}"
        --time-zone="${TIMEZONE}"
        --uri="${CF_URL}"
        --http-method=POST
        --location="${REGION}"
        --project="${PROJECT_ID}"
        --attempt-deadline=180s
    )

    if [[ "${DRY_RUN}" == "true" ]]; then
        echo "  Would run:"
        echo "    ${CMD_SCHEDULER[*]}"
    else
        if "${CMD_SCHEDULER[@]}"; then
            echo -e "${GREEN}  Cloud Scheduler job created successfully.${NC}"
        else
            echo -e "${RED}  FAILED to create Cloud Scheduler job.${NC}"
            exit 1
        fi
    fi
fi
echo ""

# ==============================================================================
# Summary
# ==============================================================================
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
if [[ "${DRY_RUN}" == "true" ]]; then
    echo -e "${YELLOW}DRY RUN complete. No resources were created.${NC}"
    echo "Run without --dry-run to create resources."
else
    echo -e "${GREEN}Retrain reminder infrastructure created.${NC}"
fi
echo ""
echo "How it works:"
echo "  - Cloud Scheduler fires every Monday 9 AM ET"
echo "  - CF checks model age via model_registry"
echo "  - If model >= 7 days old: sends Slack + SMS alert"
echo "  - If model < 7 days old: skips (recently retrained)"
echo ""
echo "Env vars needed on the CF (set via GCP Console or gcloud):"
echo "  SLACK_WEBHOOK_URL_ALERTS  - Slack webhook for #nba-alerts"
echo "  PUSHOVER_USER_KEY         - Pushover user key"
echo "  PUSHOVER_APP_TOKEN        - Pushover application API token"
echo ""
echo "Verify with:"
echo "  gcloud builds triggers list --project=${PROJECT_ID} --region=${REGION} --format='table(name)' | grep retrain"
echo "  gcloud scheduler jobs list --project=${PROJECT_ID} --location=${REGION} | grep retrain"
echo ""
echo "Test the CF:"
echo "  curl -X POST ${CF_URL}"
echo ""
