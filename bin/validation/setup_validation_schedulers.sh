#!/bin/bash
# File: bin/validation/setup_validation_schedulers.sh
# Purpose: Set up Cloud Scheduler jobs for automated validation
# Usage: ./bin/validation/setup_validation_schedulers.sh [--delete] [--list]

set -euo pipefail

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"
REGION="${REGION:-us-west2}"
SCHEDULER_LOCATION="${SCHEDULER_LOCATION:-us-west2}"
SERVICE_ACCOUNT="${SCHEDULER_SA:-scheduler@${PROJECT_ID}.iam.gserviceaccount.com}"

# Validation job configuration
VALIDATION_JOB="validation-runner"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_header() {
    echo -e "${CYAN}========================================"
    echo -e "Validation Scheduler Setup"
    echo -e "========================================${NC}"
    echo -e "Project:  ${PROJECT_ID}"
    echo -e "Region:   ${REGION}"
    echo -e "Location: ${SCHEDULER_LOCATION}"
    echo ""
}

show_usage() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  setup      - Create/update scheduler jobs (default)"
    echo "  delete     - Delete all validation scheduler jobs"
    echo "  list       - List existing validation scheduler jobs"
    echo "  status     - Show scheduler job status"
    echo ""
    echo "Options:"
    echo "  --dry-run  - Show what would be done without executing"
    echo ""
    echo "Scheduled Jobs:"
    echo "  validation-daily      - Daily validation at 6 AM PT"
    echo "  validation-weekly     - Weekly full validation on Sundays at 2 AM PT"
}

# Create or update a scheduler job
create_scheduler_job() {
    local job_name="$1"
    local schedule="$2"
    local description="$3"
    local job_args="$4"

    echo -e "${BLUE}Setting up scheduler: ${job_name}${NC}"
    echo -e "  Schedule: ${schedule}"
    echo -e "  Description: ${description}"

    # Check if job exists
    if gcloud scheduler jobs describe "${job_name}" \
        --location="${SCHEDULER_LOCATION}" \
        --project="${PROJECT_ID}" >/dev/null 2>&1; then
        echo -e "  ${YELLOW}Updating existing job...${NC}"

        gcloud scheduler jobs update http "${job_name}" \
            --location="${SCHEDULER_LOCATION}" \
            --project="${PROJECT_ID}" \
            --schedule="${schedule}" \
            --time-zone="America/Los_Angeles" \
            --description="${description}" \
            --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${VALIDATION_JOB}:run" \
            --http-method=POST \
            --oauth-service-account-email="${SERVICE_ACCOUNT}" \
            --headers="Content-Type=application/json" \
            --message-body="{\"overrides\":{\"containerOverrides\":[{\"args\":[${job_args}]}]}}" \
            --quiet
    else
        echo -e "  ${GREEN}Creating new job...${NC}"

        gcloud scheduler jobs create http "${job_name}" \
            --location="${SCHEDULER_LOCATION}" \
            --project="${PROJECT_ID}" \
            --schedule="${schedule}" \
            --time-zone="America/Los_Angeles" \
            --description="${description}" \
            --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${VALIDATION_JOB}:run" \
            --http-method=POST \
            --oauth-service-account-email="${SERVICE_ACCOUNT}" \
            --headers="Content-Type=application/json" \
            --message-body="{\"overrides\":{\"containerOverrides\":[{\"args\":[${job_args}]}]}}" \
            --quiet
    fi

    echo -e "  ${GREEN}Done${NC}"
    echo ""
}

# Setup all scheduler jobs
cmd_setup() {
    print_header
    echo -e "${BLUE}Setting up validation schedulers...${NC}"
    echo ""

    # Daily quick validation at 6 AM PT
    create_scheduler_job \
        "validation-daily" \
        "0 6 * * *" \
        "Daily pipeline validation check" \
        "\"quick\""

    # Weekly full validation on Sunday at 2 AM PT
    create_scheduler_job \
        "validation-weekly" \
        "0 2 * * 0" \
        "Weekly full pipeline validation" \
        "\"all\""

    echo -e "${GREEN}========================================"
    echo -e "Scheduler Setup Complete!"
    echo -e "========================================${NC}"
    echo ""
    echo "Scheduled jobs:"
    gcloud scheduler jobs list \
        --location="${SCHEDULER_LOCATION}" \
        --project="${PROJECT_ID}" \
        --filter="name:validation" \
        --format="table(name, schedule, state, lastAttemptTime.date())"
}

# Delete scheduler jobs
cmd_delete() {
    print_header
    echo -e "${YELLOW}Deleting validation schedulers...${NC}"
    echo ""

    for job in "validation-daily" "validation-weekly"; do
        echo -e "Deleting ${job}..."
        gcloud scheduler jobs delete "${job}" \
            --location="${SCHEDULER_LOCATION}" \
            --project="${PROJECT_ID}" \
            --quiet 2>/dev/null || echo -e "  ${YELLOW}Job not found${NC}"
    done

    echo ""
    echo -e "${GREEN}Deletion complete${NC}"
}

# List scheduler jobs
cmd_list() {
    print_header
    echo -e "${BLUE}Validation Scheduler Jobs:${NC}"
    echo ""

    gcloud scheduler jobs list \
        --location="${SCHEDULER_LOCATION}" \
        --project="${PROJECT_ID}" \
        --filter="name:validation" \
        --format="table(name, schedule, state, timeZone, lastAttemptTime.date())"
}

# Show status of scheduler jobs
cmd_status() {
    print_header
    echo -e "${BLUE}Scheduler Job Status:${NC}"
    echo ""

    for job in "validation-daily" "validation-weekly"; do
        echo -e "${CYAN}${job}:${NC}"
        if gcloud scheduler jobs describe "${job}" \
            --location="${SCHEDULER_LOCATION}" \
            --project="${PROJECT_ID}" \
            --format="yaml(state, schedule, timeZone, lastAttemptTime, scheduleTime)" 2>/dev/null; then
            echo ""
        else
            echo -e "  ${YELLOW}Not found${NC}"
            echo ""
        fi
    done
}

# Main command handling
case "${1:-setup}" in
    "setup")
        cmd_setup
        ;;
    "delete"|"--delete")
        cmd_delete
        ;;
    "list"|"--list")
        cmd_list
        ;;
    "status")
        cmd_status
        ;;
    "help"|"-h"|"--help")
        show_usage
        ;;
    "--dry-run")
        echo -e "${YELLOW}DRY RUN - Would set up:${NC}"
        echo "  1. validation-daily: 0 6 * * * (6 AM PT daily)"
        echo "  2. validation-weekly: 0 2 * * 0 (2 AM PT Sundays)"
        ;;
    *)
        echo "Unknown command: $1"
        show_usage
        exit 1
        ;;
esac
