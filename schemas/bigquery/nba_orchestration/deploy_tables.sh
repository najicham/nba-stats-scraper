#!/bin/bash
# ============================================================================
# NBA Props Platform - nba_orchestration Dataset Deployment Script
# ============================================================================
# File: schemas/bigquery/nba_orchestration/deploy_tables.sh
# Purpose: Deploy all nba_orchestration tables for Phase 1 orchestration
# 
# Usage:
#   ./schemas/bigquery/nba_orchestration/deploy_tables.sh
#   ./schemas/bigquery/nba_orchestration/deploy_tables.sh --force  # Recreate existing tables
#
# Tables Created:
#   1. scraper_execution_log - Every scraper run (3-status tracking)
#   2. workflow_decisions - Controller evaluation decisions
#   3. daily_expected_schedule - Expected workflow schedule
#   4. cleanup_operations - Self-healing recovery operations
#
# Prerequisites:
#   - gcloud CLI configured
#   - bq command available
#   - GCP_PROJECT_ID environment variable (or uses default: nba-props-platform)
#   - Permissions to create BigQuery datasets and tables
#
# Version: 1.0
# Date: November 10, 2025
# ============================================================================

set -e  # Exit on error
set -u  # Exit on undefined variable

# ============================================================================
# CONFIGURATION
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"
DATASET="nba_orchestration"
LOCATION="US"
FORCE_RECREATE=false

# ANSI color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

log_header() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "$1"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
}

log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ ERROR: $1${NC}"
}

# ============================================================================
# ARGUMENT PARSING
# ============================================================================

while [[ $# -gt 0 ]]; do
    case $1 in
        --force)
            FORCE_RECREATE=true
            log_warning "Force recreate mode enabled - existing tables will be deleted"
            shift
            ;;
        --project)
            PROJECT_ID="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --force            Delete and recreate existing tables"
            echo "  --project PROJECT  Override GCP project ID"
            echo "  --help             Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                    # Create tables (skip if exist)"
            echo "  $0 --force            # Recreate all tables"
            echo "  $0 --project my-proj  # Use different project"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# ============================================================================
# MAIN DEPLOYMENT
# ============================================================================

log_header "📊 NBA Orchestration Dataset Deployment"
log_info "Project: $PROJECT_ID"
log_info "Dataset: $DATASET"
log_info "Location: $LOCATION"
echo ""

# Step 1: Ensure dataset exists
log_header "Step 1: Dataset Setup"
log_info "Checking if dataset exists..."

if ! bq ls --project_id="$PROJECT_ID" "$DATASET" &> /dev/null; then
    log_info "Creating dataset: $DATASET"
    bq mk \
        --dataset \
        --location="$LOCATION" \
        --description="Phase 1 orchestration and scraper execution logs. Tracks workflow decisions, scraper executions, expected schedules, and cleanup operations. Supports 3-status discovery mode (success/no_data/failed) and comprehensive source tracking." \
        "$PROJECT_ID:$DATASET"
    log_success "Dataset created successfully"
else
    log_success "Dataset already exists"
fi

# Step 2: Create tables
log_header "Step 2: Table Creation"

# Define tables array
declare -a tables=(
    "scraper_execution_log"
    "workflow_decisions"
    "daily_expected_schedule"
    "cleanup_operations"
)

# Create each table
for table in "${tables[@]}"; do
    log_header "Processing: $table"
    
    full_table_id="$PROJECT_ID:$DATASET.$table"
    
    # Check if table exists
    if bq show --project_id="$PROJECT_ID" "$DATASET.$table" &> /dev/null; then
        if [[ "$FORCE_RECREATE" == true ]]; then
            log_warning "Deleting existing table..."
            bq rm -f -t "$full_table_id"
            log_success "Table deleted"
        else
            log_warning "Table already exists (use --force to recreate)"
            echo ""
            continue
        fi
    fi
    
    # Table-specific SQL file
    sql_file="$SCRIPT_DIR/${table}.sql"
    
    if [[ ! -f "$sql_file" ]]; then
        log_error "SQL file not found: $sql_file"
        exit 1
    fi
    
    log_info "Creating table from: ${table}.sql"
    
    # Execute SQL file
    # Note: bq query doesn't support CREATE TABLE from file directly,
    # so we need to construct bq mk command with parameters
    
    case "$table" in
        "scraper_execution_log")
            log_info "Creating scraper_execution_log with partitioning and clustering..."
            bq query \
                --project_id="$PROJECT_ID" \
                --use_legacy_sql=false \
                < "$sql_file" || {
                    log_error "Failed to create table: $table"
                    exit 1
                }
            ;;
            
        "workflow_decisions")
            log_info "Creating workflow_decisions with partitioning and clustering..."
            bq query \
                --project_id="$PROJECT_ID" \
                --use_legacy_sql=false \
                < "$sql_file" || {
                    log_error "Failed to create table: $table"
                    exit 1
                }
            ;;
            
        "daily_expected_schedule")
            log_info "Creating daily_expected_schedule with partitioning and clustering..."
            bq query \
                --project_id="$PROJECT_ID" \
                --use_legacy_sql=false \
                < "$sql_file" || {
                    log_error "Failed to create table: $table"
                    exit 1
                }
            ;;
            
        "cleanup_operations")
            log_info "Creating cleanup_operations with partitioning and clustering..."
            bq query \
                --project_id="$PROJECT_ID" \
                --use_legacy_sql=false \
                < "$sql_file" || {
                    log_error "Failed to create table: $table"
                    exit 1
                }
            ;;
    esac
    
    # Verify table was created
    if bq show --project_id="$PROJECT_ID" "$DATASET.$table" &> /dev/null; then
        log_success "Table created successfully: $table"
        
        # Show table info
        log_info "Verifying table structure..."
        bq show "$full_table_id" | head -n 20
    else
        log_error "Table verification failed: $table"
        exit 1
    fi
    
    echo ""
done

# Step 3: Verify deployment
log_header "Step 3: Deployment Verification"

log_info "Listing all tables in $DATASET..."
bq ls --project_id="$PROJECT_ID" --max_results=10 "$DATASET"
echo ""

# Count tables
table_count=$(bq ls --project_id="$PROJECT_ID" --max_results=100 "$DATASET" | grep -c "TABLE" || true)
expected_count=4

if [[ "$table_count" -eq "$expected_count" ]]; then
    log_success "All $expected_count tables created successfully"
else
    log_warning "Expected $expected_count tables, found $table_count"
fi

# Step 4: Summary
log_header "🎉 Deployment Complete!"

echo "📊 Created Tables:"
for table in "${tables[@]}"; do
    echo "   ✅ $DATASET.$table"
done
echo ""

echo "🔍 Verify with:"
echo "   bq ls --project_id=$PROJECT_ID $DATASET"
echo ""

echo "📋 View schema:"
echo "   bq show --schema --format=prettyjson $PROJECT_ID:$DATASET.scraper_execution_log"
echo ""

echo "🧪 Test query:"
cat << 'EOF'
   bq query --project_id=nba-props-platform --use_legacy_sql=false "
   SELECT 
     table_name,
     table_type,
     TIMESTAMP_MILLIS(creation_time) as created_at
   FROM \`nba_orchestration.INFORMATION_SCHEMA.TABLES\`
   ORDER BY table_name
   "
EOF
echo ""

echo "📖 Next Steps:"
echo "   1. Review README.md for usage examples"
echo "   2. Add logging to scraper_base.py"
echo "   3. Create config/workflows.yaml"
echo "   4. Implement master_controller.py"
echo "   5. Test with sample scrapers"
echo ""

log_success "Deployment script completed successfully"

# ============================================================================
# END OF SCRIPT
# ============================================================================
