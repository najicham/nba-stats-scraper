#!/bin/bash
# Creates Cloud Scheduler jobs for registry name resolution automation
# Run after post-game collection to resolve any new unresolved names

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
SERVICE_ACCOUNT="scheduler-orchestration@${PROJECT_ID}.iam.gserviceaccount.com"

# Get Cloud Run service URL for reference service
echo "Getting Cloud Run reference service URL..."
SERVICE_URL=$(gcloud run services describe nba-reference-service \
  --region=$REGION \
  --format="value(status.url)" 2>/dev/null || echo "")

if [ -z "$SERVICE_URL" ]; then
    echo "⚠️  Reference service not deployed yet. Using placeholder."
    echo "   Deploy the reference service first, then run this script again."
    echo ""
    echo "   Alternative: Run batch resolution manually:"
    echo "   python tools/player_registry/resolve_unresolved_batch.py"
    exit 0
fi

echo "✅ Reference Service URL: $SERVICE_URL"
echo ""

# Job 1: Nightly AI Resolution (4:30 AM ET - after post-game collection)
echo "1️⃣  Creating: registry-ai-resolution"
gcloud scheduler jobs create http registry-ai-resolution \
  --location=$REGION \
  --schedule="30 4 * * *" \
  --time-zone="America/New_York" \
  --uri="${SERVICE_URL}/resolve-pending" \
  --http-method=POST \
  --oidc-service-account-email=$SERVICE_ACCOUNT \
  --oidc-token-audience=$SERVICE_URL \
  --attempt-deadline=600s \
  --description="Nightly AI resolution of pending player names (4:30 AM ET)" \
  2>/dev/null && echo "✅ Created" || {
    echo "Job exists, updating..."
    gcloud scheduler jobs update http registry-ai-resolution \
      --location=$REGION \
      --schedule="30 4 * * *" \
      --uri="${SERVICE_URL}/resolve-pending"
    echo "✅ Updated"
  }

# Job 2: Registry Health Check (5:00 AM ET)
echo ""
echo "2️⃣  Creating: registry-health-check"
gcloud scheduler jobs create http registry-health-check \
  --location=$REGION \
  --schedule="0 5 * * *" \
  --time-zone="America/New_York" \
  --uri="${SERVICE_URL}/health-check" \
  --http-method=POST \
  --oidc-service-account-email=$SERVICE_ACCOUNT \
  --oidc-token-audience=$SERVICE_URL \
  --attempt-deadline=180s \
  --description="Daily registry health check (5:00 AM ET)" \
  2>/dev/null && echo "✅ Created" || {
    echo "Job exists, updating..."
    gcloud scheduler jobs update http registry-health-check \
      --location=$REGION \
      --schedule="0 5 * * *" \
      --uri="${SERVICE_URL}/health-check"
    echo "✅ Updated"
  }

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Registry scheduler jobs created/updated!"
echo ""
echo "Verify with:"
echo "  gcloud scheduler jobs list --location=$REGION | grep registry"
echo ""
echo "NOTE: The reference service needs endpoints:"
echo "  POST /resolve-pending  - Runs AI batch resolution"
echo "  POST /health-check     - Runs resolution health check"
