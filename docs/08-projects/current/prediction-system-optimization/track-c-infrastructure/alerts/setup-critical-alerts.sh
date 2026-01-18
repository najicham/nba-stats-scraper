#!/bin/bash
# Setup Critical Alerts for NBA Prediction System
# Created: 2026-01-18
# Purpose: Create 2 critical monitoring alerts

set -e

PROJECT="nba-props-platform"

echo "🚀 Setting up critical alerts for NBA Prediction System"
echo "=================================================="
echo ""

# Alert 1: Prediction Coordinator Errors
echo "📊 Alert 1: Prediction Coordinator Error Detection"
echo "---------------------------------------------------"

# Create log-based metric for coordinator errors
echo "Creating log-based metric: coordinator_errors..."
gcloud logging metrics create coordinator_errors \
  --project=$PROJECT \
  --description="Count of errors in prediction coordinator" \
  --log-filter='
    resource.type="cloud_run_revision"
    AND resource.labels.service_name="prediction-coordinator"
    AND severity>=ERROR
  ' \
  --value-extractor='' \
  --metric-kind=DELTA \
  --value-type=INT64 \
  2>/dev/null || echo "  ℹ️  Metric already exists, skipping..."

echo "✅ Log-based metric created/verified"
echo ""

# Alert 2: Low Prediction Volume
echo "📊 Alert 2: Low Prediction Volume Detection"
echo "---------------------------------------------------"

# Create log-based metric for prediction completion
echo "Creating log-based metric: daily_predictions..."
gcloud logging metrics create daily_predictions \
  --project=$PROJECT \
  --description="Count of daily prediction completions" \
  --log-filter='
    resource.type="cloud_run_revision"
    AND resource.labels.service_name="prediction-coordinator"
    AND jsonPayload.message=~".*predictions.*generated.*"
  ' \
  --value-extractor='' \
  --metric-kind=DELTA \
  --value-type=INT64 \
  2>/dev/null || echo "  ℹ️  Metric already exists, skipping..."

echo "✅ Log-based metric created/verified"
echo ""

echo "=================================================="
echo "✅ Log-based metrics setup complete!"
echo ""
echo "📧 Next Steps - Create Alert Policies:"
echo "=================================================="
echo ""
echo "To complete the alert setup, you need to:"
echo ""
echo "1. Create notification channels (email, slack, etc):"
echo "   https://console.cloud.google.com/monitoring/alerting/notifications?project=$PROJECT"
echo ""
echo "2. Create alert policies using the Google Cloud Console:"
echo "   https://console.cloud.google.com/monitoring/alerting/policies?project=$PROJECT"
echo ""
echo "   Alert 1: Coordinator Errors"
echo "   - Metric: logging.googleapis.com/user/coordinator_errors"
echo "   - Condition: Any time series violates > 0 for 5 minutes"
echo "   - Severity: CRITICAL"
echo ""
echo "   Alert 2: Low Prediction Volume"
echo "   - Metric: logging.googleapis.com/user/daily_predictions"
echo "   - Condition: No data points in last 25 hours"
echo "   - Severity: HIGH"
echo ""
echo "Or use the Web UI setup guide:"
echo "   docs/08-projects/current/prediction-system-optimization/track-c-infrastructure/alerts/WEB-UI-SETUP.md"
echo ""
echo "=================================================="
echo "✅ Setup script complete!"
