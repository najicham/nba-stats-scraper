#!/bin/bash
# Setup Auth Error Spike Alert
# Created: 2026-01-14, Session 38
#
# This script creates a Cloud Monitoring log-based metric and alert policy
# to detect spikes in authentication errors (401/403) on Cloud Run services.
#
# Usage:
#   ./scripts/setup_auth_error_alert.sh
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - Appropriate IAM permissions for Cloud Monitoring

set -e

PROJECT_ID="nba-props-platform"
METRIC_NAME="cloud_run_auth_errors"
ALERT_POLICY_NAME="Cloud Run Auth Error Spike"

echo "🔧 Setting up Auth Error Monitoring..."
echo ""

# Step 1: Create log-based metric for auth errors
echo "1️⃣ Creating log-based metric: ${METRIC_NAME}"

# Check if metric already exists
if gcloud logging metrics describe "${METRIC_NAME}" --project="${PROJECT_ID}" &>/dev/null; then
    echo "   ✅ Metric already exists"
else
    gcloud logging metrics create "${METRIC_NAME}" \
        --project="${PROJECT_ID}" \
        --description="Count of authentication errors (401/403) on Cloud Run services" \
        --log-filter='resource.type="cloud_run_revision" AND (textPayload=~"401" OR textPayload=~"403" OR textPayload=~"not authenticated" OR textPayload=~"not authorized" OR textPayload=~"Unauthorized")'
    echo "   ✅ Metric created"
fi

# Step 2: Create alert policy
echo ""
echo "2️⃣ Creating alert policy: ${ALERT_POLICY_NAME}"

# Create the alert policy JSON
ALERT_POLICY_JSON=$(cat <<'EOF'
{
  "displayName": "Cloud Run Auth Error Spike",
  "documentation": {
    "content": "## Cloud Run Authentication Error Spike\n\nThis alert fires when there are more than 10 authentication errors (401/403) in a 5-minute window.\n\n### Possible Causes\n- Pub/Sub subscription missing OIDC configuration\n- Scheduler job with incorrect audience\n- Service account permissions revoked\n- Token expiration issues\n\n### Resolution Steps\n1. Check Pub/Sub subscriptions: `gcloud pubsub subscriptions describe <sub-name> --format='yaml(pushConfig)'`\n2. Verify scheduler job audiences: `gcloud scheduler jobs describe <job-name> --location=us-west2`\n3. Run health check: `python scripts/system_health_check.py --hours=1`\n4. See Session 38 handoff for detailed fix procedures",
    "mimeType": "text/markdown"
  },
  "conditions": [
    {
      "displayName": "Auth errors > 10 in 5 minutes",
      "conditionThreshold": {
        "filter": "resource.type = \"cloud_run_revision\" AND metric.type = \"logging.googleapis.com/user/cloud_run_auth_errors\"",
        "aggregations": [
          {
            "alignmentPeriod": "300s",
            "perSeriesAligner": "ALIGN_SUM"
          }
        ],
        "comparison": "COMPARISON_GT",
        "thresholdValue": 10,
        "duration": "0s",
        "trigger": {
          "count": 1
        }
      }
    }
  ],
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": []
}
EOF
)

# Check if we need to add notification channels
echo "   ℹ️  Note: No notification channels configured. Add channels via Cloud Console."
echo ""

# Save the policy to a temp file
TEMP_FILE=$(mktemp)
echo "${ALERT_POLICY_JSON}" > "${TEMP_FILE}"

# Check if policy already exists
EXISTING_POLICY=$(gcloud alpha monitoring policies list \
    --project="${PROJECT_ID}" \
    --filter="displayName='${ALERT_POLICY_NAME}'" \
    --format="value(name)" 2>/dev/null || true)

if [ -n "${EXISTING_POLICY}" ]; then
    echo "   ✅ Alert policy already exists: ${EXISTING_POLICY}"
else
    # Create the policy
    gcloud alpha monitoring policies create \
        --project="${PROJECT_ID}" \
        --policy-from-file="${TEMP_FILE}" 2>/dev/null || {
        echo "   ⚠️  Could not create alert policy via CLI."
        echo "   📋 Policy JSON saved to: ${TEMP_FILE}"
        echo "   → Create manually via Cloud Console: Monitoring > Alerting > Create Policy"
    }
fi

rm -f "${TEMP_FILE}"

echo ""
echo "✅ Auth error monitoring setup complete!"
echo ""
echo "To verify:"
echo "  1. Check metric: gcloud logging metrics describe ${METRIC_NAME}"
echo "  2. Check alert: gcloud alpha monitoring policies list --filter='displayName~Auth'"
echo "  3. Test by viewing logs: gcloud logging read 'resource.type=\"cloud_run_revision\" textPayload=~\"401\"' --limit=5"
echo ""
echo "To add notification channels (email/Slack):"
echo "  → Go to Cloud Console > Monitoring > Alerting > Edit '${ALERT_POLICY_NAME}'"
