#!/bin/bash
#
# Configure Slack Webhooks for Health Check Alerts
#
# This script stores Slack webhook URLs in GCP Secret Manager
# for automated health check alerts.
#
# Prerequisites:
# 1. Create Slack webhooks in your Slack workspace:
#    - Go to https://api.slack.com/apps
#    - Select your app or create a new one
#    - Go to "Incoming Webhooks" and activate them
#    - Create webhooks for:
#      a) Warning channel (for degraded status)
#      b) Error channel (for critical status)
#
# Usage: ./bin/infrastructure/configure-slack-webhooks.sh
#
# The script will prompt you for the webhook URLs.

set -euo pipefail

PROJECT_ID="nba-props-platform"

echo "=== Configure Slack Webhooks for Health Alerts ==="
echo "Project: $PROJECT_ID"
echo ""

echo "You need two Slack webhook URLs:"
echo "  1. Warning webhook (for degraded health status)"
echo "  2. Error webhook (for critical health status)"
echo ""
echo "To create these webhooks:"
echo "  1. Go to https://api.slack.com/apps"
echo "  2. Select your app (or create one)"
echo "  3. Go to 'Incoming Webhooks' and activate"
echo "  4. Create webhooks for your alert channels"
echo ""

# Function to create or update secret
create_or_update_secret() {
    local secret_name=$1
    local secret_value=$2

    # Check if secret exists
    if gcloud secrets describe "$secret_name" --project="$PROJECT_ID" &>/dev/null; then
        echo "Secret $secret_name exists, adding new version..."
        echo -n "$secret_value" | gcloud secrets versions add "$secret_name" \
            --data-file=- \
            --project="$PROJECT_ID"
    else
        echo "Creating secret $secret_name..."
        echo -n "$secret_value" | gcloud secrets create "$secret_name" \
            --data-file=- \
            --replication-policy="automatic" \
            --project="$PROJECT_ID"
    fi
}

# Prompt for warning webhook URL
echo ""
echo "Enter the Slack webhook URL for WARNING alerts:"
echo "(This will be sent when health score is 50-79%)"
read -r WARNING_WEBHOOK_URL

if [ -z "$WARNING_WEBHOOK_URL" ]; then
    echo "❌ Warning webhook URL cannot be empty"
    exit 1
fi

# Prompt for error webhook URL
echo ""
echo "Enter the Slack webhook URL for ERROR alerts:"
echo "(This will be sent when health score is <50% or critical failures)"
read -r ERROR_WEBHOOK_URL

if [ -z "$ERROR_WEBHOOK_URL" ]; then
    echo "❌ Error webhook URL cannot be empty"
    exit 1
fi

# Create/update secrets
echo ""
echo "Creating/updating secrets in Secret Manager..."
create_or_update_secret "slack-webhook-warning" "$WARNING_WEBHOOK_URL"
create_or_update_secret "slack-webhook-error" "$ERROR_WEBHOOK_URL"

echo ""
echo "✅ Slack webhooks configured successfully!"
echo ""
echo "=== Next Steps ==="
echo ""
echo "1. Grant the Cloud Run Job access to the secrets:"
echo ""
echo "   SERVICE_ACCOUNT=\$(gcloud run jobs describe unified-health-check \\"
echo "       --region=us-west2 --format='value(spec.template.spec.serviceAccountName)')"
echo ""
echo "   gcloud secrets add-iam-policy-binding slack-webhook-warning \\"
echo "       --member=\"serviceAccount:\$SERVICE_ACCOUNT\" \\"
echo "       --role=\"roles/secretmanager.secretAccessor\""
echo ""
echo "   gcloud secrets add-iam-policy-binding slack-webhook-error \\"
echo "       --member=\"serviceAccount:\$SERVICE_ACCOUNT\" \\"
echo "       --role=\"roles/secretmanager.secretAccessor\""
echo ""
echo "2. Update the Cloud Run Job to use the secrets:"
echo ""
echo "   gcloud run jobs update unified-health-check \\"
echo "       --region=us-west2 \\"
echo "       --set-secrets=SLACK_WEBHOOK_URL_WARNING=slack-webhook-warning:latest,SLACK_WEBHOOK_URL_ERROR=slack-webhook-error:latest"
echo ""
echo "3. Test the alerts:"
echo ""
echo "   gcloud run jobs execute unified-health-check --region=us-west2"
echo ""
echo "   Check your Slack channels for alert messages."
echo ""
echo "=== Webhook Management ==="
echo ""
echo "To view secrets:"
echo "  gcloud secrets list --project=$PROJECT_ID"
echo ""
echo "To update a webhook URL:"
echo "  Run this script again with new URLs"
echo ""
echo "To remove a secret:"
echo "  gcloud secrets delete slack-webhook-warning --project=$PROJECT_ID"
echo ""
