#!/bin/bash
# Setup Memory Warning Alerts for Cloud Functions
#
# Creates Cloud Monitoring alert policies that fire when any Cloud Function
# exceeds 80% memory utilization.
#
# Usage:
#   ./bin/monitoring/setup_memory_alerts.sh
#
# Prerequisites:
#   - gcloud CLI authenticated
#   - Notification channel configured (Slack/Email)
#
# Part of: Pipeline Resilience Improvements (Jan 2026)

set -e

PROJECT_ID="nba-props-platform"
POLICY_NAME="cloud-function-memory-warning"

echo "=================================================="
echo "Cloud Function Memory Alert Setup"
echo "=================================================="
echo ""

# Check if policy already exists
EXISTING=$(gcloud alpha monitoring policies list \
    --project=$PROJECT_ID \
    --filter="displayName:'Cloud Function Memory'" \
    --format="value(name)" 2>/dev/null || true)

if [ -n "$EXISTING" ]; then
    echo "Alert policy already exists: $EXISTING"
    echo "To recreate, delete it first with:"
    echo "  gcloud alpha monitoring policies delete $EXISTING --project=$PROJECT_ID"
    exit 0
fi

# Create alert policy using REST API
echo "Creating alert policy via REST API..."

# Get notification channels
echo "Fetching notification channels..."
CHANNELS=$(gcloud alpha monitoring channels list \
    --project=$PROJECT_ID \
    --format="value(name)" 2>/dev/null | head -1)

if [ -z "$CHANNELS" ]; then
    echo ""
    echo "WARNING: No notification channels found."
    echo "Create one first via Cloud Console:"
    echo "  https://console.cloud.google.com/monitoring/alerting/notifications?project=$PROJECT_ID"
    echo ""
    CHANNELS_JSON="[]"
else
    echo "Using notification channel: $CHANNELS"
    CHANNELS_JSON="[\"$CHANNELS\"]"
fi

# Create the alert policy JSON
cat > /tmp/memory_alert_policy.json << EOF
{
  "displayName": "Cloud Function Memory Warning (>80%)",
  "documentation": {
    "content": "A Cloud Function is using more than 80% of its allocated memory. This may lead to OOM errors.\n\n**Action Required:**\n1. Check which function triggered the alert\n2. Review recent logs for memory issues\n3. Consider increasing memory allocation\n4. Run: ./bin/monitoring/check_cloud_resources.sh --check-logs",
    "mimeType": "text/markdown"
  },
  "conditions": [
    {
      "displayName": "Cloud Function Memory > 80%",
      "conditionThreshold": {
        "filter": "resource.type = \"cloud_function\" AND metric.type = \"cloudfunctions.googleapis.com/function/user_memory_bytes\"",
        "aggregations": [
          {
            "alignmentPeriod": "300s",
            "perSeriesAligner": "ALIGN_PERCENTILE_99"
          }
        ],
        "comparison": "COMPARISON_GT",
        "thresholdValue": 0.8,
        "duration": "300s",
        "trigger": {
          "count": 1
        }
      }
    }
  ],
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": $CHANNELS_JSON,
  "alertStrategy": {
    "autoClose": "604800s"
  }
}
EOF

# Create the policy
curl -s -X POST \
    -H "Authorization: Bearer $(gcloud auth print-access-token)" \
    -H "Content-Type: application/json" \
    -d @/tmp/memory_alert_policy.json \
    "https://monitoring.googleapis.com/v3/projects/$PROJECT_ID/alertPolicies" \
    > /tmp/alert_result.json

# Check result
if grep -q "error" /tmp/alert_result.json 2>/dev/null; then
    echo ""
    echo "ERROR creating alert policy:"
    cat /tmp/alert_result.json
    echo ""
    echo "Alternative: Create manually via Cloud Console:"
    echo "  https://console.cloud.google.com/monitoring/alerting/policies/create?project=$PROJECT_ID"
    exit 1
fi

echo ""
echo "=================================================="
echo "Alert Policy Created Successfully!"
echo "=================================================="
echo ""
echo "View in Cloud Console:"
echo "  https://console.cloud.google.com/monitoring/alerting?project=$PROJECT_ID"
echo ""
echo "The alert will fire when any Cloud Function uses >80% of its allocated memory."
echo ""

# Cleanup
rm -f /tmp/memory_alert_policy.json /tmp/alert_result.json

echo "Done!"
