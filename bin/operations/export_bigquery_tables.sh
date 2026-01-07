#!/bin/bash
###############################################################################
# BigQuery Table Export Script
#
# Exports critical BigQuery tables to GCS for disaster recovery
# Run daily via Cloud Scheduler or cron
#
# Usage:
#   ./bin/operations/export_bigquery_tables.sh [backup-type]
#
# Backup Types:
#   daily   - Export latest data only (default)
#   full    - Export all historical data
#   tables  - Export specific tables (use --tables flag)
#
# Examples:
#   ./bin/operations/export_bigquery_tables.sh daily
#   ./bin/operations/export_bigquery_tables.sh full
#   ./bin/operations/export_bigquery_tables.sh tables player_game_summary
#
# Created: 2026-01-03 (Session 6)
###############################################################################

set -euo pipefail

# Configuration
PROJECT_ID="nba-props-platform"
BACKUP_BUCKET="gs://nba-bigquery-backups"
DATE=$(date +%Y%m%d)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_TYPE="${1:-daily}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Critical tables to backup
PHASE3_TABLES=(
    "nba_analytics.player_game_summary"
    "nba_analytics.team_offense_game_summary"
    "nba_analytics.team_defense_game_summary"
    "nba_analytics.upcoming_player_game_context"
    "nba_analytics.upcoming_team_game_context"
)

PHASE4_TABLES=(
    "nba_precompute.player_composite_factors"
    "nba_precompute.player_shot_zone_analysis"
    "nba_precompute.team_defense_zone_analysis"
    "nba_precompute.player_daily_cache"
)

ORCHESTRATION_TABLES=(
    "nba_orchestration.processor_output_validation"
    "nba_orchestration.workflow_decisions"
)

###############################################################################
# Functions
###############################################################################

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1"
}

export_table() {
    local table_full_name=$1
    local export_path=$2
    local description=$3

    log "Exporting $description: $table_full_name"

    # Extract dataset and table name
    local dataset=$(echo "$table_full_name" | cut -d'.' -f1)
    local table_name=$(echo "$table_full_name" | cut -d'.' -f2)

    # Check if table exists
    if ! bq show "${PROJECT_ID}:${table_full_name}" >/dev/null 2>&1; then
        warn "Table not found: $table_full_name (skipping)"
        return 1
    fi

    # Get row count
    local row_count=$(bq query --use_legacy_sql=false --format=csv --max_rows=1 \
        "SELECT COUNT(*) as cnt FROM \`${PROJECT_ID}.${table_full_name}\`" 2>/dev/null | tail -n1)

    log "  Row count: $row_count"

    # Export to GCS (AVRO format for best compression + schema preservation)
    if bq extract \
        --destination_format=AVRO \
        --compression=SNAPPY \
        "${PROJECT_ID}:${table_full_name}" \
        "${export_path}/*.avro" 2>&1 | tee /tmp/bq_export_${table_name}.log; then

        log "  ✓ Export successful: $export_path"

        # Write metadata
        cat > /tmp/export_metadata_${table_name}.json <<EOF
{
    "table": "${table_full_name}",
    "export_date": "$(date -Iseconds)",
    "row_count": ${row_count},
    "export_path": "${export_path}",
    "format": "AVRO",
    "compression": "SNAPPY"
}
EOF

        # Upload metadata
        gsutil cp /tmp/export_metadata_${table_name}.json "${export_path}/_metadata.json"

        return 0
    else
        error "  ✗ Export failed: $table_full_name"
        return 1
    fi
}

create_backup_bucket() {
    # Check if bucket exists
    if gsutil ls "$BACKUP_BUCKET" >/dev/null 2>&1; then
        log "Backup bucket exists: $BACKUP_BUCKET"
    else
        log "Creating backup bucket: $BACKUP_BUCKET"
        gsutil mb -l US -p "$PROJECT_ID" "$BACKUP_BUCKET"

        # Set lifecycle policy (delete after 90 days)
        cat > /tmp/lifecycle.json <<EOF
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "Delete"},
        "condition": {"age": 90}
      }
    ]
  }
}
EOF
        gsutil lifecycle set /tmp/lifecycle.json "$BACKUP_BUCKET"
        log "Lifecycle policy set: delete after 90 days"
    fi
}

###############################################################################
# Main Export Logic
###############################################################################

main() {
    log "==================================================================="
    log "BigQuery Backup Export - Type: $BACKUP_TYPE"
    log "==================================================================="

    # Ensure backup bucket exists
    create_backup_bucket

    local export_base_path="${BACKUP_BUCKET}/${BACKUP_TYPE}/${DATE}"
    local success_count=0
    local failure_count=0

    log "Export base path: $export_base_path"
    echo ""

    # Export Phase 3 tables
    log "--- Phase 3: Analytics Tables ---"
    for table in "${PHASE3_TABLES[@]}"; do
        table_name=$(echo "$table" | cut -d'.' -f2)
        export_path="${export_base_path}/phase3/${table_name}"

        if export_table "$table" "$export_path" "Phase 3 - $table_name"; then
            ((success_count++))
        else
            ((failure_count++))
        fi
        echo ""
    done

    # Export Phase 4 tables
    log "--- Phase 4: Precompute Tables ---"
    for table in "${PHASE4_TABLES[@]}"; do
        table_name=$(echo "$table" | cut -d'.' -f2)
        export_path="${export_base_path}/phase4/${table_name}"

        if export_table "$table" "$export_path" "Phase 4 - $table_name"; then
            ((success_count++))
        else
            ((failure_count++))
        fi
        echo ""
    done

    # Export orchestration tables (if they exist)
    log "--- Orchestration Tables ---"
    for table in "${ORCHESTRATION_TABLES[@]}"; do
        table_name=$(echo "$table" | cut -d'.' -f2)
        export_path="${export_base_path}/orchestration/${table_name}"

        if export_table "$table" "$export_path" "Orchestration - $table_name"; then
            ((success_count++))
        else
            ((failure_count++))
        fi
        echo ""
    done

    # Summary
    log "==================================================================="
    log "Backup Summary"
    log "==================================================================="
    log "Successful exports: $success_count"
    log "Failed exports: $failure_count"
    log "Backup location: $export_base_path"

    # Create index file
    cat > /tmp/backup_index.txt <<EOF
NBA Stats Scraper - BigQuery Backup
====================================
Date: $(date)
Backup Type: $BACKUP_TYPE
Project: $PROJECT_ID
Location: $export_base_path

Tables Exported: $success_count
Tables Failed: $failure_count

To restore from this backup:
    # Restore specific table:
    bq load --source_format=AVRO --replace \\
      ${PROJECT_ID}:nba_analytics.player_game_summary \\
      ${export_base_path}/phase3/player_game_summary/*.avro

    # List all backups:
    gsutil ls ${BACKUP_BUCKET}/${BACKUP_TYPE}/

For complete recovery procedures, see:
    docs/02-operations/disaster-recovery-runbook.md
EOF

    gsutil cp /tmp/backup_index.txt "${export_base_path}/_BACKUP_INDEX.txt"

    if [[ $failure_count -eq 0 ]]; then
        log "✓ All exports completed successfully"
        exit 0
    else
        warn "Some exports failed (see logs above)"
        exit 1
    fi
}

# Run main
main "$@"
