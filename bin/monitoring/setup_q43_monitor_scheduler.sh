#!/bin/bash
# bin/monitoring/setup_q43_monitor_scheduler.sh
#
# Deploy Q43 Performance Monitor as Cloud Run Job with Cloud Scheduler trigger
# Runs daily at 8 AM ET (after overnight grading completes)
#
# Usage:
#   ./bin/monitoring/setup_q43_monitor_scheduler.sh

set -e

PROJECT_ID="nba-props-platform"
REGION="us-west2"
JOB_NAME="nba-q43-performance-monitor"
SCHEDULE="0 8 * * *"  # 8:00 AM ET daily

echo "=== Deploying Q43 Performance Monitor ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Job: $JOB_NAME"
echo "Schedule: Daily at 8:00 AM ET"
echo ""

# Build and deploy Cloud Run Job
echo "1. Building container..."
docker build -t gcr.io/$PROJECT_ID/$JOB_NAME:latest \
    -f- . <<'DOCKERFILE'
FROM python:3.11-slim

WORKDIR /app

# Copy shared requirements and install
COPY shared/requirements.txt /app/shared/requirements.txt
RUN pip install --no-cache-dir -r shared/requirements.txt

# Install BigQuery client (if not in shared requirements)
RUN pip install --no-cache-dir google-cloud-bigquery requests

# Copy project code
COPY . /app/

ENV PYTHONPATH=/app

CMD ["python", "bin/monitoring/q43_performance_monitor.py", "--slack", "--days", "7"]
DOCKERFILE

echo ""
echo "2. Pushing container..."
docker push gcr.io/$PROJECT_ID/$JOB_NAME:latest

echo ""
echo "3. Deploying Cloud Run Job..."
gcloud run jobs create $JOB_NAME \
    --image gcr.io/$PROJECT_ID/$JOB_NAME:latest \
    --region $REGION \
    --project $PROJECT_ID \
    --max-retries 2 \
    --task-timeout 5m \
    --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID" \
    --update-env-vars \
        SLACK_WEBHOOK_URL_WARNING=$(gcloud secrets versions access latest --secret="slack-webhook-warning" --project=$PROJECT_ID 2>/dev/null || echo "") \
    || echo "Job may already exist, updating..."

# Update if exists
gcloud run jobs update $JOB_NAME \
    --image gcr.io/$PROJECT_ID/$JOB_NAME:latest \
    --region $REGION \
    --project $PROJECT_ID \
    --update-env-vars \
        SLACK_WEBHOOK_URL_WARNING=$(gcloud secrets versions access latest --secret="slack-webhook-warning" --project=$PROJECT_ID 2>/dev/null || echo "") \
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
echo "Deployment complete!"
echo ""
echo "Schedule: Daily at 8:00 AM ET"
echo "Alerts: #nba-alerts Slack channel"
echo ""
echo "Manual test:"
echo "  gcloud run jobs execute $JOB_NAME --region $REGION --project $PROJECT_ID"
echo ""
echo "Local test:"
echo "  PYTHONPATH=. python bin/monitoring/q43_performance_monitor.py"
echo "  PYTHONPATH=. python bin/monitoring/q43_performance_monitor.py --slack --days 7"
echo ""
echo "View logs:"
echo "  gcloud logging read \"resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME\" --limit 50 --project $PROJECT_ID"
