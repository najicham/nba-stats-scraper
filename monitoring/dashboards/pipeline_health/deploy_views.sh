#!/bin/bash
# ============================================================================
# Script: deploy_views.sh
# Purpose: Deploy all pipeline health monitoring views to BigQuery
# ============================================================================
# This script creates the nba_monitoring dataset (if needed) and deploys
# all four monitoring views that power the pipeline health dashboard.
#
# Usage:
#   ./deploy_views.sh
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - BigQuery API enabled
#   - Proper permissions on nba-props-platform project
# ============================================================================

set -euo pipefail

PROJECT_ID="nba-props-platform"
DATASET="nba_monitoring"
LOCATION="us-east1"
VIEWS_DIR="../../bigquery_views"

echo "================================================================"
echo "Pipeline Health Dashboard - View Deployment"
echo "================================================================"
echo "Project: ${PROJECT_ID}"
echo "Dataset: ${DATASET}"
echo "Location: ${LOCATION}"
echo ""

# ============================================================================
# 1. Create dataset (if not exists)
# ============================================================================
echo "Checking if dataset exists..."

if bq ls --project_id="${PROJECT_ID}" "${DATASET}" > /dev/null 2>&1; then
  echo "✓ Dataset ${DATASET} already exists"
else
  echo "Creating dataset ${DATASET}..."
  bq mk \
    --dataset \
    --project_id="${PROJECT_ID}" \
    --location="${LOCATION}" \
    --description="Pipeline health monitoring views and metrics" \
    --label=team:data-engineering \
    --label=purpose:monitoring \
    "${DATASET}"
  echo "✓ Dataset created"
fi

echo ""

# ============================================================================
# 2. Deploy views
# ============================================================================
echo "Deploying monitoring views..."

VIEWS=(
  "pipeline_health_summary"
  "processor_error_summary"
  "prediction_coverage_metrics"
  "pipeline_latency_metrics"
)

for view in "${VIEWS[@]}"; do
  echo ""
  echo "Deploying view: ${view}..."

  VIEW_FILE="${VIEWS_DIR}/${view}.sql"

  if [ ! -f "${VIEW_FILE}" ]; then
    echo "ERROR: View file not found: ${VIEW_FILE}"
    exit 1
  fi

  if bq query \
    --use_legacy_sql=false \
    --project_id="${PROJECT_ID}" \
    < "${VIEW_FILE}"; then
    echo "✓ View ${view} deployed successfully"
  else
    echo "ERROR: Failed to deploy view ${view}"
    exit 1
  fi
done

echo ""
echo "================================================================"
echo "✓ All views deployed successfully!"
echo ""
echo "Deployed views:"
for view in "${VIEWS[@]}"; do
  echo "  - ${PROJECT_ID}.${DATASET}.${view}"
done
echo ""
echo "Next steps:"
echo "  1. Test views: bq query 'SELECT * FROM ${PROJECT_ID}.${DATASET}.pipeline_health_summary LIMIT 10'"
echo "  2. Set up scheduled queries: ./scheduled_queries_setup.sh"
echo "  3. Import Cloud Monitoring dashboard: gcloud monitoring dashboards create --config-from-file=pipeline_health_dashboard.json"
echo "  4. Review deployment guide: cat README.md"
echo "================================================================"
