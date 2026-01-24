#!/bin/bash
# Deploy new cloud functions created in Resilience Session 2
# Created: 2026-01-24

set -euo pipefail

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo "==================================="
echo "Deploying New Cloud Functions"
echo "==================================="

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"
REGION="us-west2"
RUNTIME="python311"

log_info "Project: $PROJECT_ID"
log_info "Region: $REGION"
echo ""

# Verify gcloud is authenticated
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" &>/dev/null; then
    log_error "Not authenticated with gcloud. Run 'gcloud auth login' first."
    exit 1
fi

# Verify project exists
if ! gcloud projects describe "$PROJECT_ID" &>/dev/null; then
    log_error "Project $PROJECT_ID not found or not accessible."
    exit 1
fi

log_info "Pre-flight checks passed"
echo ""

# Deploy pipeline-dashboard
echo "1. Deploying pipeline-dashboard..."
gcloud functions deploy pipeline-dashboard \
  --gen2 \
  --runtime="$RUNTIME" \
  --region="$REGION" \
  --source=orchestration/cloud_functions/pipeline_dashboard \
  --entry-point=pipeline_dashboard \
  --trigger-http \
  --allow-unauthenticated \
  --timeout=60s \
  --memory=256MB \
  --project="$PROJECT_ID"

echo "   pipeline-dashboard deployed!"
echo ""

# Deploy auto-backfill-orchestrator
echo "2. Deploying auto-backfill-orchestrator..."
gcloud functions deploy auto-backfill-orchestrator \
  --gen2 \
  --runtime="$RUNTIME" \
  --region="$REGION" \
  --source=orchestration/cloud_functions/auto_backfill_orchestrator \
  --entry-point=auto_backfill_orchestrator \
  --trigger-http \
  --timeout=120s \
  --memory=512MB \
  --project="$PROJECT_ID"

echo "   auto-backfill-orchestrator deployed!"
echo ""

echo "==================================="
echo "Deployment Complete!"
echo "==================================="
echo ""

# Health check URLs
DASHBOARD_URL="https://$REGION-$PROJECT_ID.cloudfunctions.net/pipeline-dashboard?date=$(date +%Y-%m-%d)"
BACKFILL_URL="https://$REGION-$PROJECT_ID.cloudfunctions.net/auto-backfill-orchestrator?dry_run=true"

log_info "Verifying deployments..."
echo ""

# Health check for pipeline-dashboard
if curl -s -o /dev/null -w "%{http_code}" "$DASHBOARD_URL" | grep -q "200\|401"; then
    log_info "pipeline-dashboard: HEALTHY"
else
    log_warn "pipeline-dashboard: May need manual verification"
fi

# Health check for auto-backfill-orchestrator
if curl -s -o /dev/null -w "%{http_code}" "$BACKFILL_URL" | grep -q "200\|401"; then
    log_info "auto-backfill-orchestrator: HEALTHY"
else
    log_warn "auto-backfill-orchestrator: May need manual verification"
fi

echo ""
log_info "Verify manually:"
echo "  Pipeline Dashboard: $DASHBOARD_URL"
echo "  Auto-Backfill: $BACKFILL_URL"
echo ""
