#!/bin/bash
#
# setup-grading-alerts.sh
#
# Sets up Cloud Monitoring alerts for the grading system.
# This creates log-based metrics and alert policies to detect issues early.
#
# Prerequisites:
# - gcloud CLI configured
# - Project: nba-props-platform
# - Permissions: Monitoring Admin, Logging Admin

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"

echo "=== Setting Up Grading System Alerts ==="
echo "Project: $PROJECT_ID"
echo ""

# Step 1: Create Slack notification channel (if not exists)
echo "1. Setting up notification channels..."
echo ""
echo "To create a Slack notification channel:"
echo "  1. Go to: https://console.cloud.google.com/monitoring/alerting/notifications"
echo "  2. Click 'Add New'"
echo "  3. Select 'Slack'"
echo "  4. Follow instructions to connect your Slack workspace"
echo "  5. Note the notification channel ID"
echo ""
read -p "Have you created a Slack notification channel? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Please create notification channel first, then re-run this script."
    exit 1
fi

read -p "Enter Slack notification channel ID (projects/nba-props-platform/notificationChannels/...): " CHANNEL_ID

# Step 2: Create log-based metric for grading coverage
echo ""
echo "2. Creating log-based metric for grading coverage..."

# Note: This requires BigQuery scheduled query to write results to Cloud Logging
# The metric counts how many times coverage drops below 70%

cat > /tmp/grading-coverage-metric.yaml <<EOF
name: grading_coverage_low
description: "Counts instances where grading coverage drops below 70%"
filter: |
  resource.type="bigquery_project"
  jsonPayload.message=~"grading.*coverage.*[0-6]?[0-9]\\.[0-9]%"
  OR textPayload=~"LOW_COVERAGE_ALERT"
metricDescriptor:
  metricKind: DELTA
  valueType: INT64
  unit: "1"
  displayName: "Low Grading Coverage Events"
EOF

echo "Log-based metric configuration saved to: /tmp/grading-coverage-metric.yaml"
echo ""
echo "To create this metric manually:"
echo "  gcloud logging metrics create grading_coverage_low \\"
echo "    --description='Counts instances where grading coverage drops below 70%' \\"
echo "    --log-filter='textPayload=~\"LOW_COVERAGE_ALERT\"'"
echo ""

# Step 3: Create alert policy for Phase 3 503 errors
echo "3. Creating alert policy for Phase 3 503 errors..."

cat > /tmp/phase3-503-alert.json <<EOF
{
  "displayName": "Phase 3 Analytics 503 Errors (Critical)",
  "documentation": {
    "content": "## Phase 3 503 Errors Detected\n\n**Severity:** Critical\n\n**What This Means:**\nThe grading auto-heal mechanism is failing with 503 errors when trying to trigger Phase 3 analytics.\n\n**Immediate Action:**\n1. Verify Phase 3 service has minScale=1:\n   \`\`\`\n   gcloud run services describe nba-phase3-analytics-processors --region=us-west2 --format=yaml | grep minScale\n   \`\`\`\n2. If minScale=0, fix it:\n   \`\`\`\n   gcloud run services update nba-phase3-analytics-processors --region=us-west2 --min-instances=1\n   \`\`\`\n\n**Reference:** docs/09-handoff/SESSION-99-PHASE3-FIX-COMPLETE.md",
    "mimeType": "text/markdown"
  },
  "conditions": [
    {
      "displayName": "Phase 3 503 errors > 0",
      "conditionMatchedLog": {
        "filter": "resource.type=\\"cloud_function\\" AND resource.labels.function_name=\\"phase5b-grading\\" AND textPayload=~\\"Phase 3.*503.*Service Unavailable\\""
      }
    }
  ],
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": [
    "$CHANNEL_ID"
  ],
  "alertStrategy": {
    "autoClose": "3600s",
    "notificationRateLimit": {
      "period": "1800s"
    }
  }
}
EOF

echo "Creating Phase 3 503 error alert..."
gcloud alpha monitoring policies create --policy-from-file=/tmp/phase3-503-alert.json 2>/dev/null || echo "Alert policy may already exist"

# Step 4: Create alert policy for no grading activity
echo ""
echo "4. Creating alert policy for missing grading activity..."

cat > /tmp/no-grading-alert.json <<EOF
{
  "displayName": "No Grading Activity for 48+ Hours (Critical)",
  "documentation": {
    "content": "## No Grading Activity Detected\n\n**Severity:** Critical\n\n**What This Means:**\nNo grading activity has been detected in the last 48 hours.\n\n**Immediate Actions:**\n1. Check Cloud Scheduler: \`gcloud scheduler jobs describe nba-daily-grading --location=us-west2\`\n2. Check grading function: \`gcloud functions describe phase5b-grading --region=us-west2\`\n3. Manual trigger: \`gcloud pubsub topics publish nba-grading-trigger --message='{\"target_date\":\"YYYY-MM-DD\"}'\`\n\n**Reference:** docs/02-operations/GRADING-TROUBLESHOOTING-RUNBOOK.md",
    "mimeType": "text/markdown"
  },
  "conditions": [
    {
      "displayName": "No grading logs in 48 hours",
      "conditionAbsent": {
        "filter": "resource.type=\\"cloud_function\\" AND resource.labels.function_name=\\"phase5b-grading\\" AND (textPayload=~\\"Grading.*complete\\" OR textPayload=~\\"graded.*predictions\\")",
        "duration": "172800s"
      }
    }
  ],
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": [
    "$CHANNEL_ID"
  ],
  "alertStrategy": {
    "autoClose": "86400s"
  }
}
EOF

echo "Creating no grading activity alert..."
gcloud alpha monitoring policies create --policy-from-file=/tmp/no-grading-alert.json 2>/dev/null || echo "Alert policy may already exist"

# Cleanup
rm -f /tmp/grading-coverage-metric.yaml /tmp/phase3-503-alert.json /tmp/no-grading-alert.json

echo ""
echo "=== Alert Setup Complete ==="
echo ""
echo "✅ Created alert policies:"
echo "  1. Phase 3 503 errors"
echo "  2. No grading activity for 48+ hours"
echo ""
echo "📊 To view alerts:"
echo "  https://console.cloud.google.com/monitoring/alerting/policies?project=$PROJECT_ID"
echo ""
echo "📧 Notifications will be sent to: $CHANNEL_ID"
echo ""
echo "Next steps:"
echo "  1. Test alerts by checking Cloud Monitoring console"
echo "  2. Verify Slack notifications are working"
echo "  3. Document alert channel ID in monitoring guide"
echo ""
echo "For manual monitoring, use:"
echo "  bash monitoring/check-system-health.sh"
