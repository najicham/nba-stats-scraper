#!/bin/bash
# Week 0 Security Fixes - Staging Deployment Script
# Deploys all services affected by Week 0 security fixes to staging environment
#
# Usage: ./bin/deploy/week0_deploy_staging.sh [--dry-run]
#
# Prerequisites:
# - Secrets created via ./bin/deploy/week0_setup_secrets.sh
# - On week-0-security-fixes branch or commit 50f3120a+
# - gcloud authenticated with deploy permissions

set -e

DRY_RUN=false
if [ "$1" == "--dry-run" ]; then
    DRY_RUN=true
    echo "🔍 DRY RUN MODE - No actual deployments will occur"
    echo ""
fi

PROJECT_ID=$(gcloud config get-value project)
REGION="us-west2"

if [ -z "$PROJECT_ID" ]; then
    echo "❌ Error: GCP project not set"
    exit 1
fi

echo "🚀 Week 0 Security Fixes - Staging Deployment"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Branch: $(git branch --show-current)"
echo "Commit: $(git rev-parse --short HEAD)"
echo ""

# Verify we're on the right branch/commit
CURRENT_COMMIT=$(git rev-parse HEAD)
if ! git merge-base --is-ancestor 428a9676 "$CURRENT_COMMIT" 2>/dev/null; then
    echo "⚠️  Warning: Current commit may not include Week 0 security fixes"
    echo "   Expected: week-0-security-complete tag (428a9676) or later"
    read -p "   Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Function to deploy service
deploy_service() {
    local service_name=$1
    local source_dir=$2
    local env_vars=$3
    local secrets=$4

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📦 Deploying: $service_name"
    echo "   Source: $source_dir"

    if [ "$DRY_RUN" == "true" ]; then
        echo "   [DRY RUN] Would deploy with:"
        echo "   Env vars: $env_vars"
        echo "   Secrets: $secrets"
        return
    fi

    local deploy_cmd="gcloud run deploy $service_name"
    deploy_cmd="$deploy_cmd --source $source_dir"
    deploy_cmd="$deploy_cmd --region $REGION"
    deploy_cmd="$deploy_cmd --platform managed"
    deploy_cmd="$deploy_cmd --allow-unauthenticated"
    deploy_cmd="$deploy_cmd --memory 2Gi"
    deploy_cmd="$deploy_cmd --timeout 540"

    # Add environment variables
    if [ -n "$env_vars" ]; then
        deploy_cmd="$deploy_cmd --update-env-vars $env_vars"
    fi

    # Add secrets
    if [ -n "$secrets" ]; then
        deploy_cmd="$deploy_cmd --update-secrets $secrets"
    fi

    echo "   Deploying..."
    eval "$deploy_cmd"
    echo "   ✅ Deployed successfully"
}

# Phase 1: Scrapers (BettingPros needs API key)
echo ""
echo "🔄 Phase 1: Scrapers"
deploy_service \
    "nba-phase1-scrapers" \
    "./scrapers" \
    "ALLOW_DEGRADED_MODE=false" \
    "BETTINGPROS_API_KEY=bettingpros-api-key:latest,SENTRY_DSN=sentry-dsn:latest"

# Phase 2: Raw Processors (SQL injection fixes)
echo ""
echo "🔄 Phase 2: Raw Processors"
deploy_service \
    "nba-phase2-raw-processors" \
    "./data_processors/raw" \
    "ALLOW_DEGRADED_MODE=false" \
    "SENTRY_DSN=sentry-dsn:latest"

# Phase 3: Analytics Processors (Authentication + SQL fixes)
echo ""
echo "🔄 Phase 3: Analytics Processors"
deploy_service \
    "nba-phase3-analytics-processors" \
    "./data_processors/analytics" \
    "ALLOW_DEGRADED_MODE=false" \
    "VALID_API_KEYS=analytics-api-keys:latest,SENTRY_DSN=sentry-dsn:latest"

# Phase 4: Precompute (ML feature store changes)
echo ""
echo "🔄 Phase 4: Precompute Processors"
deploy_service \
    "nba-phase4-precompute-processors" \
    "./data_processors/precompute" \
    "ALLOW_DEGRADED_MODE=false" \
    "SENTRY_DSN=sentry-dsn:latest"

# Phase 5: Prediction Worker
echo ""
echo "🔄 Phase 5: Prediction Worker"
deploy_service \
    "prediction-worker" \
    "./predictions/worker" \
    "ALLOW_DEGRADED_MODE=false" \
    "SENTRY_DSN=sentry-dsn:latest"

# Phase 5: Prediction Coordinator
echo ""
echo "🔄 Phase 5: Prediction Coordinator"
deploy_service \
    "prediction-coordinator" \
    "./predictions/coordinator" \
    "" \
    "SENTRY_DSN=sentry-dsn:latest"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ All Week 0 services deployed to staging!"
echo ""
echo "📝 Next steps:"
echo "  1. Run smoke tests: ./bin/deploy/week0_smoke_tests.sh"
echo "  2. Monitor for 24 hours"
echo "  3. Review deployment checklist: docs/08-projects/.../PHASE-A-DEPLOYMENT-CHECKLIST.md"
echo ""
echo "🔍 Verify deployments:"
echo "  gcloud run services list --region=$REGION --filter='nba-phase'"
echo ""
