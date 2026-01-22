#!/bin/bash
# Deploy phase_boundary_validations table to BigQuery
# Part of: Robustness Improvements - Week 3-4 Phase Boundary Validation
# Created: January 21, 2026

set -e  # Exit on error

# Configuration
PROJECT_ID="${PROJECT_ID:-nba-props-platform}"
DATASET="nba_monitoring"
TABLE="phase_boundary_validations"
SCHEMA_FILE="phase_boundary_validations_schema.json"
SQL_FILE="create_phase_boundary_validations_table.sql"

echo "=================================="
echo "BigQuery Table Deployment"
echo "=================================="
echo "Project: $PROJECT_ID"
echo "Dataset: $DATASET"
echo "Table: $TABLE"
echo "=================================="

# Change to script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check if dataset exists, create if not
echo "Checking if dataset $DATASET exists..."
if ! bq ls --project_id="$PROJECT_ID" "$DATASET" &>/dev/null; then
  echo "Dataset $DATASET does not exist. Creating..."
  bq mk \
    --project_id="$PROJECT_ID" \
    --dataset \
    --location=US \
    --description="NBA pipeline monitoring and validation data" \
    --label=component:monitoring \
    --label=project:robustness-improvements \
    "$DATASET"
  echo "✓ Dataset created successfully"
else
  echo "✓ Dataset $DATASET already exists"
fi

# Check if table exists
echo ""
echo "Checking if table $DATASET.$TABLE exists..."
if bq show --project_id="$PROJECT_ID" "$DATASET.$TABLE" &>/dev/null; then
  echo "⚠ Table $DATASET.$TABLE already exists"
  read -p "Do you want to drop and recreate it? (y/N): " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Dropping existing table..."
    bq rm -f --project_id="$PROJECT_ID" "$DATASET.$TABLE"
    echo "✓ Table dropped"
  else
    echo "Skipping table creation. Exiting."
    exit 0
  fi
fi

# Create table using schema file
echo ""
echo "Creating table $DATASET.$TABLE..."
bq mk \
  --project_id="$PROJECT_ID" \
  --table \
  --time_partitioning_field=game_date \
  --time_partitioning_type=DAY \
  --clustering_fields=phase_name,is_valid \
  --description="Phase boundary validation results for pipeline quality gates" \
  --label=component:validation \
  --label=project:robustness-improvements \
  "$DATASET.$TABLE" \
  "$SCHEMA_FILE"

if [ $? -eq 0 ]; then
  echo "✓ Table created successfully"
else
  echo "✗ Table creation failed"
  exit 1
fi

# Verify table creation
echo ""
echo "Verifying table structure..."
bq show --project_id="$PROJECT_ID" "$DATASET.$TABLE"

echo ""
echo "=================================="
echo "Deployment Summary"
echo "=================================="
echo "✓ Dataset: $DATASET"
echo "✓ Table: $TABLE"
echo "✓ Partitioning: By game_date (DAY)"
echo "✓ Clustering: phase_name, is_valid"
echo "=================================="
echo ""
echo "Table is ready for use!"
echo ""
echo "Next steps:"
echo "1. Update Cloud Functions with environment variable:"
echo "   PHASE_VALIDATION_ENABLED=true"
echo ""
echo "2. Deploy phase transition functions:"
echo "   - phase1_to_phase2 (WARNING mode)"
echo "   - phase2_to_phase3 (WARNING mode)"
echo "   - phase3_to_phase4 (BLOCKING mode)"
echo ""
echo "3. Monitor validation logs:"
echo "   bq query --project_id=$PROJECT_ID --use_legacy_sql=false \\"
echo "     'SELECT * FROM $DATASET.$TABLE ORDER BY timestamp DESC LIMIT 10'"
echo ""
