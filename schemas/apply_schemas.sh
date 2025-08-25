#!/bin/bash
# Apply all BigQuery schemas for NBA processors

set -e  # Exit on error

# Configuration
PROJECT_ID=${GCP_PROJECT_ID:-"nba-props-platform"}
LOCATION="us-west2"

echo "=========================================="
echo "Applying BigQuery schemas"
echo "Project: $PROJECT_ID"
echo "Location: $LOCATION"
echo "=========================================="

# Function to run SQL file
run_sql() {
    local sql_file=$1
    local description=$2
    
    echo ""
    echo "➤ $description"
    echo "  File: $sql_file"
    
    if [ -f "$sql_file" ]; then
        bq query \
            --project_id="$PROJECT_ID" \
            --location="$LOCATION" \
            --use_legacy_sql=false \
            < "$sql_file"
        
        if [ $? -eq 0 ]; then
            echo "  ✓ Success"
        else
            echo "  ✗ Failed"
            exit 1
        fi
    else
        echo "  ✗ File not found: $sql_file"
        exit 1
    fi
}

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Apply schemas in order
echo ""
echo "Step 1: Creating datasets..."
run_sql "$SCRIPT_DIR/bigquery/datasets.sql" "Creating datasets"

echo ""
echo "Step 2: Creating processor tables..."
run_sql "$SCRIPT_DIR/bigquery/processing_tables.sql" "Creating processing tables"

echo ""
echo "Step 3: Creating Basketball Reference tables..."
run_sql "$SCRIPT_DIR/bigquery/br_roster_tables.sql" "Creating BR roster tables"

# Add other source tables as needed
# run_sql "$SCRIPT_DIR/bigquery/bdl_tables.sql" "Creating Ball Don't Lie tables"
# run_sql "$SCRIPT_DIR/bigquery/nbac_tables.sql" "Creating NBA.com tables"
# run_sql "$SCRIPT_DIR/bigquery/oddsa_tables.sql" "Creating Odds API tables"

echo ""
echo "=========================================="
echo "✓ All schemas applied successfully!"
echo "=========================================="
echo ""
echo "To verify:"
echo "  bq ls --project_id=$PROJECT_ID"
echo "  bq ls --project_id=$PROJECT_ID nba_raw"
echo "  bq ls --project_id=$PROJECT_ID nba_processing"