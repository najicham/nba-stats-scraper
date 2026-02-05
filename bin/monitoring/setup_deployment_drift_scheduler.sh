#!/bin/bash
# bin/monitoring/setup_deployment_drift_scheduler.sh
#
# Deploy deployment drift alerter as Cloud Run Job with Cloud Scheduler trigger
# Runs every 2 hours to detect stale deployments
#
# Usage:
#   ./bin/monitoring/setup_deployment_drift_scheduler.sh

set -e

PROJECT_ID="nba-props-platform"
REGION="us-west2"
JOB_NAME="nba-deployment-drift-alerter"
SCHEDULE="0 */2 * * *"  # Every 2 hours at :00

echo "=== Deploying Deployment Drift Alerter ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Job: $JOB_NAME"
echo "Schedule: Every 2 hours"
echo ""

# Build and deploy Cloud Run Job
echo "1. Building container..."
docker build -t gcr.io/$PROJECT_ID/$JOB_NAME:latest \
    -f- . <<'EOF'
FROM python:3.11-slim

# Install gcloud CLI (needed for deployment checks)
RUN apt-get update && \
    apt-get install -y curl gnupg git && \
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | \
    tee -a /etc/apt/sources.list.d/google-cloud-sdk.list && \
    curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | \
    apt-key --keyring /usr/share/keyrings/cloud.google.gpg add - && \
    apt-get update && \
    apt-get install -y google-cloud-sdk && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements
COPY shared/requirements.txt /app/shared/requirements.txt
RUN pip install --no-cache-dir -r shared/requirements.txt

# Copy code
COPY . /app/

# Set git safe directory
RUN git config --global --add safe.directory /app

CMD ["python", "bin/monitoring/deployment_drift_alerter.py"]
EOF

echo ""
echo "2. Pushing container..."
docker push gcr.io/$PROJECT_ID/$JOB_NAME:latest

echo ""
echo "3. Deploying Cloud Run Job..."
gcloud run jobs create $JOB_NAME \
    --image gcr.io/$PROJECT_ID/$JOB_NAME:latest \
    --region $REGION \
    --project $PROJECT_ID \
    --max-retries 3 \
    --task-timeout 10m \
    --set-env-vars "PROJECT_ID=$PROJECT_ID,REGION=$REGION" \
    --update-env-vars \
        SLACK_WEBHOOK_URL_DEPLOYMENT_ALERTS=$(gcloud secrets versions access latest --secret="slack-webhook-deployment-alerts" --project=$PROJECT_ID 2>/dev/null || echo "") \
    || echo "Job may already exist, updating..."

# Update if exists
gcloud run jobs update $JOB_NAME \
    --image gcr.io/$PROJECT_ID/$JOB_NAME:latest \
    --region $REGION \
    --project $PROJECT_ID \
    --update-env-vars \
        SLACK_WEBHOOK_URL_DEPLOYMENT_ALERTS=$(gcloud secrets versions access latest --secret="slack-webhook-deployment-alerts" --project=$PROJECT_ID 2>/dev/null || echo "") \
    2>/dev/null || true

echo ""
echo "4. Creating Cloud Scheduler job..."
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
echo "Scheduler will run every 2 hours: 12 AM, 2 AM, 4 AM, ..."
echo "Manual test: gcloud run jobs execute $JOB_NAME --region $REGION --project $PROJECT_ID"
echo "View logs: gcloud logging read \"resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME\" --limit 50 --project $PROJECT_ID"
