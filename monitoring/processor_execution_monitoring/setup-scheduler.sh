#!/bin/bash
# File: monitoring/processor_execution_monitoring/setup-scheduler.sh
# Configure Cloud Scheduler for Processor Execution Monitor

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/job-config.env"

echo "========================================="
echo "Processor Execution Monitor - Cloud Scheduler Setup"
echo "========================================="
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Job Name: ${JOB_NAME}"
echo ""

# Hourly during business hours (simpler than season detection)
SCHEDULE="0 * * * *"

echo "Schedule: ${SCHEDULE} (Hourly)"
echo ""

# Create Cloud Scheduler job name
SCHEDULER_JOB_NAME="${JOB_NAME}-scheduler"

# Check if scheduler job already exists
if gcloud scheduler jobs describe "${SCHEDULER_JOB_NAME}" \
    --location="${REGION}" \
    --project="${PROJECT_ID}" &>/dev/null; then
    
    echo "Scheduler job '${SCHEDULER_JOB_NAME}' already exists."
    read -p "Do you want to update it? (y/n) " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Updating existing scheduler job..."
        
        gcloud scheduler jobs update http "${SCHEDULER_JOB_NAME}" \
            --location="${REGION}" \
            --project="${PROJECT_ID}" \
            --schedule="${SCHEDULE}" \
            --time-zone="America/Los_Angeles" \
            --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
            --http-method=POST \
            --oauth-service-account-email="${SERVICE_ACCOUNT}"
        
        echo ""
        echo "Scheduler job updated successfully!"
    else
        echo "Keeping existing scheduler job unchanged."
        exit 0
    fi
else
    echo "Creating new scheduler job..."
    
    gcloud scheduler jobs create http "${SCHEDULER_JOB_NAME}" \
        --location="${REGION}" \
        --project="${PROJECT_ID}" \
        --schedule="${SCHEDULE}" \
        --time-zone="America/Los_Angeles" \
        --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
        --http-method=POST \
        --oauth-service-account-email="${SERVICE_ACCOUNT}" \
        --description="Automated processor execution monitoring"
    
    echo ""
    echo "Scheduler job created successfully!"
fi

echo ""
echo "========================================="
echo "Scheduler Configuration Complete"
echo "========================================="
echo ""
echo "Job Name: ${SCHEDULER_JOB_NAME}"
echo "Schedule: ${SCHEDULE} (Hourly)"
echo "Time Zone: America/Los_Angeles (PT)"
echo ""
echo "Next scheduled run:"
gcloud scheduler jobs describe "${SCHEDULER_JOB_NAME}" \
    --location="${REGION}" \
    --project="${PROJECT_ID}" \
    --format="value(schedule)" | xargs -I {} echo "  {}"
echo ""
echo "Manual operations:"
echo "  Trigger now:    gcloud scheduler jobs run ${SCHEDULER_JOB_NAME} --location=${REGION}"
echo "  Pause:          gcloud scheduler jobs pause ${SCHEDULER_JOB_NAME} --location=${REGION}"
echo "  Resume:         gcloud scheduler jobs resume ${SCHEDULER_JOB_NAME} --location=${REGION}"
echo "  View logs:      gcloud logging read \"resource.type=cloud_scheduler_job\" --limit=20"
echo ""