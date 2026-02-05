#!/bin/bash
# bin/monitoring/setup_auto_batch_cleanup.sh
#
# Deploy automated batch cleanup as Cloud Run Job with Cloud Scheduler trigger
# Runs every 15 minutes to detect and heal stalled prediction batches
#
# Usage:
#   ./bin/monitoring/setup_auto_batch_cleanup.sh

set -e

PROJECT_ID="nba-props-platform"
REGION="us-west2"
JOB_NAME="nba-auto-batch-cleanup"
SCHEDULE="*/15 * * * *"  # Every 15 minutes

echo "=== Deploying Automated Batch Cleanup ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Job: $JOB_NAME"
echo "Schedule: Every 15 minutes"
echo ""

# Create BigQuery table for healing events
echo "1. Creating BigQuery table for healing events..."
bq mk --table \
    --project_id=$PROJECT_ID \
    --description="Self-healing event audit trail (Session 135)" \
    nba_orchestration.healing_events \
    schemas/nba_orchestration/healing_events.json \
    || echo "Table may already exist"

echo ""

# Build and deploy Cloud Run Job
echo "2. Building container..."
docker build -t gcr.io/$PROJECT_ID/$JOB_NAME:latest \
    -f- . <<'EOF'
FROM python:3.11-slim

WORKDIR /app

# Copy requirements
COPY shared/requirements.txt /app/shared/requirements.txt
RUN pip install --no-cache-dir -r shared/requirements.txt

# Install additional dependencies
RUN pip install --no-cache-dir google-cloud-firestore google-cloud-bigquery

# Copy code
COPY . /app/

CMD ["python", "bin/monitoring/auto_batch_cleanup.py"]
EOF

echo ""
echo "3. Pushing container..."
docker push gcr.io/$PROJECT_ID/$JOB_NAME:latest

echo ""
echo "4. Deploying Cloud Run Job..."
gcloud run jobs create $JOB_NAME \
    --image gcr.io/$PROJECT_ID/$JOB_NAME:latest \
    --region $REGION \
    --project $PROJECT_ID \
    --max-retries 3 \
    --task-timeout 10m \
    --set-env-vars "PROJECT_ID=$PROJECT_ID" \
    --update-env-vars \
        SLACK_WEBHOOK_URL=$(gcloud secrets versions access latest --secret="slack-webhook-url" --project=$PROJECT_ID 2>/dev/null || echo "") \
    || echo "Job may already exist, updating..."

# Update if exists
gcloud run jobs update $JOB_NAME \
    --image gcr.io/$PROJECT_ID/$JOB_NAME:latest \
    --region $REGION \
    --project $PROJECT_ID \
    --update-env-vars \
        SLACK_WEBHOOK_URL=$(gcloud secrets versions access latest --secret="slack-webhook-url" --project=$PROJECT_ID 2>/dev/null || echo "") \
    2>/dev/null || true

echo ""
echo "5. Creating Cloud Scheduler job..."
gcloud scheduler jobs create http ${JOB_NAME}-trigger \
    --location $REGION \
    --schedule "$SCHEDULE" \
    --uri "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
    --http-method POST \
    --oauth-service-account-email ${PROJECT_ID}@appspot.gserviceaccount.com \
    --time-zone "America/New_York" \
    --project $PROJECT_ID \
    || echo "Scheduler job may already exist, updating..."

# Update if exists
gcloud scheduler jobs update http ${JOB_NAME}-trigger \
    --location $REGION \
    --schedule "$SCHEDULE" \
    --uri "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
    --time-zone "America/New_York" \
    --project $PROJECT_ID \
    2>/dev/null || true

echo ""
echo "✓ Deployment complete!"
echo ""
echo "Scheduler will run every 15 minutes"
echo "Manual test: gcloud run jobs execute $JOB_NAME --region $REGION --project $PROJECT_ID"
echo "View logs: gcloud logging read \"resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME\" --limit 50 --project $PROJECT_ID"
echo ""
echo "Healing events will be tracked in:"
echo "- Firestore: prediction_batches collection (auto_completed flag)"
echo "- Firestore: healing_events collection (full audit trail)"
echo "- BigQuery: nba_orchestration.healing_events (analytics)"
