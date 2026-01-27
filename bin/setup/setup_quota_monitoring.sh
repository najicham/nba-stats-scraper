#!/bin/bash
#
# Setup BigQuery Quota Monitoring
#
# Creates:
#   1. BigQuery table: nba_orchestration.quota_usage_log
#   2. Cloud Scheduler job: bigquery-quota-monitor (runs hourly)
#
# Usage:
#   ./bin/setup/setup_quota_monitoring.sh
#

set -e

PROJECT_ID="nba-props-platform"
REGION="us-west2"
DATASET="nba_orchestration"
TABLE="quota_usage_log"
SCHEDULER_JOB="bigquery-quota-monitor"

echo "================================================"
echo "Setting up BigQuery Quota Monitoring"
echo "================================================"
echo ""

# 1. Create BigQuery table
echo "1. Creating BigQuery table ${DATASET}.${TABLE}..."
bq mk \
  --table \
  --project_id="${PROJECT_ID}" \
  --time_partitioning_field=check_timestamp \
  --time_partitioning_type=DAY \
  --time_partitioning_expiration=7776000 \
  --description="Quota usage monitoring log - tracks BigQuery load jobs per table per day" \
  "${DATASET}.${TABLE}" \
  schemas/nba_orchestration/quota_usage_log.json \
  || echo "Table already exists (OK)"

echo "✅ Table created"
echo ""

# 2. Create Cloud Scheduler job (runs hourly)
echo "2. Creating Cloud Scheduler job ${SCHEDULER_JOB}..."
gcloud scheduler jobs create http "${SCHEDULER_JOB}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --schedule="0 * * * *" \
  --uri="https://us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/quota-monitor:run" \
  --http-method=POST \
  --description="Run BigQuery quota monitoring hourly" \
  --time-zone="America/Los_Angeles" \
  --attempt-deadline="10m" \
  --max-retry-attempts=2 \
  --oidc-service-account-email="nba-orchestrator@${PROJECT_ID}.iam.gserviceaccount.com" \
  || gcloud scheduler jobs update http "${SCHEDULER_JOB}" \
     --project="${PROJECT_ID}" \
     --location="${REGION}" \
     --schedule="0 * * * *" \
     --description="Run BigQuery quota monitoring hourly"

echo "✅ Scheduler job created/updated"
echo ""

# 3. Create Cloud Run Job for quota monitoring
echo "3. Creating Cloud Run Job for quota monitoring..."
gcloud run jobs create quota-monitor \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --image="gcr.io/${PROJECT_ID}/nba-orchestrator:latest" \
  --command="python" \
  --args="monitoring/bigquery_quota_monitor.py" \
  --set-env-vars="PROJECT_ID=${PROJECT_ID}" \
  --service-account="nba-orchestrator@${PROJECT_ID}.iam.gserviceaccount.com" \
  --max-retries=2 \
  --task-timeout=600 \
  --memory=512Mi \
  --cpu=1 \
  || gcloud run jobs update quota-monitor \
     --project="${PROJECT_ID}" \
     --region="${REGION}" \
     --image="gcr.io/${PROJECT_ID}/nba-orchestrator:latest"

echo "✅ Cloud Run Job created/updated"
echo ""

echo "================================================"
echo "Setup Complete!"
echo "================================================"
echo ""
echo "Next steps:"
echo "  1. Test the monitoring:"
echo "     python monitoring/bigquery_quota_monitor.py --dry-run"
echo ""
echo "  2. Trigger manually:"
echo "     gcloud scheduler jobs run ${SCHEDULER_JOB} --project=${PROJECT_ID} --location=${REGION}"
echo ""
echo "  3. View logs:"
echo "     gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=quota-monitor' --limit=50"
echo ""
echo "  4. Query usage history:"
echo "     bq query --use_legacy_sql=false 'SELECT * FROM nba_orchestration.quota_usage_log ORDER BY check_timestamp DESC LIMIT 10'"
echo ""
