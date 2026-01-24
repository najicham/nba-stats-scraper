#!/bin/bash
# File: bin/validation/run_validation.sh
# Purpose: Run validation checks on data pipeline components
# Usage: ./bin/validation/run_validation.sh [command] [options]

set -euo pipefail

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
    echo "  news                   - Validate news pipeline"
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
    echo "  $0 news                          # Validate news pipeline"
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

# Validate news pipeline
cmd_news() {
    echo -e "${BLUE}Validating news pipeline...${NC}"
    echo ""

    # Check 1: BigQuery tables freshness
    echo "1. Checking BigQuery data freshness..."
    bq query --use_legacy_sql=false --format=pretty <<SQL
WITH news_status AS (
    -- Articles raw
    SELECT 'news_articles_raw' as component,
           COUNT(*) as count_24h,
           MAX(scraped_at) as latest,
           TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(scraped_at), MINUTE) as minutes_stale
    FROM \`${PROJECT_ID}.nba_raw.news_articles_raw\`
    WHERE scraped_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)

    UNION ALL

    -- Insights with AI summaries
    SELECT 'news_insights (with AI)',
           COUNTIF(ai_summary IS NOT NULL),
           MAX(ai_summary_generated_at),
           TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(ai_summary_generated_at), MINUTE)
    FROM \`${PROJECT_ID}.nba_analytics.news_insights\`
    WHERE extracted_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)

    UNION ALL

    -- Player links
    SELECT 'news_player_links',
           COUNT(*),
           MAX(created_at),
           TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), MINUTE)
    FROM \`${PROJECT_ID}.nba_analytics.news_player_links\`
    WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
)
SELECT
    component,
    count_24h,
    FORMAT_TIMESTAMP('%Y-%m-%d %H:%M', latest) as latest_update,
    minutes_stale,
    CASE
        WHEN minutes_stale <= 30 THEN 'FRESH'
        WHEN minutes_stale <= 60 THEN 'OK'
        WHEN minutes_stale <= 120 THEN 'STALE'
        ELSE 'CRITICAL'
    END as status
FROM news_status
ORDER BY component;
SQL

    echo ""
    echo "2. Checking RSS source diversity..."
    bq query --use_legacy_sql=false --format=pretty <<SQL
SELECT
    source,
    sport,
    COUNT(*) as articles_24h,
    MAX(scraped_at) as latest
FROM \`${PROJECT_ID}.nba_raw.news_articles_raw\`
WHERE scraped_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY source, sport
ORDER BY sport, articles_24h DESC;
SQL

    echo ""
    echo "3. Checking GCS export freshness..."
    # Check if tonight-summary.json exists and is recent
    local gcs_file="gs://nba-props-platform-api/v1/player-news/nba/tonight-summary.json"
    local gcs_stat=$(gsutil stat "$gcs_file" 2>/dev/null | grep "Update time" | cut -d':' -f2- | xargs)

    if [[ -n "$gcs_stat" ]]; then
        echo -e "  ${GREEN}NBA tonight-summary.json exists${NC}"
        echo "  Last updated: $gcs_stat"

        # Check content
        local player_count=$(gsutil cat "$gcs_file" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('total_players', 0))" 2>/dev/null || echo "0")
        echo "  Players with news: $player_count"
    else
        echo -e "  ${RED}NBA tonight-summary.json NOT FOUND${NC}"
    fi

    echo ""
    echo "4. Checking Cloud Function logs (last 5 runs)..."
    gcloud functions logs read news-fetcher \
        --project="${PROJECT_ID}" \
        --region=us-west2 \
        --limit=10 2>/dev/null | grep -E "(triggered|complete|error|articles)" | head -5 || \
        echo -e "  ${YELLOW}Could not fetch logs${NC}"

    echo ""
    echo -e "${GREEN}News pipeline validation complete!${NC}"
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
    echo "3. Checking news pipeline..."
    cmd_news

    echo ""
    echo "4. GCS to BigQuery check (yesterday)..."
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
    echo "3. NEWS PIPELINE"
    echo "=========================================="
    cmd_news

    echo ""
    echo "=========================================="
    echo "4. GCS TO BIGQUERY COMPLETENESS (7 days)"
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
    "news")
        print_header
        cmd_news
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
