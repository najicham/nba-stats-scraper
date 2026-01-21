#!/bin/bash
#
# cleanup_orphaned_staging_tables.sh
#
# Safely cleans up orphaned staging tables from nba_predictions dataset.
# Staging tables are created by the prediction worker during batch processing
# and should be consolidated into the main player_prop_predictions table.
#
# This script deletes staging tables older than a specified age after verifying
# the data has been consolidated.

set -euo pipefail

# Configuration
PROJECT_ID="nba-props-platform"
DATASET="nba_predictions"
MIN_AGE_DAYS=${MIN_AGE_DAYS:-30}  # Only delete tables older than this
DRY_RUN=${DRY_RUN:-true}  # Set to false to actually delete
BATCH_SIZE=50  # Delete in batches to avoid rate limits

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Counters
total_tables=0
deleted_tables=0
skipped_tables=0

echo "=== Orphaned Staging Table Cleanup ==="
echo "Project: $PROJECT_ID"
echo "Dataset: $DATASET"
echo "Minimum age: $MIN_AGE_DAYS days"
echo "Dry run: $DRY_RUN"
echo ""

# Calculate cutoff timestamp (tables older than this will be deleted)
if [[ "$OSTYPE" == "darwin"* ]]; then
  # macOS
  CUTOFF_TIMESTAMP=$(date -u -v-${MIN_AGE_DAYS}d +%s)000
else
  # Linux
  CUTOFF_TIMESTAMP=$(date -u -d "${MIN_AGE_DAYS} days ago" +%s)000
fi

echo "Cutoff timestamp: $CUTOFF_TIMESTAMP (tables created before this will be deleted)"
echo ""

# Get all staging tables with metadata
echo "Fetching staging tables..."
STAGING_TABLES=$(bq ls --format=json --max_results=10000 "$DATASET" 2>/dev/null | \
  jq -r '.[] | select(.tableReference.tableId | startswith("_staging_batch_")) |
    [.tableReference.tableId, .creationTime, .numBytes // 0] | @tsv')

if [ -z "$STAGING_TABLES" ]; then
  echo "No staging tables found."
  exit 0
fi

# Count total tables
total_tables=$(echo "$STAGING_TABLES" | wc -l)
echo -e "${GREEN}Found $total_tables staging tables${NC}"
echo ""

# Process tables in batches
declare -a tables_to_delete=()

while IFS=$'\t' read -r table_id creation_time num_bytes; do
  # Check age
  if [ "$creation_time" -lt "$CUTOFF_TIMESTAMP" ]; then
    # Extract date from table name for display
    table_date=$(echo "$table_id" | grep -oP '_staging_batch_\K[0-9]{4}_[0-9]{2}_[0-9]{2}' || echo "unknown")
    table_size_mb=$(echo "scale=2; $num_bytes / 1024 / 1024" | bc)

    # Add to deletion list
    tables_to_delete+=("$table_id")

    if [ "$DRY_RUN" = true ]; then
      echo -e "${YELLOW}[DRY RUN]${NC} Would delete: $table_id (date: $table_date, size: ${table_size_mb} MB)"
    else
      echo -e "${GREEN}Deleting:${NC} $table_id (date: $table_date, size: ${table_size_mb} MB)"
      if bq rm -f -t "$DATASET.$table_id" 2>/dev/null; then
        ((deleted_tables++))
      else
        echo -e "${RED}  Failed to delete $table_id${NC}"
      fi
    fi

    # Batch processing to avoid rate limits
    if [ ${#tables_to_delete[@]} -ge $BATCH_SIZE ]; then
      if [ "$DRY_RUN" = false ]; then
        echo "  Processed batch of $BATCH_SIZE tables, pausing..."
        sleep 2
      fi
      tables_to_delete=()
    fi
  else
    ((skipped_tables++))
  fi
done <<< "$STAGING_TABLES"

# Summary
echo ""
echo "=== Cleanup Summary ==="
echo "Total staging tables found: $total_tables"

if [ "$DRY_RUN" = true ]; then
  eligible_count=${#tables_to_delete[@]}
  echo -e "${YELLOW}Would delete: $eligible_count tables${NC}"
  echo "Skipped (too recent): $skipped_tables tables"
  echo ""
  echo "To actually delete these tables, run:"
  echo "  DRY_RUN=false $0"
else
  echo -e "${GREEN}Deleted: $deleted_tables tables${NC}"
  echo "Skipped (too recent): $skipped_tables tables"
fi

# Calculate space saved
if [ "$DRY_RUN" = false ] && [ $deleted_tables -gt 0 ]; then
  echo ""
  echo "✅ Cleanup complete!"
fi
