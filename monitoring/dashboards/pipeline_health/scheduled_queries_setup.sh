#!/bin/bash
# ============================================================================
# Script: scheduled_queries_setup.sh
# Purpose: Create scheduled queries to materialize pipeline health views
# ============================================================================
# This script sets up hourly scheduled queries that populate materialized
# tables for fast dashboard loading and historical tracking.
#
# Usage:
#   ./scheduled_queries_setup.sh
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - BigQuery Data Transfer Service enabled
#   - nba_monitoring dataset exists
#   - Source views deployed
# ============================================================================

set -euo pipefail

PROJECT_ID="nba-props-platform"
DATASET="nba_monitoring"
LOCATION="us-east1"

echo "Setting up scheduled queries for pipeline health dashboard..."

# ============================================================================
# 1. Pipeline Health Summary (hourly)
# ============================================================================
echo "Creating scheduled query: pipeline_health_summary_materialized"

bq query \
  --use_legacy_sql=false \
  --project_id="${PROJECT_ID}" \
  --display_name="Pipeline Health Summary - Hourly Refresh" \
  --schedule="every 1 hours" \
  --destination_table="${PROJECT_ID}.${DATASET}.pipeline_health_summary_materialized" \
  --replace=true \
  --time_partitioning_field=last_updated \
  --time_partitioning_type=DAY \
  --time_partitioning_expiration=2592000 \
<<'SQL'
SELECT * FROM `nba-props-platform.nba_monitoring.pipeline_health_summary`
SQL

echo "✓ Pipeline health summary scheduled query created"

# ============================================================================
# 2. Processor Error Summary (hourly)
# ============================================================================
echo "Creating scheduled query: processor_error_summary_materialized"

bq query \
  --use_legacy_sql=false \
  --project_id="${PROJECT_ID}" \
  --display_name="Processor Error Summary - Hourly Refresh" \
  --schedule="every 1 hours" \
  --destination_table="${PROJECT_ID}.${DATASET}.processor_error_summary_materialized" \
  --replace=true \
  --time_partitioning_field=last_updated \
  --time_partitioning_type=DAY \
  --time_partitioning_expiration=2592000 \
<<'SQL'
SELECT * FROM `nba-props-platform.nba_monitoring.processor_error_summary`
SQL

echo "✓ Processor error summary scheduled query created"

# ============================================================================
# 3. Prediction Coverage Metrics (hourly)
# ============================================================================
echo "Creating scheduled query: prediction_coverage_metrics_materialized"

bq query \
  --use_legacy_sql=false \
  --project_id="${PROJECT_ID}" \
  --display_name="Prediction Coverage Metrics - Hourly Refresh" \
  --schedule="every 1 hours" \
  --destination_table="${PROJECT_ID}.${DATASET}.prediction_coverage_metrics_materialized" \
  --replace=true \
  --time_partitioning_field=game_date \
  --time_partitioning_type=DAY \
  --time_partitioning_expiration=2592000 \
<<'SQL'
SELECT * FROM `nba-props-platform.nba_monitoring.prediction_coverage_metrics`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
SQL

echo "✓ Prediction coverage metrics scheduled query created"

# ============================================================================
# 4. Pipeline Latency Metrics (hourly)
# ============================================================================
echo "Creating scheduled query: pipeline_latency_metrics_materialized"

bq query \
  --use_legacy_sql=false \
  --project_id="${PROJECT_ID}" \
  --display_name="Pipeline Latency Metrics - Hourly Refresh" \
  --schedule="every 1 hours" \
  --destination_table="${PROJECT_ID}.${DATASET}.pipeline_latency_metrics_materialized" \
  --replace=true \
  --time_partitioning_field=game_date \
  --time_partitioning_type=DAY \
  --time_partitioning_expiration=2592000 \
<<'SQL'
SELECT * FROM `nba-props-platform.nba_monitoring.pipeline_latency_metrics`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
SQL

echo "✓ Pipeline latency metrics scheduled query created"

# ============================================================================
# Verify scheduled queries
# ============================================================================
echo ""
echo "Verifying scheduled queries..."
bq ls --transfer_config --project_id="${PROJECT_ID}" | grep "Pipeline Health\|Processor Error\|Prediction Coverage\|Pipeline Latency"

echo ""
echo "================================================================"
echo "✓ All scheduled queries created successfully!"
echo ""
echo "Materialized tables:"
echo "  - ${PROJECT_ID}.${DATASET}.pipeline_health_summary_materialized"
echo "  - ${PROJECT_ID}.${DATASET}.processor_error_summary_materialized"
echo "  - ${PROJECT_ID}.${DATASET}.prediction_coverage_metrics_materialized"
echo "  - ${PROJECT_ID}.${DATASET}.pipeline_latency_metrics_materialized"
echo ""
echo "Refresh schedule: Every 1 hour"
echo "Retention: 30 days"
echo ""
echo "Next steps:"
echo "  1. Wait for first scheduled run (within 1 hour)"
echo "  2. Verify data population: bq query 'SELECT * FROM ${PROJECT_ID}.${DATASET}.pipeline_health_summary_materialized LIMIT 10'"
echo "  3. Update dashboard to use materialized tables"
echo "  4. Set up Cloud Monitoring alerts"
echo "================================================================"
