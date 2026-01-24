#!/bin/bash
# Week 0 Security Fixes - Secret Setup Script
# Creates required secrets in GCP Secret Manager for Week 0 deployment
#
# Usage: ./bin/deploy/week0_setup_secrets.sh
#
# Prerequisites:
# - gcloud CLI installed and authenticated
# - Project ID set (gcloud config set project <PROJECT_ID>)
# - Proper permissions to create secrets

set -euo pipefail

PROJECT_ID=$(gcloud config get-value project)
if [ -z "$PROJECT_ID" ]; then
    echo "❌ Error: GCP project not set. Run: gcloud config set project <PROJECT_ID>"
    exit 1
fi

echo "🔐 Week 0 Security Secrets Setup"
echo "Project: $PROJECT_ID"
echo ""

# Check if .env file exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found"
    echo "Create .env file with the following variables:"
    echo "  BETTINGPROS_API_KEY=<your-key>"
    echo "  SENTRY_DSN=<your-dsn>"
    echo "  ANALYTICS_API_KEY_1=<generate-with: python -c 'import secrets; print(secrets.token_urlsafe(32))'>"
    exit 1
fi

# Load environment variables
source .env

echo "📋 Checking required environment variables..."
MISSING_VARS=()

if [ -z "$BETTINGPROS_API_KEY" ]; then
    MISSING_VARS+=("BETTINGPROS_API_KEY")
fi

if [ -z "$SENTRY_DSN" ]; then
    MISSING_VARS+=("SENTRY_DSN")
fi

if [ -z "$ANALYTICS_API_KEY_1" ]; then
    MISSING_VARS+=("ANALYTICS_API_KEY_1")
fi

if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    echo "❌ Missing required variables in .env:"
    for var in "${MISSING_VARS[@]}"; do
        echo "  - $var"
    done
    exit 1
fi

echo "✅ All required variables found in .env"
echo ""

# Function to create or update secret
create_or_update_secret() {
    local secret_name=$1
    local secret_value=$2

    echo "🔑 Processing secret: $secret_name"

    # Check if secret exists
    if gcloud secrets describe "$secret_name" --project="$PROJECT_ID" &>/dev/null; then
        echo "  ↻ Secret exists, adding new version..."
        echo -n "$secret_value" | gcloud secrets versions add "$secret_name" \
            --data-file=- \
            --project="$PROJECT_ID"
        echo "  ✅ New version added"
    else
        echo "  + Creating new secret..."
        echo -n "$secret_value" | gcloud secrets create "$secret_name" \
            --data-file=- \
            --replication-policy="automatic" \
            --project="$PROJECT_ID"
        echo "  ✅ Secret created"
    fi
}

# 1. BettingPros API Key
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
create_or_update_secret "bettingpros-api-key" "$BETTINGPROS_API_KEY"

# 2. Sentry DSN
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
create_or_update_secret "sentry-dsn" "$SENTRY_DSN"

# 3. Analytics API Keys (comma-separated list)
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
# Support multiple keys if provided
VALID_API_KEYS="${ANALYTICS_API_KEY_1}"
if [ -n "$ANALYTICS_API_KEY_2" ]; then
    VALID_API_KEYS="${VALID_API_KEYS},${ANALYTICS_API_KEY_2}"
fi
if [ -n "$ANALYTICS_API_KEY_3" ]; then
    VALID_API_KEYS="${VALID_API_KEYS},${ANALYTICS_API_KEY_3}"
fi

create_or_update_secret "analytics-api-keys" "$VALID_API_KEYS"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "✅ All secrets created/updated successfully!"
echo ""
echo "📝 Next steps:"
echo "  1. Verify secrets: gcloud secrets list --project=$PROJECT_ID"
echo "  2. Grant Cloud Run access to secrets (if not already done):"
echo "     gcloud projects add-iam-policy-binding $PROJECT_ID \\"
echo "       --member='serviceAccount:<SERVICE_ACCOUNT>@$PROJECT_ID.iam.gserviceaccount.com' \\"
echo "       --role='roles/secretmanager.secretAccessor'"
echo "  3. Deploy services with: ./bin/deploy/week0_deploy_staging.sh"
echo ""
echo "🔐 Secret names created:"
echo "  - bettingpros-api-key"
echo "  - sentry-dsn"
echo "  - analytics-api-keys"
echo ""
