#!/bin/bash
# Create Alert Policies for Phase 3 and Phase 4 Services
# Created: January 21, 2026
# Purpose: Create actual alerting policies that send Slack notifications

set -euo pipefail

PROJECT_ID="nba-props-platform"
NOTIFICATION_CHANNEL="projects/nba-props-platform/notificationChannels/13444328261517403081"

echo "================================================"
echo "  Creating Alert Policies for Phase 3/4"
echo "  Project: $PROJECT_ID"
echo "================================================"
echo ""

# Function to create alert policy from JSON
create_alert_policy() {
    local policy_name="$1"
    local policy_file="$2"

    echo "Creating alert policy: $policy_name"

    if gcloud alpha monitoring policies create \
        --policy-from-file="$policy_file" \
        --project="$PROJECT_ID" 2>&1; then
        echo "  ✓ Created: $policy_name"
    else
        echo "  ! Failed or already exists: $policy_name"
    fi
}

# Create temporary directory for policy files
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

# 1. Phase 3 High Error Rate Alert
cat > "$TEMP_DIR/phase3_error_rate.json" <<EOF
{
  "displayName": "Phase 3 Analytics - High Error Rate",
  "documentation": {
    "content": "Phase 3 Analytics service is experiencing high error rates (>10 errors in 5 minutes). This may indicate a service crash or deployment issue. Check service logs and health endpoint immediately.",
    "mimeType": "text/markdown"
  },
  "conditions": [{
    "displayName": "Error count >10 in 5 min",
    "conditionThreshold": {
      "filter": "metric.type=\"logging.googleapis.com/user/phase3_analytics_errors\" resource.type=\"cloud_run_revision\"",
      "comparison": "COMPARISON_GT",
      "thresholdValue": 10,
      "duration": "300s",
      "aggregations": [{
        "alignmentPeriod": "60s",
        "perSeriesAligner": "ALIGN_RATE"
      }]
    }
  }],
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": ["$NOTIFICATION_CHANNEL"],
  "alertStrategy": {
    "autoClose": "1800s"
  }
}
EOF

# 2. Phase 4 High Error Rate Alert
cat > "$TEMP_DIR/phase4_error_rate.json" <<EOF
{
  "displayName": "Phase 4 Precompute - High Error Rate",
  "documentation": {
    "content": "Phase 4 Precompute service is experiencing high error rates (>10 errors in 5 minutes). This may indicate a service crash or deployment issue. Check service logs and health endpoint immediately.",
    "mimeType": "text/markdown"
  },
  "conditions": [{
    "displayName": "Error count >10 in 5 min",
    "conditionThreshold": {
      "filter": "metric.type=\"logging.googleapis.com/user/phase4_precompute_errors\" resource.type=\"cloud_run_revision\"",
      "comparison": "COMPARISON_GT",
      "thresholdValue": 10,
      "duration": "300s",
      "aggregations": [{
        "alignmentPeriod": "60s",
        "perSeriesAligner": "ALIGN_RATE"
      }]
    }
  }],
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": ["$NOTIFICATION_CHANNEL"],
  "alertStrategy": {
    "autoClose": "1800s"
  }
}
EOF

# 3. Phase 3 5xx Errors Alert
cat > "$TEMP_DIR/phase3_5xx.json" <<EOF
{
  "displayName": "Phase 3 Analytics - HTTP 5xx Errors",
  "documentation": {
    "content": "Phase 3 Analytics is returning 5xx errors. Check /health endpoint and recent deployment logs.",
    "mimeType": "text/markdown"
  },
  "conditions": [{
    "displayName": "5xx errors >5 in 5 min",
    "conditionThreshold": {
      "filter": "metric.type=\"logging.googleapis.com/user/phase3_5xx_errors\" resource.type=\"cloud_run_revision\"",
      "comparison": "COMPARISON_GT",
      "thresholdValue": 5,
      "duration": "300s",
      "aggregations": [{
        "alignmentPeriod": "60s",
        "perSeriesAligner": "ALIGN_RATE"
      }]
    }
  }],
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": ["$NOTIFICATION_CHANNEL"],
  "alertStrategy": {
    "autoClose": "1800s"
  }
}
EOF

# 4. Phase 4 5xx Errors Alert
cat > "$TEMP_DIR/phase4_5xx.json" <<EOF
{
  "displayName": "Phase 4 Precompute - HTTP 5xx Errors",
  "documentation": {
    "content": "Phase 4 Precompute is returning 5xx errors. Check /health endpoint and recent deployment logs.",
    "mimeType": "text/markdown"
  },
  "conditions": [{
    "displayName": "5xx errors >5 in 5 min",
    "conditionThreshold": {
      "filter": "metric.type=\"logging.googleapis.com/user/phase4_5xx_errors\" resource.type=\"cloud_run_revision\"",
      "comparison": "COMPARISON_GT",
      "thresholdValue": 5,
      "duration": "300s",
      "aggregations": [{
        "alignmentPeriod": "60s",
        "perSeriesAligner": "ALIGN_RATE"
      }]
    }
  }],
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": ["$NOTIFICATION_CHANNEL"],
  "alertStrategy": {
    "autoClose": "1800s"
  }
}
EOF

# Create all alert policies
echo "Creating alert policies..."
echo ""

create_alert_policy "Phase 3 Error Rate" "$TEMP_DIR/phase3_error_rate.json"
create_alert_policy "Phase 4 Error Rate" "$TEMP_DIR/phase4_error_rate.json"
create_alert_policy "Phase 3 5xx Errors" "$TEMP_DIR/phase3_5xx.json"
create_alert_policy "Phase 4 5xx Errors" "$TEMP_DIR/phase4_5xx.json"

echo ""
echo "================================================"
echo "✓ Alert policy creation complete!"
echo ""
echo "View alerts:"
echo "https://console.cloud.google.com/monitoring/alerting?project=$PROJECT_ID"
echo ""
echo "Test alerts by viewing metrics:"
echo "https://console.cloud.google.com/logs/metrics?project=$PROJECT_ID"
echo "================================================"
