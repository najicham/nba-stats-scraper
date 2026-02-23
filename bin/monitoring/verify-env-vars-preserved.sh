#!/bin/bash
# P1-2: Environment Variable Drift Detection (Session 89)
#
# Verifies required environment variables are preserved after deployment.
# Prevents: Session 81 - env vars wiped using --set-env-vars instead of --update-env-vars
#
# Usage: ./bin/monitoring/verify-env-vars-preserved.sh <service-name>

set -e

SERVICE=$1
REGION="us-west2"
PROJECT="nba-props-platform"

if [ -z "$SERVICE" ]; then
    echo "Usage: $0 <service-name>"
    exit 1
fi

echo "=============================================="
echo "P1-2: Environment Variable Drift Detection"
echo "=============================================="
echo "Service: $SERVICE"
echo ""

# Define required env vars per service
IS_CLOUD_FUNCTION=false
case "$SERVICE" in
  prediction-worker)
    REQUIRED_VARS=(
      "GCP_PROJECT_ID"
      "CATBOOST_V8_MODEL_PATH"
      "CATBOOST_V9_MODEL_PATH"
      "PUBSUB_READY_TOPIC"
      "BUILD_COMMIT"
      "BUILD_TIMESTAMP"
    )
    ;;
  prediction-coordinator)
    REQUIRED_VARS=(
      "GCP_PROJECT_ID"
      "BUILD_COMMIT"
      "BUILD_TIMESTAMP"
    )
    ;;
  nba-phase2-raw-processors)
    REQUIRED_VARS=(
      "GCP_PROJECT_ID"
      "BUILD_COMMIT"
      "BUILD_TIMESTAMP"
    )
    ;;
  nba-phase3-analytics-processors)
    REQUIRED_VARS=(
      "GCP_PROJECT_ID"
      "BUILD_COMMIT"
      "BUILD_TIMESTAMP"
    )
    ;;
  nba-phase4-precompute-processors)
    REQUIRED_VARS=(
      "GCP_PROJECT_ID"
      "BUILD_COMMIT"
      "BUILD_TIMESTAMP"
    )
    ;;
  nba-scrapers|nba-phase1-scrapers)
    REQUIRED_VARS=(
      "GCP_PROJECT_ID"
      "BUILD_COMMIT"
      "BUILD_TIMESTAMP"
    )
    ;;
  unified-dashboard)
    REQUIRED_VARS=(
      "GCP_PROJECT_ID"
      "BUILD_COMMIT"
      "BUILD_TIMESTAMP"
    )
    ;;
  nba-grading-service)
    REQUIRED_VARS=(
      "GCP_PROJECT_ID"
      "BUILD_COMMIT"
      "BUILD_TIMESTAMP"
    )
    ;;
  live-export)
    REQUIRED_VARS=(
      "GCP_PROJECT"
      "BDL_API_KEY"
    )
    IS_CLOUD_FUNCTION=true
    ;;
  live-freshness-monitor)
    REQUIRED_VARS=(
      "GCP_PROJECT"
      "SLACK_WEBHOOK_URL"
    )
    IS_CLOUD_FUNCTION=true
    ;;
  *)
    echo "⚠️  WARNING: No env var requirements defined for $SERVICE"
    echo "   Add service to case statement in this script"
    exit 2
    ;;
esac

# Get deployed env vars — Cloud Functions use different gcloud command and JSON path
echo "Fetching deployed environment variables..."
if [ "${IS_CLOUD_FUNCTION:-false}" = "true" ]; then
  echo "  (detected as Cloud Function)"
  DEPLOYED_VARS=$(gcloud functions describe "$SERVICE" \
    --region="$REGION" \
    --project="$PROJECT" \
    --format="json" 2>/dev/null | jq -r '.environmentVariables // {} | keys[]' 2>/dev/null)
else
  DEPLOYED_VARS=$(gcloud run services describe "$SERVICE" \
    --region="$REGION" \
    --project="$PROJECT" \
    --format="json" 2>/dev/null | jq -r '.spec.template.spec.containers[0].env[]?.name // empty' 2>/dev/null)
fi

if [ -z "$DEPLOYED_VARS" ]; then
  echo ""
  echo "=============================================="
  echo "❌ CRITICAL: Cannot fetch environment variables"
  echo "=============================================="
  echo "Service may not exist or gcloud auth failed"
  exit 1
fi

# Check all required vars present
MISSING=()
PRESENT=()
for var in "${REQUIRED_VARS[@]}"; do
  if echo "$DEPLOYED_VARS" | grep -q "^$var$"; then
    PRESENT+=("$var")
  else
    MISSING+=("$var")
  fi
done

# Report results
echo ""
echo "Environment Variable Check:"
echo "  Total required: ${#REQUIRED_VARS[@]}"
echo "  Present: ${#PRESENT[@]}"
echo "  Missing: ${#MISSING[@]}"
echo ""

if [ ${#PRESENT[@]} -gt 0 ]; then
  echo "✅ Present variables:"
  for var in "${PRESENT[@]}"; do
    echo "  - $var"
  done
fi

if [ ${#MISSING[@]} -gt 0 ]; then
  echo ""
  echo "=============================================="
  echo "🚨 CRITICAL: MISSING ENVIRONMENT VARIABLES"
  echo "=============================================="
  echo ""
  echo "The following required variables are missing:"
  for var in "${MISSING[@]}"; do
    echo "  ❌ $var"
  done
  echo ""
  echo "ROOT CAUSE: This indicates deployment used --set-env-vars"
  echo "            instead of --update-env-vars, wiping all vars."
  echo ""
  echo "Impact:"
  echo "  - Service may crash on startup"
  echo "  - Missing configuration for critical features"
  echo "  - Requires immediate re-deployment"
  echo ""
  echo "Fix:"
  echo "  1. Re-deploy with --update-env-vars to preserve vars:"
  echo "     gcloud run services update $SERVICE \\"
  echo "       --region=$REGION \\"
  echo "       --update-env-vars=\"MISSING_VAR=value\""
  echo ""
  echo "  2. Or use deploy script which uses --update-env-vars:"
  echo "     ./bin/deploy-service.sh $SERVICE"
  echo ""
  echo "Prevention:"
  echo "  - ALWAYS use --update-env-vars for partial updates"
  echo "  - Use --set-env-vars ONLY when replacing ALL vars"
  echo "  - Use ./bin/deploy-service.sh for all deployments"
  echo "=============================================="
  exit 1
fi

echo ""
echo "=============================================="
echo "✅ ALL REQUIRED VARIABLES PRESENT"
echo "=============================================="
echo "No environment variable drift detected"
echo "Deployment preserved all required configuration"
echo "=============================================="
