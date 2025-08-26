#!/bin/bash
# File: processor_backfill/odds_api_props/setup.sh
#
# Setup script for Odds API Props Processor
# Creates necessary directories, files, and BigQuery tables

set -e

PROJECT_ID=${GCP_PROJECT_ID:-"nba-props-platform"}

echo "========================================"
echo "Setting up Odds API Props Processor"
echo "========================================"
echo "Project: $PROJECT_ID"
echo ""

# Create directory structure
echo "Creating directory structure..."
mkdir -p processors/odds_api
mkdir -p processors/utils
mkdir -p processor_backfill/odds_api_props
mkdir -p scripts
mkdir -p schemas/bigquery
mkdir -p bin/processor_backfill
mkdir -p bin/deployment
mkdir -p docker
mkdir -p shared

echo "✓ Directories created"

# Create __init__.py files if they don't exist
echo "Creating Python package files..."
touch processors/__init__.py
touch processors/odds_api/__init__.py
touch processors/utils/__init__.py

echo "✓ Python packages initialized"

# Check for requirements files
echo "Checking requirements files..."
if [[ ! -f "shared/requirements.txt" ]]; then
    echo "⚠️  Warning: shared/requirements.txt not found"
    echo "   The Dockerfile expects requirements at:"
    echo "   - shared/requirements.txt"
    echo "   - processors/requirements_processors.txt"
fi
if [[ ! -f "processors/requirements_processors.txt" ]]; then
    echo "⚠️  Warning: processors/requirements_processors.txt not found"
fi

echo "✓ Python packages initialized"

# Apply BigQuery schema
echo ""
echo "Applying BigQuery schema..."
echo "Creating datasets if they don't exist..."

# Create datasets
bq mk --dataset --location=US --project_id=$PROJECT_ID nba_raw 2>/dev/null || echo "Dataset nba_raw already exists"
bq mk --dataset --location=US --project_id=$PROJECT_ID nba_processing 2>/dev/null || echo "Dataset nba_processing already exists"

# Apply the schema
echo "Creating odds_api_player_points_props table..."
bq query --use_legacy_sql=false --project_id=$PROJECT_ID < schemas/bigquery/odds_api_props_tables.sql

echo "✓ BigQuery schema applied"

# Create service account if it doesn't exist
echo ""
echo "Checking service account..."
SERVICE_ACCOUNT="odds-api-props-backfill@${PROJECT_ID}.iam.gserviceaccount.com"

if gcloud iam service-accounts describe $SERVICE_ACCOUNT --project=$PROJECT_ID >/dev/null 2>&1; then
    echo "✓ Service account already exists"
else
    echo "Creating service account..."
    gcloud iam service-accounts create odds-api-props-backfill \
        --display-name="Odds API Props Backfill Service Account" \
        --project=$PROJECT_ID
    
    # Grant necessary permissions
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:$SERVICE_ACCOUNT" \
        --role="roles/bigquery.dataEditor"
    
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:$SERVICE_ACCOUNT" \
        --role="roles/storage.objectViewer"
    
    echo "✓ Service account created and configured"
fi

# Test with a sample file
echo ""
echo "Testing processor with sample file..."
SAMPLE_FILE="gs://nba-scraped-data/odds-api/player-props-history/2023-10-24/fd55db2fa9ee5be1f108be5151e2ecb0-LALDEN/20250812_035909-snap-2130.json"

if python scripts/test_odds_api_props_processor.py --gcs-file "$SAMPLE_FILE"; then
    echo "✓ Processor test successful"
else
    echo "✗ Processor test failed - please check the error messages above"
    exit 1
fi

# Summary
echo ""
echo "========================================"
echo "Setup Complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "1. Test with more files:"
echo "   python scripts/test_odds_api_props_processor.py --gcs-file <file> --load"
echo ""
echo "2. Run local backfill for a single day:"
echo "   python processor_backfill/odds_api_props/odds_api_props_backfill_job.py --dates 2023-10-24"
echo ""
echo "3. Deploy to Cloud Run:"
echo "   ./bin/deployment/deploy_processor_backfill_job.sh odds_api_props"
echo ""
echo "4. Run full backfill:"
echo "   gcloud run jobs execute odds-api-props-backfill --region=us-central1"
echo ""
echo "5. Monitor progress:"
echo "   ./bin/processor_backfill/odds_api_props_backfill_monitor.sh"
echo ""
echo "BigQuery table: ${PROJECT_ID}.nba_raw.odds_api_player_points_props"