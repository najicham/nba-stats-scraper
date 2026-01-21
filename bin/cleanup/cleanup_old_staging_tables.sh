#!/bin/bash
# cleanup_old_staging_tables.sh - Clean up orphaned staging tables
#
# Staging tables are temporary tables created during prediction batch consolidation.
# They should be deleted after consolidation completes, but sometimes fail to cleanup
# due to errors or interrupted processes.
#
# This script:
# 1. Finds all staging tables older than retention period (default: 7 days)
# 2. Deletes them to free up storage and table quota
# 3. Logs deletions for audit trail
#
# Usage: ./bin/cleanup/cleanup_old_staging_tables.sh [--retention-days=7] [--dry-run]
#
# Schedule: Run daily via cron or Cloud Scheduler
# Example cron: 0 3 * * * /path/to/cleanup_old_staging_tables.sh

set -euo pipefail

PROJECT_ID="nba-props-platform"
DATASET="nba_predictions"
RETENTION_DAYS=7
DRY_RUN=false
LOG_FILE="/tmp/staging_table_cleanup_$(date +%Y%m%d_%H%M%S).log"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --retention-days=*)
            RETENTION_DAYS="${1#*=}"
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--retention-days=7] [--dry-run]"
            exit 1
            ;;
    esac
done

echo "========================================"
echo "Staging Table Cleanup"
echo "========================================"
echo "Project: $PROJECT_ID"
echo "Dataset: $DATASET"
echo "Retention: $RETENTION_DAYS days"
echo "Dry Run: $DRY_RUN"
echo "Log File: $LOG_FILE"
echo ""

# Start logging
{
    echo "Cleanup started: $(date)"
    echo "Parameters: retention=$RETENTION_DAYS days, dry_run=$DRY_RUN"
    echo ""
} > "$LOG_FILE"

# Get current timestamp for age calculation
CURRENT_TIMESTAMP=$(date +%s)

# Track counts
TOTAL_STAGING_TABLES=0
TABLES_TO_DELETE=0
TABLES_DELETED=0
ERRORS=0

echo "Scanning for staging tables..."

# List all tables in the dataset
TABLES=$(bq ls --project_id=$PROJECT_ID --max_results=1000 --format=json $DATASET 2>/dev/null | jq -r '.[] | select(.type == "TABLE") | select(.tableReference.tableId | startswith("_staging_")) | "\(.tableReference.tableId) \(.creationTime)"')

if [ -z "$TABLES" ]; then
    echo "✅ No staging tables found"
    {
        echo "No staging tables found"
        echo "Cleanup completed: $(date)"
    } >> "$LOG_FILE"
    exit 0
fi

echo "$TABLES" | while read -r table_name creation_time; do
    TOTAL_STAGING_TABLES=$((TOTAL_STAGING_TABLES + 1))

    # Convert creation_time (milliseconds since epoch) to seconds
    creation_seconds=$((creation_time / 1000))

    # Calculate age in days
    age_seconds=$((CURRENT_TIMESTAMP - creation_seconds))
    age_days=$((age_seconds / 86400))

    # Convert timestamps to readable format
    created_date=$(date -d "@$creation_seconds" "+%Y-%m-%d %H:%M:%S")

    if [ $age_days -gt $RETENTION_DAYS ]; then
        TABLES_TO_DELETE=$((TABLES_TO_DELETE + 1))

        echo "Found old table: $table_name"
        echo "  Created: $created_date"
        echo "  Age: $age_days days"

        {
            echo "Table: $table_name"
            echo "  Created: $created_date"
            echo "  Age: $age_days days"
        } >> "$LOG_FILE"

        if [ "$DRY_RUN" = false ]; then
            echo "  Deleting..."

            if bq rm -f --project_id=$PROJECT_ID ${DATASET}.${table_name} 2>&1 | tee -a "$LOG_FILE"; then
                echo "  ✅ Deleted successfully"
                echo "  Status: DELETED" >> "$LOG_FILE"
                TABLES_DELETED=$((TABLES_DELETED + 1))
            else
                echo "  ❌ Failed to delete"
                echo "  Status: ERROR" >> "$LOG_FILE"
                ERRORS=$((ERRORS + 1))
            fi
        else
            echo "  [DRY RUN] Would delete"
            echo "  Status: DRY_RUN" >> "$LOG_FILE"
        fi

        echo ""
    else
        echo "Keeping recent table: $table_name (age: $age_days days)"
    fi
done

# Print summary
echo "========================================"
echo "Cleanup Summary"
echo "========================================"
echo "Total staging tables scanned: $TOTAL_STAGING_TABLES"
echo "Tables older than $RETENTION_DAYS days: $TABLES_TO_DELETE"

if [ "$DRY_RUN" = false ]; then
    echo "Tables successfully deleted: $TABLES_DELETED"
    echo "Errors: $ERRORS"
else
    echo "Mode: DRY RUN (no tables deleted)"
fi

echo ""
echo "Log file: $LOG_FILE"

# Write summary to log
{
    echo ""
    echo "Summary:"
    echo "  Total staging tables: $TOTAL_STAGING_TABLES"
    echo "  Tables to delete: $TABLES_TO_DELETE"
    echo "  Tables deleted: $TABLES_DELETED"
    echo "  Errors: $ERRORS"
    echo ""
    echo "Cleanup completed: $(date)"
} >> "$LOG_FILE"

# Exit with error if any deletions failed
if [ $ERRORS -gt 0 ] && [ "$DRY_RUN" = false ]; then
    echo "⚠️  Warning: $ERRORS table deletions failed"
    exit 1
fi

# Success
if [ "$DRY_RUN" = false ]; then
    if [ $TABLES_DELETED -gt 0 ]; then
        echo "✅ Cleanup complete: Deleted $TABLES_DELETED old staging tables"
    else
        echo "✅ No cleanup needed: All staging tables are within retention period"
    fi
else
    echo "✅ Dry run complete: Would delete $TABLES_TO_DELETE tables"
fi

exit 0
