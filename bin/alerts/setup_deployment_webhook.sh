#!/bin/bash
# Setup Deployment Notifications Slack Webhook
#
# Usage:
#   ./setup_deployment_webhook.sh <slack-webhook-url>
#
# Example:
#   ./setup_deployment_webhook.sh https://hooks.slack.com/services/YOUR/WEBHOOK/URL

set -e

PROJECT_ID="nba-props-platform"
SECRET_NAME="deployment-notifications-slack-webhook"
WEBHOOK_URL="$1"

if [ -z "$WEBHOOK_URL" ]; then
    echo "Error: Slack webhook URL is required"
    echo ""
    echo "Usage: $0 <slack-webhook-url>"
    echo ""
    echo "To get a webhook URL:"
    echo "  1. Go to https://api.slack.com/apps"
    echo "  2. Create a new app or select existing"
    echo "  3. Enable 'Incoming Webhooks'"
    echo "  4. Add webhook to workspace and select channel"
    echo "  5. Copy the webhook URL"
    exit 1
fi

echo "Creating Secret Manager secret for deployment notifications..."

# Check if secret exists
if gcloud secrets describe "$SECRET_NAME" --project="$PROJECT_ID" &>/dev/null; then
    echo "Secret already exists - adding new version..."
    echo -n "$WEBHOOK_URL" | gcloud secrets versions add "$SECRET_NAME" \
        --project="$PROJECT_ID" \
        --data-file=-
else
    echo "Creating new secret..."
    echo -n "$WEBHOOK_URL" | gcloud secrets create "$SECRET_NAME" \
        --project="$PROJECT_ID" \
        --replication-policy="automatic" \
        --data-file=-
fi

echo ""
echo "✓ Webhook configured successfully!"
echo ""
echo "The prediction worker deployment script will now send notifications to Slack."
echo ""
echo "To test, run:"
echo "  ./bin/predictions/deploy/deploy_prediction_worker.sh prod"
echo ""
