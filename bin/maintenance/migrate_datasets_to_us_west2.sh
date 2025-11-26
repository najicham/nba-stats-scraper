#!/bin/bash
# ============================================================================
# migrate_datasets_to_us_west2.sh
# Migrate BigQuery datasets from US multi-region to us-west2
# ============================================================================
#
# BigQuery doesn't support moving datasets between regions directly.
# This script:
# 1. Creates new datasets in us-west2 with _new suffix
# 2. Copies tables via GCS export/import
# 3. Recreates views
# 4. Verifies data integrity
#
# After verification, manually:
# 5. Delete old datasets (or rename to _old)
# 6. Rename new datasets (remove _new suffix)
#
# Usage:
#   ./migrate_datasets_to_us_west2.sh [--dry-run] [--dataset DATASET_NAME]
#
# ============================================================================

set -e

PROJECT_ID="nba-props-platform"
TARGET_LOCATION="us-west2"
GCS_BUCKET="gs://nba-props-platform-temp-migration"

# Datasets to migrate (currently in US multi-region)
DATASETS_TO_MIGRATE=(
    "nba_analytics"
    "nba_precompute"
    "nba_predictions"
    "nba_reference"
)

DRY_RUN=false
SINGLE_DATASET=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --dataset)
            SINGLE_DATASET="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

run_cmd() {
    if [ "$DRY_RUN" = true ]; then
        echo "[DRY-RUN] $1"
    else
        log "Running: $1"
        eval "$1"
    fi
}

# Create GCS bucket if it doesn't exist
create_bucket() {
    if ! gsutil ls "$GCS_BUCKET" &>/dev/null; then
        log "Creating GCS bucket: $GCS_BUCKET"
        run_cmd "gsutil mb -l $TARGET_LOCATION $GCS_BUCKET"
    fi
}

# Get list of tables (excluding views) in a dataset
get_tables() {
    local dataset=$1
    bq ls --format=json "$PROJECT_ID:$dataset" 2>/dev/null | \
        python3 -c "import json,sys; data=json.load(sys.stdin); print('\n'.join([t['tableReference']['tableId'] for t in data if t.get('type') == 'TABLE']))"
}

# Get list of views in a dataset
get_views() {
    local dataset=$1
    bq ls --format=json "$PROJECT_ID:$dataset" 2>/dev/null | \
        python3 -c "import json,sys; data=json.load(sys.stdin); print('\n'.join([t['tableReference']['tableId'] for t in data if t.get('type') == 'VIEW']))"
}

# Get view definition
get_view_definition() {
    local dataset=$1
    local view=$2
    bq show --format=prettyjson "$PROJECT_ID:$dataset.$view" 2>/dev/null | \
        python3 -c "import json,sys; data=json.load(sys.stdin); print(data.get('view', {}).get('query', ''))"
}

# Migrate a single dataset
migrate_dataset() {
    local dataset=$1
    local new_dataset="${dataset}_new"

    log "=========================================="
    log "Migrating dataset: $dataset -> $new_dataset"
    log "=========================================="

    # Check current location
    current_location=$(bq show --format=json "$PROJECT_ID:$dataset" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('location', 'unknown'))")
    log "Current location: $current_location"

    if [ "$current_location" = "$TARGET_LOCATION" ]; then
        log "Dataset already in $TARGET_LOCATION, skipping"
        return 0
    fi

    # Step 1: Create new dataset in target location
    log "Step 1: Creating new dataset in $TARGET_LOCATION"
    if bq show "$PROJECT_ID:$new_dataset" &>/dev/null; then
        log "Dataset $new_dataset already exists"
    else
        run_cmd "bq mk --location=$TARGET_LOCATION --dataset $PROJECT_ID:$new_dataset"
    fi

    # Step 2: Copy tables via GCS
    log "Step 2: Copying tables via GCS export/import"
    tables=$(get_tables "$dataset")

    for table in $tables; do
        log "  Copying table: $table"

        # Check if table has data
        num_rows=$(bq show --format=json "$PROJECT_ID:$dataset.$table" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('numRows', '0'))")

        if [ "$num_rows" = "0" ]; then
            log "    Table is empty, copying schema only"
            schema_file="/tmp/${dataset}_${table}_schema.json"
            bq show --schema "$PROJECT_ID:$dataset.$table" > "$schema_file"
            run_cmd "bq mk --table $PROJECT_ID:$new_dataset.$table $schema_file"
        else
            log "    Table has $num_rows rows, exporting to GCS"
            gcs_path="$GCS_BUCKET/$dataset/$table/*.json"

            # Export
            run_cmd "bq extract --destination_format=NEWLINE_DELIMITED_JSON $PROJECT_ID:$dataset.$table $gcs_path"

            # Get schema
            schema_file="/tmp/${dataset}_${table}_schema.json"
            bq show --schema "$PROJECT_ID:$dataset.$table" > "$schema_file"

            # Import
            run_cmd "bq load --source_format=NEWLINE_DELIMITED_JSON $PROJECT_ID:$new_dataset.$table $gcs_path $schema_file"

            # Verify row count
            new_rows=$(bq show --format=json "$PROJECT_ID:$new_dataset.$table" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('numRows', '0'))")
            if [ "$num_rows" != "$new_rows" ]; then
                log "    WARNING: Row count mismatch! Original: $num_rows, New: $new_rows"
            else
                log "    Row count verified: $num_rows"
            fi
        fi
    done

    # Step 3: Recreate views
    log "Step 3: Recreating views"
    views=$(get_views "$dataset")

    for view in $views; do
        log "  Recreating view: $view"
        view_query=$(get_view_definition "$dataset" "$view")

        # Replace dataset references in view query
        updated_query=$(echo "$view_query" | sed "s/$dataset/$new_dataset/g")

        # Create view
        run_cmd "bq mk --use_legacy_sql=false --view=\"$updated_query\" $PROJECT_ID:$new_dataset.$view"
    done

    # Step 4: Verify
    log "Step 4: Verification"
    orig_table_count=$(get_tables "$dataset" | wc -l)
    new_table_count=$(get_tables "$new_dataset" | wc -l)
    orig_view_count=$(get_views "$dataset" | wc -l)
    new_view_count=$(get_views "$new_dataset" | wc -l)

    log "  Original: $orig_table_count tables, $orig_view_count views"
    log "  New:      $new_table_count tables, $new_view_count views"

    if [ "$orig_table_count" = "$new_table_count" ] && [ "$orig_view_count" = "$new_view_count" ]; then
        log "  ✅ Migration verified!"
    else
        log "  ❌ Migration verification failed!"
        return 1
    fi

    log "Dataset $dataset migrated successfully"
    log ""
}

# Main
main() {
    log "BigQuery Dataset Migration to us-west2"
    log "========================================"

    if [ "$DRY_RUN" = true ]; then
        log "DRY RUN MODE - No changes will be made"
    fi

    # Create bucket
    create_bucket

    # Migrate datasets
    if [ -n "$SINGLE_DATASET" ]; then
        migrate_dataset "$SINGLE_DATASET"
    else
        for dataset in "${DATASETS_TO_MIGRATE[@]}"; do
            migrate_dataset "$dataset"
        done
    fi

    log ""
    log "========================================"
    log "Migration complete!"
    log ""
    log "Next steps:"
    log "1. Verify data in *_new datasets"
    log "2. Update code to reference new datasets (or rename)"
    log "3. Delete old datasets after verification"
    log "========================================"
}

main
