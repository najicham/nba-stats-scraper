#!/bin/bash

# Setup Deep Health Check Monitoring for NBA Prediction Worker
#
# This script creates:
# 1. Cloud Monitoring uptime check for /health/deep endpoint
# 2. Alert policy to fire on consecutive health check failures
#
# Usage:
#   ./setup_health_monitoring.sh [PROJECT_ID] [ENVIRONMENT]
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
elif [ "$ENVIRONMENT" = "staging" ]; then
    SERVICE_NAME="prediction-worker-staging"
else
    SERVICE_NAME="prediction-worker-dev"
fi

# Uptime check configuration
UPTIME_CHECK_ID="nba-prediction-worker-deep-health-${ENVIRONMENT}"
CHECK_FREQUENCY="5"  # 5 minutes

# Alert configuration
ALERT_NAME="[WARNING] NBA Prediction Worker Health Check Failed"
SLACK_CHANNEL_ID=$(gcloud alpha monitoring channels list \
    --project="$PROJECT_ID" \
    --filter='displayName="Slack - #platform-team"' \
    --format='value(name)' \
    --limit=1)

echo "=========================================="
echo "Setup NBA Deep Health Check Monitoring"
echo "=========================================="
echo "Project: $PROJECT_ID"
echo "Environment: $ENVIRONMENT"
echo "Service: $SERVICE_NAME"
echo "Region: $REGION"
echo ""

# Step 1: Get Cloud Run service URL
echo "Step 1: Getting Cloud Run service URL..."
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --format='value(status.url)')

if [ -z "$SERVICE_URL" ]; then
    echo "❌ ERROR: Service $SERVICE_NAME not found in $PROJECT_ID"
    exit 1
fi

HEALTH_URL="${SERVICE_URL}/health/deep"
echo "✓ Service URL: $SERVICE_URL"
echo "✓ Health endpoint: $HEALTH_URL"
echo ""

# Step 2: Create uptime check
echo "Step 2: Creating Cloud Monitoring uptime check..."

# Extract host from URL
SERVICE_HOST=$(echo $SERVICE_URL | sed 's|https://||' | sed 's|http://||' | sed 's|/.*||')

# Check if uptime check already exists
EXISTING_CHECK=$(gcloud monitoring uptime list \
    --project="$PROJECT_ID" \
    --filter="display_name='$UPTIME_CHECK_ID'" \
    --format='value(name)' \
    --limit=1 2>/dev/null || echo "")

if [ -n "$EXISTING_CHECK" ]; then
    echo "⚠️  Uptime check $UPTIME_CHECK_ID already exists - skipping creation"
    echo "    To update, delete first: gcloud monitoring uptime delete $EXISTING_CHECK"
    UPTIME_CHECK_NAME="$EXISTING_CHECK"
else
    # Create uptime check using new syntax
    CREATE_OUTPUT=$(gcloud monitoring uptime create "$UPTIME_CHECK_ID" \
        --project="$PROJECT_ID" \
        --resource-type="uptime-url" \
        --resource-labels="host=$SERVICE_HOST" \
        --path="/health/deep" \
        --port=443 \
        --protocol="https" \
        --request-method="get" \
        --validate-ssl=true \
        --status-classes="2xx" \
        --period="${CHECK_FREQUENCY}" \
        --timeout="10" \
        --regions="usa-oregon,usa-virginia,usa-iowa" 2>&1)

    # Extract the uptime check name from creation output
    UPTIME_CHECK_NAME=$(echo "$CREATE_OUTPUT" | grep -oP 'projects/[^]]+')

    echo "✓ Uptime check created: $UPTIME_CHECK_ID"
    echo "  Frequency: Every 5 minutes"
    echo "  Endpoint: $HEALTH_URL"
fi
echo ""

# Step 3: Verify uptime check ID
echo "Step 3: Verifying uptime check..."

if [ -z "$UPTIME_CHECK_NAME" ]; then
    echo "❌ ERROR: Could not get uptime check name"
    exit 1
fi

# Extract just the check ID from the full path
CHECK_ID=$(basename "$UPTIME_CHECK_NAME")

echo "✓ Uptime check ID: $CHECK_ID"
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
    cat > /tmp/health_alert_policy.yaml <<EOF
displayName: "$ALERT_NAME"
documentation:
  content: |
    ## Prediction Worker Health Check Failed

    The deep health check endpoint failed 2 consecutive times (10 minute detection window).

    **Health Checks Performed:**
    - GCS Access: Can read model files from buckets
    - BigQuery Access: Can query predictions table
    - Model Loading: Models are accessible and loadable
    - Configuration: All required env vars are set

    **Investigation Steps:**
    1. Check the health endpoint directly: $HEALTH_URL
    2. Review Cloud Run logs for errors
    3. Verify service is running and not crashed
    4. Check which specific dependency failed in the health check response

    **Common Causes:**
    - GCS permissions issues
    - BigQuery quota/permissions issues
    - Model file missing or inaccessible
    - Required env vars not set
    - Service crashed or restarting

    **To Fix:**
    1. Review logs: gcloud run services logs read $SERVICE_NAME --project=$PROJECT_ID
    2. Fix the specific dependency that failed
    3. Verify fix by calling /health/deep endpoint
    4. Alert should auto-resolve once health check passes

    **Related Runbook:** docs/04-deployment/ALERT-RUNBOOKS.md (Week 2 section)
  mimeType: text/markdown
conditions:
  - displayName: "Health check failures"
    conditionThreshold:
      aggregations:
        - alignmentPeriod: 300s
          crossSeriesReducer: REDUCE_COUNT_FALSE
          groupByFields:
            - resource.project_id
          perSeriesAligner: ALIGN_NEXT_OLDER
      comparison: COMPARISON_GT
      duration: 600s
      filter: |
        resource.type = "uptime_url"
        metric.type = "monitoring.googleapis.com/uptime_check/check_passed"
        metric.labels.check_id = "$CHECK_ID"
      thresholdValue: 1
      trigger:
        count: 1
combiner: OR
enabled: true
alertStrategy:
  autoClose: 1800s
EOF

    gcloud alpha monitoring policies create \
        --project="$PROJECT_ID" \
        --policy-from-file=/tmp/health_alert_policy.yaml \
        $NOTIFICATION_CHANNELS

    rm /tmp/health_alert_policy.yaml

    echo "✓ Alert policy created: $ALERT_NAME"
fi

echo ""
echo "=========================================="
echo "✓ Health Monitoring Setup Complete!"
echo "=========================================="
echo ""
echo "Next Steps:"
echo "1. Deploy updated prediction-worker with health_checks.py"
echo ""
echo "2. Test the health endpoint manually:"
echo "   curl $HEALTH_URL"
echo ""
echo "3. View uptime check status:"
echo "   gcloud monitoring uptime list --project=$PROJECT_ID"
echo ""
echo "4. Alerts will fire after 2 consecutive failures (10 minutes)"
echo ""
