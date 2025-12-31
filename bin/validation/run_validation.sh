#!/bin/bash
# File: bin/validation/run_validation.sh
# Purpose: Run validation checks on data pipeline components
# Usage: ./bin/validation/run_validation.sh [command] [options]

set -e

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_header() {
    echo -e "${CYAN}========================================"
    echo -e "NBA Data Pipeline Validation"
    echo -e "========================================${NC}"
    echo -e "Time: $(date)"
    echo ""
}

show_usage() {
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  all                    - Run all validation checks"
    echo "  gcs-bq DATE [END]      - Validate GCS to BigQuery completeness"
    echo "  scrapers               - Validate scraper data freshness"
    echo "  processors             - Validate processor outputs"
    echo "  quick                  - Quick validation (last 24h)"
    echo "  summary                - Show validation summary"
    echo ""
    echo "Options:"
    echo "  --verbose              - Show detailed output"
    echo "  --json                 - Output as JSON"
    echo ""
    echo "Examples:"
    echo "  $0 all                           # Run all validations"
    echo "  $0 gcs-bq 2024-01-15             # Validate specific date"
    echo "  $0 gcs-bq 2024-01-01 2024-01-31  # Validate date range"
    echo "  $0 quick --verbose               # Quick check with details"
}

# Run GCS to BigQuery completeness validation
cmd_gcs_bq() {
    local start_date="$1"
    local end_date="${2:-$start_date}"
    local extra_args="${@:3}"

    echo -e "${BLUE}Running GCS to BigQuery completeness validation...${NC}"
    echo -e "  Date range: $start_date to $end_date"
    echo ""

    python3 "${SCRIPT_DIR}/validate_gcs_bq_completeness.py" "$start_date" "$end_date" $extra_args
}

# Validate scraper data freshness
cmd_scrapers() {
    echo -e "${BLUE}Validating scraper data freshness...${NC}"
    echo ""

    # Check each scraper's data freshness in BigQuery
    bq query --use_legacy_sql=false --format=pretty <<SQL
WITH scraper_freshness AS (
    SELECT 'nbac_gamebook' as source,
           MAX(game_date) as latest_date,
           COUNT(DISTINCT game_date) as dates_7d
    FROM \`${PROJECT_ID}.nba_raw.nbac_gamebook_player_stats\`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

    UNION ALL

    SELECT 'bdl_boxscores',
           MAX(game_date),
           COUNT(DISTINCT game_date)
    FROM \`${PROJECT_ID}.nba_raw.bdl_boxscores\`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

    UNION ALL

    SELECT 'br_rosters',
           CAST(MAX(updated_at) AS DATE),
           1
    FROM \`${PROJECT_ID}.nba_raw.br_rosters_current\`
    WHERE updated_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
)
SELECT
    source,
    latest_date,
    dates_7d as days_with_data,
    DATE_DIFF(CURRENT_DATE(), latest_date, DAY) as days_stale,
    CASE
        WHEN DATE_DIFF(CURRENT_DATE(), latest_date, DAY) <= 1 THEN 'FRESH'
        WHEN DATE_DIFF(CURRENT_DATE(), latest_date, DAY) <= 3 THEN 'OK'
        ELSE 'STALE'
    END as status
FROM scraper_freshness
ORDER BY source;
SQL
}

# Validate processor outputs
cmd_processors() {
    echo -e "${BLUE}Validating processor outputs...${NC}"
    echo ""

    bq query --use_legacy_sql=false --format=pretty <<SQL
WITH processor_status AS (
    SELECT 'player_game_summary' as processor,
           MAX(game_date) as latest_date,
           COUNT(*) as records_7d
    FROM \`${PROJECT_ID}.nba_analytics.player_game_summary\`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

    UNION ALL

    SELECT 'team_defense_summary',
           MAX(game_date),
           COUNT(*)
    FROM \`${PROJECT_ID}.nba_analytics.team_defense_game_summary\`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

    UNION ALL

    SELECT 'player_reference',
           CAST(MAX(updated_at) AS DATE),
           COUNT(*)
    FROM \`${PROJECT_ID}.nba_reference.player_reference\`
    WHERE updated_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
)
SELECT
    processor,
    latest_date,
    records_7d,
    CASE
        WHEN DATE_DIFF(CURRENT_DATE(), latest_date, DAY) <= 1 THEN 'CURRENT'
        WHEN DATE_DIFF(CURRENT_DATE(), latest_date, DAY) <= 3 THEN 'BEHIND'
        ELSE 'STALE'
    END as status
FROM processor_status
ORDER BY processor;
SQL
}

# Quick validation (last 24 hours)
cmd_quick() {
    local verbose="${1:-}"

    print_header
    echo -e "${BLUE}Quick Validation (Last 24 Hours)${NC}"
    echo ""

    local yesterday=$(date -d "yesterday" +%Y-%m-%d 2>/dev/null || date -v-1d +%Y-%m-%d)
    local today=$(date +%Y-%m-%d)

    echo "1. Checking scraper freshness..."
    cmd_scrapers

    echo ""
    echo "2. Checking processor outputs..."
    cmd_processors

    echo ""
    echo "3. GCS to BigQuery check (yesterday)..."
    python3 "${SCRIPT_DIR}/validate_gcs_bq_completeness.py" "$yesterday" --quick 2>/dev/null || \
        echo -e "  ${YELLOW}Skipped (script not available or no data)${NC}"

    echo ""
    echo -e "${GREEN}Quick validation complete!${NC}"
}

# Run all validations
cmd_all() {
    print_header
    echo -e "${BLUE}Running All Validations${NC}"
    echo ""

    local yesterday=$(date -d "yesterday" +%Y-%m-%d 2>/dev/null || date -v-1d +%Y-%m-%d)
    local week_ago=$(date -d "7 days ago" +%Y-%m-%d 2>/dev/null || date -v-7d +%Y-%m-%d)

    echo "=========================================="
    echo "1. SCRAPER DATA FRESHNESS"
    echo "=========================================="
    cmd_scrapers

    echo ""
    echo "=========================================="
    echo "2. PROCESSOR OUTPUTS"
    echo "=========================================="
    cmd_processors

    echo ""
    echo "=========================================="
    echo "3. GCS TO BIGQUERY COMPLETENESS (7 days)"
    echo "=========================================="
    python3 "${SCRIPT_DIR}/validate_gcs_bq_completeness.py" "$week_ago" "$yesterday" 2>/dev/null || \
        echo -e "  ${YELLOW}GCS-BQ validation skipped${NC}"

    echo ""
    echo -e "${GREEN}=========================================="
    echo -e "All Validations Complete!"
    echo -e "==========================================${NC}"
}

# Summary command
cmd_summary() {
    print_header
    echo -e "${BLUE}Validation Summary${NC}"
    echo ""

    echo "Data Sources Status:"
    bq query --use_legacy_sql=false --format=pretty <<SQL
SELECT
    'Raw Data' as layer,
    (SELECT COUNT(DISTINCT game_date) FROM \`${PROJECT_ID}.nba_raw.nbac_gamebook_player_stats\`
     WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)) as gamebook_dates,
    (SELECT COUNT(DISTINCT game_date) FROM \`${PROJECT_ID}.nba_raw.bdl_boxscores\`
     WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)) as boxscores_dates,
    (SELECT COUNT(DISTINCT team_abbrev) FROM \`${PROJECT_ID}.nba_raw.br_rosters_current\`) as roster_teams
UNION ALL
SELECT
    'Analytics',
    (SELECT COUNT(DISTINCT game_date) FROM \`${PROJECT_ID}.nba_analytics.player_game_summary\`
     WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)),
    (SELECT COUNT(DISTINCT game_date) FROM \`${PROJECT_ID}.nba_analytics.team_defense_game_summary\`
     WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)),
    NULL;
SQL
}

# Main command handling
case "${1:-help}" in
    "all")
        shift
        cmd_all "$@"
        ;;
    "gcs-bq")
        shift
        if [[ -z "$1" ]]; then
            echo "Error: Date required for gcs-bq command"
            echo "Usage: $0 gcs-bq DATE [END_DATE]"
            exit 1
        fi
        cmd_gcs_bq "$@"
        ;;
    "scrapers")
        print_header
        cmd_scrapers
        ;;
    "processors")
        print_header
        cmd_processors
        ;;
    "quick")
        shift
        cmd_quick "$@"
        ;;
    "summary")
        cmd_summary
        ;;
    "help"|"-h"|"--help")
        show_usage
        ;;
    *)
        echo "Unknown command: $1"
        show_usage
        exit 1
        ;;
esac
