#!/bin/bash
# Cloud Shell Deployment Script for Session 33
# Run this entire script in Cloud Shell to deploy all services

set -e  # Exit on error

echo "=============================================="
echo "Session 33: Deploy Tracking Bug Fixes"
echo "=============================================="
echo ""

# Check if repo exists, clone if not
if [ ! -d "$HOME/nba-stats-scraper" ]; then
    echo "📥 Cloning repository..."
    cd $HOME
    git clone git@github.com:najicham/nba-stats-scraper.git
    cd nba-stats-scraper
else
    echo "✅ Repository exists"
    cd $HOME/nba-stats-scraper
fi

# Pull latest code
echo ""
echo "🔄 Pulling latest code..."
git fetch origin
git checkout main
git pull origin main

# Show current commit
echo ""
echo "📦 Current commit:"
git log -1 --oneline
echo ""
echo "Expected: d22c4d8 or ff8e564"
echo ""

# Verify deployment scripts exist
echo "🔍 Verifying deployment scripts..."
if [ ! -f "bin/raw/deploy/deploy_processors_simple.sh" ]; then
    echo "❌ ERROR: bin/raw/deploy/deploy_processors_simple.sh not found"
    exit 1
fi
if [ ! -f "bin/analytics/deploy/deploy_analytics_processors.sh" ]; then
    echo "❌ ERROR: bin/analytics/deploy/deploy_analytics_processors.sh not found"
    exit 1
fi
if [ ! -f "bin/precompute/deploy/deploy_precompute_processors.sh" ]; then
    echo "❌ ERROR: bin/precompute/deploy/deploy_precompute_processors.sh not found"
    exit 1
fi
echo "✅ All deployment scripts found"
echo ""

# Deploy Phase 2
echo "=============================================="
echo "Deploying Phase 2: Raw Processors"
echo "=============================================="
bash bin/raw/deploy/deploy_processors_simple.sh
echo ""

# Deploy Phase 3
echo "=============================================="
echo "Deploying Phase 3: Analytics Processors"
echo "=============================================="
bash bin/analytics/deploy/deploy_analytics_processors.sh
echo ""

# Deploy Phase 4
echo "=============================================="
echo "Deploying Phase 4: Precompute Processors"
echo "=============================================="
bash bin/precompute/deploy/deploy_precompute_processors.sh
echo ""

# Verify deployments
echo "=============================================="
echo "Verifying Deployments"
echo "=============================================="
echo ""

echo "=== Phase 2 Raw Processors ==="
gcloud run services describe nba-phase2-raw-processors --region=us-west2 \
  --format="value(status.latestReadyRevisionName,metadata.labels.'commit-sha')"

echo ""
echo "=== Phase 3 Analytics Processors ==="
gcloud run services describe nba-phase3-analytics-processors --region=us-west2 \
  --format="value(status.latestReadyRevisionName,metadata.labels.'commit-sha')"

echo ""
echo "=== Phase 4 Precompute Processors ==="
gcloud run services describe nba-phase4-precompute-processors --region=us-west2 \
  --format="value(status.latestReadyRevisionName,metadata.labels.'commit-sha')"

echo ""
echo "=============================================="
echo "✅ Deployment Complete!"
echo "=============================================="
echo ""
echo "All services should show commit: d22c4d8 or ff8e564"
echo ""
echo "Next step: Run this BigQuery query to verify tracking fix:"
echo ""
echo "SELECT processor_name, data_date, records_processed, status"
echo "FROM \`nba-props-platform.nba_reference.processor_run_history\`"
echo "WHERE processor_name IN ('BdlActivePlayersProcessor', 'BdlStandingsProcessor')"
echo "  AND data_date >= '2026-01-14' AND status = 'success'"
echo "ORDER BY started_at DESC LIMIT 20"
echo ""
