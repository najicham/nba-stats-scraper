#!/bin/bash

# Setup Environment Variable Monitoring for NBA Prediction Worker
#
# This script creates:
# 1. Cloud Scheduler job to check env vars every 5 minutes
# 2. Log-based metric to detect env var changes
# 3. Alert policy to fire when changes detected
#
# Usage:
#   ./setup_env_monitoring.sh [PROJECT_ID] [ENVIRONMENT]
#
# Arguments:
#   PROJECT_ID: GCP project ID (default: nba-props-platform)
#   ENVIRONMENT: dev|staging|prod (default: prod)
#

set -euo pipefail

# Configuration
PROJECT_ID="${1:-nba-props-platform}"
ENVIRONMENT="${2:-prod}"
REGION="us-west2"

# Service configuration
if [ "$ENVIRONMENT" = "prod" ]; then
    SERVICE_NAME="prediction-worker"
    SERVICE_URL="https://prediction-worker-<SERVICE_ID>-uc.a.run.app"  # Will be updated
elif [ "$ENVIRONMENT" = "staging" ]; then
    SERVICE_NAME="prediction-worker-staging"
    SERVICE_URL="https://prediction-worker-staging-<SERVICE_ID>-uc.a.run.app"
else
    SERVICE_NAME="prediction-worker-dev"
    SERVICE_URL="https://prediction-worker-dev-<SERVICE_ID>-uc.a.run.app"
fi

# Scheduler configuration
SCHEDULER_JOB_NAME="nba-env-var-check-${ENVIRONMENT}"
CHECK_FREQUENCY="*/5 * * * *"  # Every 5 minutes

# Alert configuration
METRIC_NAME="nba_env_var_changes"
ALERT_NAME="[WARNING] NBA Environment Variable Changes"
SLACK_CHANNEL_ID=$(gcloud alpha monitoring channels list \
    --project="$PROJECT_ID" \
    --filter='displayName="Slack - #platform-team"' \
    --format='value(name)' \
    --limit=1)

echo "=========================================="
echo "Setup NBA Environment Variable Monitoring"
echo "=========================================="
echo "Project: $PROJECT_ID"
echo "Environment: $ENVIRONMENT"
echo "Service: $SERVICE_NAME"
echo "Region: $REGION"
echo ""

# Step 1: Get actual Cloud Run service URL
echo "Step 1: Getting Cloud Run service URL..."
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --format='value(status.url)')

if [ -z "$SERVICE_URL" ]; then
    echo "❌ ERROR: Service $SERVICE_NAME not found in $PROJECT_ID"
    exit 1
fi

echo "✓ Service URL: $SERVICE_URL"
echo ""

# Step 2: Create Cloud Scheduler job
echo "Step 2: Creating Cloud Scheduler job..."
CHECK_URL="${SERVICE_URL}/internal/check-env"

# Check if job already exists
if gcloud scheduler jobs describe "$SCHEDULER_JOB_NAME" \
    --project="$PROJECT_ID" \
    --location="$REGION" &>/dev/null; then
    echo "⚠️  Job $SCHEDULER_JOB_NAME already exists - skipping creation"
    echo "    Job is already configured and running"
else
    echo "Creating new scheduler job..."
    gcloud scheduler jobs create http "$SCHEDULER_JOB_NAME" \
        --project="$PROJECT_ID" \
        --location="$REGION" \
        --schedule="$CHECK_FREQUENCY" \
        --uri="$CHECK_URL" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --oidc-service-account-email="${SERVICE_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
        --oidc-token-audience="$CHECK_URL" \
        --time-zone="America/New_York" \
        --attempt-deadline=60s \
        --description="Check NBA prediction worker environment variables every 5 minutes"
fi

echo "✓ Cloud Scheduler job created: $SCHEDULER_JOB_NAME"
echo "  Schedule: Every 5 minutes"
echo "  Endpoint: $CHECK_URL"
echo ""

# Step 3: Create log-based metric
echo "Step 3: Creating log-based metric..."

# Check if metric already exists
if gcloud logging metrics describe "$METRIC_NAME" --project="$PROJECT_ID" &>/dev/null; then
    echo "⚠️  Metric $METRIC_NAME already exists - updating..."
    gcloud logging metrics update "$METRIC_NAME" \
        --project="$PROJECT_ID" \
        --description="Detects NBA environment variable changes" \
        --log-filter='
resource.type="cloud_run_revision"
resource.labels.service_name="'"$SERVICE_NAME"'"
jsonPayload.alert_type="ENV_VAR_CHANGE"
severity="ERROR"
'
else
    echo "Creating new log-based metric..."
    gcloud logging metrics create "$METRIC_NAME" \
        --project="$PROJECT_ID" \
        --description="Detects NBA environment variable changes" \
        --log-filter='
resource.type="cloud_run_revision"
resource.labels.service_name="'"$SERVICE_NAME"'"
jsonPayload.alert_type="ENV_VAR_CHANGE"
severity="ERROR"
'
fi

echo "✓ Log-based metric created: $METRIC_NAME"
echo ""

# Step 4: Create alert policy
echo "Step 4: Creating alert policy..."

# Check if Slack channel exists
if [ -z "$SLACK_CHANNEL_ID" ]; then
    echo "⚠️  WARNING: Slack notification channel not found"
    echo "    Create one manually or alerts will only go to Cloud Monitoring"
    NOTIFICATION_CHANNELS=""
else
    echo "✓ Found Slack channel: $SLACK_CHANNEL_ID"
    NOTIFICATION_CHANNELS="--notification-channels=$SLACK_CHANNEL_ID"
fi

# Check if alert already exists
EXISTING_ALERT=$(gcloud alpha monitoring policies list \
    --project="$PROJECT_ID" \
    --filter="displayName='$ALERT_NAME'" \
    --format='value(name)' \
    --limit=1)

if [ -n "$EXISTING_ALERT" ]; then
    echo "⚠️  Alert policy already exists: $ALERT_NAME"
    echo "    To update, delete and re-run: gcloud alpha monitoring policies delete $EXISTING_ALERT"
else
    cat > /tmp/env_var_alert_policy.yaml <<EOF
displayName: "$ALERT_NAME"
documentation:
  content: |
    ## Environment Variable Change Detected

    One or more critical environment variables changed unexpectedly outside of a deployment window.

    **Critical Variables Monitored:**
    - XGBOOST_V1_MODEL_PATH
    - CATBOOST_V8_MODEL_PATH
    - NBA_ACTIVE_SYSTEMS
    - NBA_MIN_CONFIDENCE
    - NBA_MIN_EDGE

    **Investigation Steps:**
    1. Check recent deployments: Was this expected?
    2. Review the alert log for which variables changed
    3. Verify current env vars match expected configuration
    4. Check if predictions are still working correctly

    **To Fix:**
    - If change was intentional: No action needed (baseline updated automatically)
    - If change was accidental: Restore correct values and redeploy
    - If during deployment: Call /internal/deployment-started endpoint BEFORE deploying

    **Related Runbook:** docs/04-deployment/ALERT-RUNBOOKS.md (Week 2 section)
  mimeType: text/markdown
conditions:
  - displayName: "Environment variable changes"
    conditionThreshold:
      aggregations:
        - alignmentPeriod: 300s
          perSeriesAligner: ALIGN_RATE
      comparison: COMPARISON_GT
      duration: 0s
      filter: |
        resource.type = "cloud_run_revision"
        resource.labels.service_name = "$SERVICE_NAME"
        metric.type = "logging.googleapis.com/user/$METRIC_NAME"
      thresholdValue: 0
      trigger:
        count: 1
combiner: OR
enabled: true
alertStrategy:
  autoClose: 3600s
EOF

    gcloud alpha monitoring policies create \
        --project="$PROJECT_ID" \
        --policy-from-file=/tmp/env_var_alert_policy.yaml \
        $NOTIFICATION_CHANNELS

    rm /tmp/env_var_alert_policy.yaml

    echo "✓ Alert policy created: $ALERT_NAME"
fi

echo ""
echo "=========================================="
echo "✓ Environment Monitoring Setup Complete!"
echo "=========================================="
echo ""
echo "Next Steps:"
echo "1. Deploy updated prediction-worker with env_monitor.py"
echo "2. Test the scheduler job:"
echo "   gcloud scheduler jobs run $SCHEDULER_JOB_NAME --project=$PROJECT_ID --location=$REGION"
echo ""
echo "3. (Optional) Call /internal/deployment-started BEFORE deploying:"
echo "   curl -X POST $SERVICE_URL/internal/deployment-started \\"
echo "     -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\""
echo ""
echo "4. Monitor alerts in Cloud Monitoring or Slack"
echo ""
