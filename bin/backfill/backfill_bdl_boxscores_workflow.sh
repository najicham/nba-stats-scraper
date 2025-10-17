#!/bin/bash
# =============================================================================
# File: bin/backfill/backfill_bdl_boxscores_workflow.sh
# Purpose: Complete workflow for BDL boxscore backfill - from validation to completion
# Usage: ./bin/backfill/backfill_bdl_boxscores_workflow.sh [options]
# =============================================================================
#
# This script orchestrates the complete backfill workflow:
#   1. Runs validation to find missing dates
#   2. Executes scraper backfill for those dates
#   3. Executes processor backfill for those dates
#   4. Validates completion
#
# Example Usage:
#   # Dry run - see what would be done
#   ./bin/backfill/backfill_bdl_boxscores_workflow.sh --dry-run
#
#   # Process Priority 1 missing dates (2023-24 regular season)
#   ./bin/backfill/backfill_bdl_boxscores_workflow.sh --priority 1
#
#   # Process Priority 2 missing dates (2022-23 playoffs)
#   ./bin/backfill/backfill_bdl_boxscores_workflow.sh --priority 2
#
#   # Process all missing dates
#   ./bin/backfill/backfill_bdl_boxscores_workflow.sh --priority all
#
#   # Custom dates
#   ./bin/backfill/backfill_bdl_boxscores_workflow.sh --dates "2023-11-03,2023-11-10"
#
# =============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
REGION="us-west2"
SCRAPER_SERVICE_URL="${SCRAPER_SERVICE_URL:-https://nba-scrapers-f7p3g7f6ya-wl.a.run.app}"

# Flags
DRY_RUN=false
PRIORITY=""
CUSTOM_DATES=""
SKIP_VALIDATION=false

# =============================================================================
# Helper Functions
# =============================================================================

print_header() {
    echo -e "${BLUE}=================================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}=================================================${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo -e "${CYAN}ℹ️  $1${NC}"
}

show_help() {
    cat << EOF
${GREEN}BDL Boxscore Backfill Workflow${NC}

Complete orchestration of scraper → processor → validation workflow for BDL boxscores.

${YELLOW}Usage:${NC}
  ./bin/backfill/backfill_bdl_boxscores_workflow.sh [options]

${YELLOW}Options:${NC}
  --priority LEVEL      Process specific priority level from backfill plan
                        Options: 1, 2, 3, 4, all
  --dates "D1,D2,D3"    Process specific comma-separated dates
  --dry-run             Show what would be done without executing
  --skip-validation     Skip final validation step
  --help, -h            Show this help message

${YELLOW}Priority Levels (from backfill plan):${NC}
  Priority 1: 2023-24 Regular Season (66 games, 10 dates) - CRITICAL
              Dates: 2023-11-03, 2023-11-10, 2023-11-14, 2023-11-17,
                     2023-11-21, 2023-11-24, 2023-11-28, 2023-12-04,
                     2023-12-05, 2023-12-07

  Priority 2: 2022-23 Playoffs (2 games, 1 date) - CRITICAL
              Date: 2023-04-28

  Priority 3: 2022-23 Regular Season (3 games, 3 dates) - MODERATE
              Dates: 2023-03-05, 2023-03-06, 2023-03-07

  Priority 4: 2021-22 Regular Season (30 games, 17 dates) - MODERATE
              Dates: 2022-01-10, 2022-01-11, 2022-01-16, 2022-01-24,
                     2022-01-25, 2022-01-26, 2022-01-28, 2022-01-31,
                     2022-02-01, 2022-02-03, 2022-02-11, 2022-02-17,
                     2022-02-28, 2022-03-03, 2022-03-04, 2022-03-07,
                     2022-03-31

  All: All priorities combined (101 games, 31 unique dates)

${YELLOW}Examples:${NC}
  # Dry run to see what Priority 1 would do
  ./bin/backfill/backfill_bdl_boxscores_workflow.sh --priority 1 --dry-run

  # Process Priority 1 (critical 2023-24 gaps)
  ./bin/backfill/backfill_bdl_boxscores_workflow.sh --priority 1

  # Process all missing dates
  ./bin/backfill/backfill_bdl_boxscores_workflow.sh --priority all

  # Custom dates for specific gap filling
  ./bin/backfill/backfill_bdl_boxscores_workflow.sh --dates "2023-11-03,2023-11-10"

${YELLOW}Workflow Steps:${NC}
  1. 📊 Validation: Identifies missing dates (optional with --dates)
  2. 🔽 Scraper: Downloads box scores from BDL API
  3. ⚙️  Processor: Loads data into BigQuery
  4. ✅ Validation: Confirms completion

${YELLOW}Environment Variables:${NC}
  SCRAPER_SERVICE_URL   URL of scraper Cloud Run service
                        Default: https://nba-scrapers-f7p3g7f6ya-wl.a.run.app

EOF
}

# =============================================================================
# Priority Level Date Definitions (from backfill plan document)
# =============================================================================

get_priority_dates() {
    local priority=$1
    
    case $priority in
        1)
            # Priority 1: 2023-24 Regular Season
            echo "2023-11-03,2023-11-10,2023-11-14,2023-11-17,2023-11-21,2023-11-24,2023-11-28,2023-12-04,2023-12-05,2023-12-07"
            ;;
        2)
            # Priority 2: 2022-23 Playoffs
            echo "2023-04-28"
            ;;
        3)
            # Priority 3: 2022-23 Regular Season
            echo "2023-03-05,2023-03-06,2023-03-07"
            ;;
        4)
            # Priority 4: 2021-22 Regular Season
            echo "2022-01-10,2022-01-11,2022-01-16,2022-01-24,2022-01-25,2022-01-26,2022-01-28,2022-01-31,2022-02-01,2022-02-03,2022-02-11,2022-02-17,2022-02-28,2022-03-03,2022-03-04,2022-03-07,2022-03-31"
            ;;
        all)
            # All priorities combined
            echo "2023-11-03,2023-11-10,2023-11-14,2023-11-17,2023-11-21,2023-11-24,2023-11-28,2023-12-04,2023-12-05,2023-12-07,2023-04-28,2023-03-05,2023-03-06,2023-03-07,2022-01-10,2022-01-11,2022-01-16,2022-01-24,2022-01-25,2022-01-26,2022-01-28,2022-01-31,2022-02-01,2022-02-03,2022-02-11,2022-02-17,2022-02-28,2022-03-03,2022-03-04,2022-03-07,2022-03-31"
            ;;
        *)
            print_error "Invalid priority: $priority"
            return 1
            ;;
    esac
}

get_priority_description() {
    local priority=$1
    
    case $priority in
        1)
            echo "Priority 1: 2023-24 Regular Season (66 games, 10 dates)"
            ;;
        2)
            echo "Priority 2: 2022-23 Playoffs (2 games, 1 date)"
            ;;
        3)
            echo "Priority 3: 2022-23 Regular Season (3 games, 3 dates)"
            ;;
        4)
            echo "Priority 4: 2021-22 Regular Season (30 games, 17 dates)"
            ;;
        all)
            echo "All Priorities: Complete backfill (101 games, 31 dates)"
            ;;
    esac
}

# =============================================================================
# Validation Step
# =============================================================================

run_validation() {
    print_header "Step 1: Validation - Finding Missing Dates"
    
    print_info "Running: ./scripts/validate-bdl-boxscores missing"
    
    # Run validation query
    "${PROJECT_ROOT}/scripts/validate-bdl-boxscores" missing --csv
    
    if [ $? -eq 0 ]; then
        print_success "Validation complete - check validation_bdl_find_missing_games_*.csv"
    else
        print_warning "Validation had warnings or errors"
    fi
    
    echo ""
}

# =============================================================================
# Scraper Backfill Step
# =============================================================================

run_scraper_backfill() {
    local dates=$1
    local dry_run_flag=$2
    
    print_header "Step 2: Scraper Backfill - Downloading Box Scores"
    
    # Count dates
    local date_count=$(echo "$dates" | tr ',' '\n' | wc -l | xargs)
    print_info "Processing $date_count dates"
    print_info "Dates: ${dates:0:100}..."
    
    if [ "$dry_run_flag" = "true" ]; then
        print_info "DRY RUN - Would execute:"
        echo "  gcloud run jobs execute bdl-boxscore-backfill \\"
        echo "    --args=\"--service-url=$SCRAPER_SERVICE_URL,--dates=$dates,--dry-run\" \\"
        echo "    --region=$REGION"
        echo ""
        return 0
    fi
    
    print_info "Executing scraper backfill..."
    
    # Execute Cloud Run job
    if gcloud run jobs execute bdl-boxscore-backfill \
        --args="--service-url=$SCRAPER_SERVICE_URL,--dates=$dates" \
        --region=$REGION \
        --wait; then
        print_success "Scraper backfill complete"
    else
        print_error "Scraper backfill failed"
        return 1
    fi
    
    echo ""
}

# =============================================================================
# Processor Backfill Step
# =============================================================================

run_processor_backfill() {
    local dates=$1
    local dry_run_flag=$2
    
    print_header "Step 3: Processor Backfill - Loading to BigQuery"
    
    # Count dates
    local date_count=$(echo "$dates" | tr ',' '\n' | wc -l | xargs)
    print_info "Processing $date_count dates"
    print_info "Dates: ${dates:0:100}..."
    
    if [ "$dry_run_flag" = "true" ]; then
        print_info "DRY RUN - Would execute:"
        echo "  gcloud run jobs execute bdl-boxscores-processor-backfill \\"
        echo "    --args=\"--dates=$dates,--dry-run\" \\"
        echo "    --region=$REGION"
        echo ""
        return 0
    fi
    
    print_info "Executing processor backfill..."
    
    # Execute Cloud Run job
    if gcloud run jobs execute bdl-boxscores-processor-backfill \
        --args="--dates=$dates" \
        --region=$REGION \
        --wait; then
        print_success "Processor backfill complete"
    else
        print_error "Processor backfill failed"
        return 1
    fi
    
    echo ""
}

# =============================================================================
# Final Validation Step
# =============================================================================

run_final_validation() {
    print_header "Step 4: Final Validation - Confirming Completion"
    
    print_info "Running season completeness check..."
    "${PROJECT_ROOT}/scripts/validate-bdl-boxscores" completeness
    
    echo ""
    
    print_info "Running missing games check..."
    "${PROJECT_ROOT}/scripts/validate-bdl-boxscores" missing
    
    if [ $? -eq 0 ]; then
        print_success "Final validation complete"
    else
        print_warning "Validation found issues - review output above"
    fi
    
    echo ""
}

# =============================================================================
# Main Workflow
# =============================================================================

main() {
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --priority)
                PRIORITY=$2
                shift 2
                ;;
            --dates)
                CUSTOM_DATES=$2
                shift 2
                ;;
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --skip-validation)
                SKIP_VALIDATION=true
                shift
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done
    
    # Validate inputs
    if [ -z "$PRIORITY" ] && [ -z "$CUSTOM_DATES" ]; then
        print_error "Must specify either --priority or --dates"
        show_help
        exit 1
    fi
    
    if [ -n "$PRIORITY" ] && [ -n "$CUSTOM_DATES" ]; then
        print_error "Cannot specify both --priority and --dates"
        show_help
        exit 1
    fi
    
    # Determine dates to process
    local dates_to_process=""
    
    if [ -n "$PRIORITY" ]; then
        dates_to_process=$(get_priority_dates "$PRIORITY")
        if [ $? -ne 0 ]; then
            exit 1
        fi
        
        print_header "BDL Boxscore Backfill Workflow"
        echo ""
        print_info "Mode: $(get_priority_description "$PRIORITY")"
    else
        dates_to_process="$CUSTOM_DATES"
        print_header "BDL Boxscore Backfill Workflow"
        echo ""
        print_info "Mode: Custom Dates"
    fi
    
    if [ "$DRY_RUN" = true ]; then
        print_warning "DRY RUN MODE - No actual processing will occur"
    fi
    
    echo ""
    print_info "Dates to process: $dates_to_process"
    echo ""
    
    # Confirm execution
    if [ "$DRY_RUN" = false ]; then
        read -p "Continue with backfill? (y/N) " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_warning "Aborted by user"
            exit 0
        fi
        echo ""
    fi
    
    # Execute workflow
    local start_time=$(date +%s)
    
    # Step 1: Validation (optional - only if not using custom dates)
    if [ -z "$CUSTOM_DATES" ] && [ "$SKIP_VALIDATION" = false ]; then
        run_validation
    else
        print_info "Skipping initial validation (using predefined dates)"
        echo ""
    fi
    
    # Step 2: Scraper Backfill
    if ! run_scraper_backfill "$dates_to_process" "$DRY_RUN"; then
        print_error "Workflow failed at scraper step"
        exit 1
    fi
    
    # Step 3: Processor Backfill
    if ! run_processor_backfill "$dates_to_process" "$DRY_RUN"; then
        print_error "Workflow failed at processor step"
        exit 1
    fi
    
    # Step 4: Final Validation
    if [ "$DRY_RUN" = false ] && [ "$SKIP_VALIDATION" = false ]; then
        run_final_validation
    fi
    
    # Summary
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local duration_min=$((duration / 60))
    
    print_header "Workflow Complete"
    echo ""
    print_success "All steps completed successfully"
    print_info "Duration: ${duration_min} minutes"
    echo ""
    
    if [ "$DRY_RUN" = false ]; then
        print_info "Next steps:"
        echo "  1. Review validation output above"
        echo "  2. Check BigQuery: SELECT COUNT(*) FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`"
        echo "  3. Monitor for any remaining gaps: ./scripts/validate-bdl-boxscores missing"
    else
        print_info "This was a dry run. Re-run without --dry-run to execute."
    fi
    echo ""
}

# =============================================================================
# Execute Main
# =============================================================================

main "$@"
