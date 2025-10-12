#!/bin/bash
# =============================================================================
# File: scripts/validate-injuries
# Purpose: CLI tool for running NBA injury report validation queries
# Usage: ./scripts/validate-injuries [command] [options]
# =============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# Base directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
QUERIES_DIR="$PROJECT_ROOT/validation/queries/raw/nbac_injury_report"

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
    echo -e "${MAGENTA}ℹ️  $1${NC}"
}

# =============================================================================
# Show Available Commands
# =============================================================================

show_help() {
    cat << EOF
${GREEN}NBA Injury Report Validation Tool${NC}

Usage: validate-injuries [command] [options]

${YELLOW}HISTORICAL VALIDATION:${NC}
  completeness          Hourly snapshot completeness (detects scraper failures)
  trends                Player coverage trends (detect anomalies)
  confidence            PDF parsing quality monitoring

${YELLOW}GAME DAY MONITORING:${NC}
  gameday               Cross-validate with schedule (game day coverage)
  peaks                 Validate critical 5 PM & 8 PM reports

${YELLOW}BUSINESS INTELLIGENCE:${NC}
  changes               Track intraday status changes (late scratches)
  status                Same as 'changes' (alias)

${YELLOW}DAILY MONITORING:${NC}
  yesterday             Check if yesterday's reports were captured
  daily                 Same as 'yesterday' (alias)

${YELLOW}OPTIONS:${NC}
  --csv                 Save results to CSV file
  --table               Save results to BigQuery table
  --help                Show this help message

${YELLOW}EXAMPLES:${NC}
  validate-injuries yesterday             # Morning check
  validate-injuries completeness --csv    # Full health check
  validate-injuries changes               # Find late scratches
  validate-injuries peaks                 # Check 5 PM & 8 PM reports

${YELLOW}QUICK COMMANDS:${NC}
  validate-injuries list                  # List all available queries
  validate-injuries help                  # Show this help

${MAGENTA}KEY DIFFERENCES FROM ODDS:${NC}
  • Hourly data (24 snapshots/day) vs game-based
  • Empty hours are NORMAL (60-70% expected)
  • Peak hours (5 PM, 8 PM ET) are critical
  • Game-day focus for validation

EOF
}

# =============================================================================
# List All Queries
# =============================================================================

list_queries() {
    print_header "Available Injury Report Validation Queries"
    echo ""
    echo "Historical Validation:"
    echo "  1. hourly_snapshot_completeness.sql    (alias: completeness, snapshots)"
    echo "  2. player_coverage_trends.sql          (alias: trends, coverage)"
    echo "  3. confidence_score_monitoring.sql     (alias: confidence, quality)"
    echo ""
    echo "Game Day Monitoring:"
    echo "  4. game_day_coverage_check.sql         (alias: gameday, games)"
    echo "  5. peak_hour_validation.sql            (alias: peaks, peak-hours)"
    echo ""
    echo "Business Intelligence:"
    echo "  6. status_change_detection.sql         (alias: changes, status)"
    echo ""
    echo "Daily Monitoring:"
    echo "  7. daily_check_yesterday.sql           (alias: yesterday, daily)"
    echo ""
    print_info "Run 'validate-injuries help' for detailed usage"
}

# =============================================================================
# Run Query
# =============================================================================

run_query() {
    local query_file=$1
    local output_format=$2
    local query_path="$QUERIES_DIR/$query_file"
    
    if [ ! -f "$query_path" ]; then
        print_error "Query file not found: $query_file"
        echo "Run 'validate-injuries list' to see available queries"
        exit 1
    fi
    
    print_header "Running: $query_file"
    echo ""
    
    # Show query-specific tips
    case $query_file in
        "hourly_snapshot_completeness.sql")
            print_info "During season: expect 5-10 hourly snapshots/day"
            print_info "Off-season: 0-3 snapshots/day is normal"
            echo ""
            ;;
        "peak_hour_validation.sql")
            print_info "5 PM (hour 17) and 8 PM (hour 20) ET are critical"
            print_info "These hours have most comprehensive injury data"
            echo ""
            ;;
        "status_change_detection.sql")
            print_info "Finding late status changes (last 7 days)"
            print_info "High impact: 'out' ↔ 'available' changes"
            echo ""
            ;;
    esac
    
    case $output_format in
        csv)
            local timestamp=$(date +%Y%m%d_%H%M%S)
            local output_file="validation_injury_${query_file%.sql}_${timestamp}.csv"
            print_warning "Saving results to: $output_file"
            bq query --use_legacy_sql=false --format=csv < "$query_path" > "$output_file"
            print_success "Results saved to $output_file"
            ;;
        table)
            local timestamp=$(date +%Y%m%d)
            local table_name="validation.injury_${query_file%.sql}_${timestamp}"
            print_warning "Saving to BigQuery table: $table_name"
            bq query --use_legacy_sql=false --destination_table="nba-props-platform:${table_name}" < "$query_path"
            print_success "Results saved to nba-props-platform:${table_name}"
            ;;
        *)
            bq query --use_legacy_sql=false < "$query_path"
            ;;
    esac
}

# =============================================================================
# Main Command Handler
# =============================================================================

main() {
    local command=$1
    local output_format=""
    
    # Parse options
    shift || true
    while [[ $# -gt 0 ]]; do
        case $1 in
            --csv)
                output_format="csv"
                shift
                ;;
            --table)
                output_format="table"
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
    
    # Handle commands
    case $command in
        # Show help
        help|--help|-h|"")
            show_help
            ;;
        
        # List queries
        list|ls)
            list_queries
            ;;
        
        # Historical validation
        completeness|complete|snapshots|hourly)
            run_query "hourly_snapshot_completeness.sql" "$output_format"
            ;;
        
        trends|coverage)
            run_query "player_coverage_trends.sql" "$output_format"
            ;;
        
        confidence|quality|parsing)
            run_query "confidence_score_monitoring.sql" "$output_format"
            ;;
        
        # Game day monitoring
        gameday|games|game-day)
            run_query "game_day_coverage_check.sql" "$output_format"
            ;;
        
        peaks|peak-hours|peak)
            run_query "peak_hour_validation.sql" "$output_format"
            ;;
        
        # Business intelligence
        changes|status|scratches)
            run_query "status_change_detection.sql" "$output_format"
            ;;
        
        # Daily monitoring
        yesterday|daily)
            run_query "daily_check_yesterday.sql" "$output_format"
            ;;
        
        # Unknown command
        *)
            print_error "Unknown command: $command"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

# =============================================================================
# Run
# =============================================================================

main "$@"
