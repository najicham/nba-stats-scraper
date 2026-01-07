#!/bin/bash
###############################################################################
# Emergency Operations Dashboard
#
# Unified monitoring dashboard for NBA Stats Scraper platform
# Combines pipeline health, workflow status, validation, and error tracking
#
# Usage:
#   ./bin/operations/ops_dashboard.sh              # Full dashboard
#   ./bin/operations/ops_dashboard.sh quick        # Quick status only
#   ./bin/operations/ops_dashboard.sh pipeline     # Pipeline health only
#   ./bin/operations/ops_dashboard.sh errors       # Recent errors only
#
# Created: 2026-01-03 (Session 6 Infrastructure Polish)
# Version: 1.0
###############################################################################

set -euo pipefail

# Script directory setup
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Source sport configuration (uses SPORT env var, defaults to nba)
source "$PROJECT_ROOT/bin/common/sport_config.sh"

# Configuration (now sourced from sport_config.sh)
# PROJECT_ID, GCS_BUCKET, RAW_DATASET, etc. are now available

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

###############################################################################
# Helper Functions
###############################################################################

print_header() {
    local title="$1"
    local width=80
    echo ""
    echo -e "${BOLD}$(printf '═%.0s' $(seq 1 $width))${NC}"
    echo -e "${BOLD}$(printf "%*s" $(((${#title}+$width)/2)) "$title")${NC}"
    echo -e "${BOLD}$(printf '═%.0s' $(seq 1 $width))${NC}"
    echo ""
}

print_section() {
    local title="$1"
    echo ""
    echo -e "${CYAN}${BOLD}▶ $title${NC}"
    echo -e "${CYAN}$(printf '─%.0s' $(seq 1 78))${NC}"
}

status_icon() {
    local status="$1"
    case "$status" in
        "healthy"|"good"|"success"|"complete")
            echo -e "${GREEN}✓${NC}"
            ;;
        "warning"|"partial"|"degraded")
            echo -e "${YELLOW}⚠${NC}"
            ;;
        "critical"|"failed"|"error"|"missing")
            echo -e "${RED}✗${NC}"
            ;;
        "unknown"|"checking")
            echo -e "${BLUE}?${NC}"
            ;;
        *)
            echo -e "${BLUE}○${NC}"
            ;;
    esac
}

###############################################################################
# Phase 1-4: Data Pipeline Health
###############################################################################

check_pipeline_health() {
    print_section "📊 DATA PIPELINE HEALTH (Phases 1-4)"

    local today=$(date -d "yesterday" +%Y-%m-%d)  # Use yesterday for complete data

    echo -e "${BOLD}Checking data completeness for: $today${NC}"
    echo ""

    # Phase 3: Analytics Layer
    echo -e "${MAGENTA}Phase 3: Analytics${NC}"

    local phase3_tables=(
        "nba_analytics.player_game_summary"
        "nba_analytics.team_offense_game_summary"
        "nba_analytics.team_defense_game_summary"
        "nba_analytics.upcoming_player_game_context"
        "nba_analytics.upcoming_team_game_context"
    )

    local phase3_healthy=0
    local phase3_total=0

    for table in "${phase3_tables[@]}"; do
        phase3_total=$((phase3_total + 1))
        local table_name=$(echo "$table" | cut -d'.' -f2)
        local row_count=$(bq query --use_legacy_sql=false --format=csv --max_rows=1 \
            "SELECT COUNT(*) as cnt FROM \`${PROJECT_ID}.${table}\` WHERE game_date = '$today'" 2>/dev/null | tail -n1)

        if [[ -n "$row_count" && "$row_count" != "cnt" && "$row_count" -gt 0 ]]; then
            echo -e "  $(status_icon "healthy") ${table_name}: ${GREEN}$row_count rows${NC}"
            phase3_healthy=$((phase3_healthy + 1))
        elif [[ "$row_count" == "0" ]]; then
            echo -e "  $(status_icon "warning") ${table_name}: ${YELLOW}0 rows (no games or pending)${NC}"
        else
            echo -e "  $(status_icon "failed") ${table_name}: ${RED}Query failed${NC}"
        fi
    done

    echo -e "  ${BOLD}Phase 3 Status: $phase3_healthy/$phase3_total tables have data${NC}"

    # Phase 4: Precompute Layer
    echo ""
    echo -e "${MAGENTA}Phase 4: Precompute${NC}"

    local phase4_tables=(
        "nba_precompute.player_composite_factors"
        "nba_precompute.player_shot_zone_analysis"
        "nba_precompute.team_defense_zone_analysis"
        "nba_precompute.player_daily_cache"
    )

    local phase4_healthy=0
    local phase4_total=0

    for table in "${phase4_tables[@]}"; do
        phase4_total=$((phase4_total + 1))
        local table_name=$(echo "$table" | cut -d'.' -f2)

        # Determine date field (most use game_date, some use analysis_date or cache_date)
        local date_field="game_date"
        [[ "$table_name" == *"analysis"* ]] && date_field="analysis_date"
        [[ "$table_name" == *"cache"* ]] && date_field="cache_date"

        local row_count=$(bq query --use_legacy_sql=false --format=csv --max_rows=1 \
            "SELECT COUNT(*) as cnt FROM \`${PROJECT_ID}.${table}\` WHERE ${date_field} = '$today'" 2>/dev/null | tail -n1)

        if [[ -n "$row_count" && "$row_count" != "cnt" && "$row_count" -gt 0 ]]; then
            echo -e "  $(status_icon "healthy") ${table_name}: ${GREEN}$row_count rows${NC}"
            phase4_healthy=$((phase4_healthy + 1))
        elif [[ "$row_count" == "0" ]]; then
            echo -e "  $(status_icon "warning") ${table_name}: ${YELLOW}0 rows (early season or pending)${NC}"
        else
            echo -e "  $(status_icon "failed") ${table_name}: ${RED}Query failed${NC}"
        fi
    done

    echo -e "  ${BOLD}Phase 4 Status: $phase4_healthy/$phase4_total tables have data${NC}"

    # Overall pipeline health
    echo ""
    local total_healthy=$((phase3_healthy + phase4_healthy))
    local total_tables=$((phase3_total + phase4_total))
    local health_percent=$((total_healthy * 100 / total_tables))

    if [[ $health_percent -ge 80 ]]; then
        echo -e "  $(status_icon "healthy") ${BOLD}Overall Pipeline Health: ${GREEN}${health_percent}%${NC} ($total_healthy/$total_tables tables)"
    elif [[ $health_percent -ge 50 ]]; then
        echo -e "  $(status_icon "warning") ${BOLD}Overall Pipeline Health: ${YELLOW}${health_percent}%${NC} ($total_healthy/$total_tables tables)"
    else
        echo -e "  $(status_icon "critical") ${BOLD}Overall Pipeline Health: ${RED}${health_percent}%${NC} ($total_healthy/$total_tables tables)"
    fi
}

###############################################################################
# Validation Status
###############################################################################

check_validation_status() {
    print_section "✅ DATA QUALITY VALIDATION"

    # Check for validation tables (if they exist)
    echo -e "${BOLD}Validation Framework Status:${NC}"

    # Check if validation ran recently
    local val_exists=$(bq ls --project_id="$PROJECT_ID" --max_results=1 nba_orchestration 2>/dev/null | grep -c "processor_output_validation" || true)

    if [[ "$val_exists" -gt 0 ]]; then
        # Get recent validation results
        local recent_validations=$(bq query --use_legacy_sql=false --format=csv --max_rows=10 \
            "SELECT
                processor_name,
                game_date,
                issue_type,
                severity,
                is_acceptable
            FROM \`${PROJECT_ID}.nba_orchestration.processor_output_validation\`
            WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
            ORDER BY timestamp DESC
            LIMIT 5" 2>/dev/null || echo "")

        if [[ -n "$recent_validations" ]]; then
            echo -e "  $(status_icon "healthy") Recent validation checks found"
            echo ""
            echo "$recent_validations" | column -t -s','
        else
            echo -e "  $(status_icon "warning") ${YELLOW}No recent validation results (last 24h)${NC}"
        fi
    else
        echo -e "  $(status_icon "unknown") ${BLUE}Validation table not found (may not be enabled)${NC}"
    fi

    # Check feature coverage for ML training
    echo ""
    echo -e "${BOLD}ML Training Data Quality:${NC}"

    local feature_check=$(bq query --use_legacy_sql=false --format=csv --max_rows=1 \
        "SELECT
            COUNT(*) as total_records,
            COUNTIF(minutes_played IS NULL) as null_minutes,
            COUNTIF(usage_rate IS NULL) as null_usage_rate
        FROM \`${PROJECT_ID}.nba_analytics.player_game_summary\`
        WHERE game_date >= '2024-10-01'" 2>/dev/null | tail -n1)

    if [[ -n "$feature_check" && "$feature_check" != "total_records,null_minutes,null_usage_rate" ]]; then
        IFS=',' read -r total null_min null_usage <<< "$feature_check"
        local min_pct=$((null_min * 100 / total))
        local usage_pct=$((null_usage * 100 / total))

        echo -e "  Total records (2024-25): $total"

        if [[ $min_pct -lt 5 ]]; then
            echo -e "  $(status_icon "healthy") minutes_played: ${GREEN}${min_pct}% NULL${NC}"
        else
            echo -e "  $(status_icon "warning") minutes_played: ${YELLOW}${min_pct}% NULL${NC}"
        fi

        if [[ $usage_pct -lt 5 ]]; then
            echo -e "  $(status_icon "healthy") usage_rate: ${GREEN}${usage_pct}% NULL${NC}"
        else
            echo -e "  $(status_icon "warning") usage_rate: ${YELLOW}${usage_pct}% NULL${NC}"
        fi
    else
        echo -e "  $(status_icon "unknown") ${BLUE}Could not check feature quality${NC}"
    fi
}

###############################################################################
# Workflow & Orchestration Health
###############################################################################

check_workflow_health() {
    print_section "🔄 WORKFLOW & ORCHESTRATION"

    echo -e "${BOLD}Recent Workflow Executions:${NC}"
    echo ""

    local workflows=(
        "early-morning-final-check"
        "morning-operations"
        "real-time-business"
        "post-game-collection"
        "late-night-recovery"
    )

    local healthy_count=0
    local total_count=0

    for workflow in "${workflows[@]}"; do
        total_count=$((total_count + 1))
        local latest_state=$(gcloud workflows executions list "$workflow" \
            --location="$REGION" --limit=1 --format="value(state)" 2>/dev/null || echo "UNKNOWN")

        local status_icon_var
        if [[ "$latest_state" == "SUCCEEDED" ]]; then
            status_icon_var="healthy"
            healthy_count=$((healthy_count + 1))
        elif [[ "$latest_state" == "FAILED" ]]; then
            status_icon_var="critical"
        elif [[ "$latest_state" == "ACTIVE" ]]; then
            status_icon_var="unknown"
        else
            status_icon_var="warning"
        fi

        printf "  $(status_icon "$status_icon_var") %-30s : %s\n" "$workflow" "$latest_state"
    done

    echo ""
    if [[ $healthy_count -eq $total_count ]]; then
        echo -e "  $(status_icon "healthy") ${BOLD}All workflows healthy${NC} ($healthy_count/$total_count)"
    elif [[ $healthy_count -ge $((total_count * 3 / 4)) ]]; then
        echo -e "  $(status_icon "warning") ${BOLD}Most workflows healthy${NC} ($healthy_count/$total_count)"
    else
        echo -e "  $(status_icon "critical") ${BOLD}Multiple workflow failures${NC} ($healthy_count/$total_count)"
    fi
}

###############################################################################
# Backfill Progress (if running)
###############################################################################

check_backfill_progress() {
    print_section "⏳ BACKFILL PROGRESS"

    # Check if backfill orchestrator is running
    if pgrep -f "backfill_orchestrator.sh" > /dev/null 2>&1; then
        echo -e "  $(status_icon "unknown") ${YELLOW}Backfill orchestrator is RUNNING${NC}"

        # Try to find latest log
        local latest_log=$(ls -t "$PROJECT_ROOT"/logs/orchestrator_*.log 2>/dev/null | head -n1)
        if [[ -n "$latest_log" ]]; then
            echo -e "  Log file: $latest_log"
            echo ""
            echo -e "  ${BOLD}Recent progress:${NC}"
            tail -n 10 "$latest_log" | sed 's/^/    /'
        fi
    else
        # Check Phase 3/4 coverage to infer backfill status
        local phase3_coverage=$(bq query --use_legacy_sql=false --format=csv --max_rows=1 \
            "SELECT COUNT(DISTINCT game_date) as dates
            FROM \`${PROJECT_ID}.nba_analytics.player_game_summary\`
            WHERE game_date >= '2021-10-01'" 2>/dev/null | tail -n1)

        local phase4_coverage=$(bq query --use_legacy_sql=false --format=csv --max_rows=1 \
            "SELECT COUNT(DISTINCT game_date) as dates
            FROM \`${PROJECT_ID}.nba_precompute.player_composite_factors\`
            WHERE game_date >= '2021-10-01'" 2>/dev/null | tail -n1)

        echo -e "  $(status_icon "healthy") ${GREEN}No active backfill running${NC}"
        echo ""
        echo -e "  ${BOLD}Historical Coverage:${NC}"

        if [[ -n "$phase3_coverage" && "$phase3_coverage" != "dates" ]]; then
            echo -e "  Phase 3 (Analytics): $phase3_coverage dates since 2021-10-01"
        fi

        if [[ -n "$phase4_coverage" && "$phase4_coverage" != "dates" ]]; then
            echo -e "  Phase 4 (Precompute): $phase4_coverage dates since 2021-10-01"
        fi
    fi
}

###############################################################################
# Recent Errors (Last 24h)
###############################################################################

check_recent_errors() {
    print_section "⚠️  RECENT ERRORS (Last 24 Hours)"

    # Use Python nba-monitor if available, otherwise use gcloud logging
    if [[ -f "$PROJECT_ROOT/monitoring/scripts/nba-monitor" ]]; then
        echo -e "  ${BOLD}Fetching errors via nba-monitor...${NC}"
        echo ""
        python3 "$PROJECT_ROOT/monitoring/scripts/nba-monitor" errors 24 2>/dev/null || {
            echo -e "  $(status_icon "warning") ${YELLOW}nba-monitor failed, using gcloud logging${NC}"
            check_errors_gcloud
        }
    else
        check_errors_gcloud
    fi
}

check_errors_gcloud() {
    local errors=$(gcloud logging read \
        'resource.type="cloud_run_revision" AND severity>=ERROR' \
        --limit=10 \
        --format="csv[no-heading](timestamp,severity,textPayload)" \
        --freshness=1d 2>/dev/null || echo "")

    if [[ -n "$errors" ]]; then
        echo -e "  ${BOLD}Recent errors:${NC}"
        echo ""
        echo "$errors" | head -n 10 | while IFS=',' read -r timestamp severity message; do
            timestamp=$(echo "$timestamp" | cut -d'T' -f2 | cut -d'.' -f1)
            message=$(echo "$message" | tr -d '"' | head -c 80)
            echo -e "  $(status_icon "critical") [$timestamp] $message"
        done
    else
        echo -e "  $(status_icon "healthy") ${GREEN}No errors found in last 24 hours${NC}"
    fi
}

###############################################################################
# Action Items
###############################################################################

show_action_items() {
    print_section "🎯 ACTION ITEMS"

    local actions=()

    # Check if any workflows failed
    local failed_workflows=$(gcloud workflows executions list \
        --filter="state=FAILED AND startTime>=$(date -d '24 hours ago' -Iseconds)" \
        --format="value(name)" 2>/dev/null | wc -l)

    if [[ $failed_workflows -gt 0 ]]; then
        actions+=("${RED}✗${NC} Investigate $failed_workflows failed workflow execution(s)")
    fi

    # Check if Phase 4 coverage is low
    local phase4_dates=$(bq query --use_legacy_sql=false --format=csv --max_rows=1 \
        "SELECT COUNT(DISTINCT game_date) FROM \`${PROJECT_ID}.nba_precompute.player_composite_factors\`
        WHERE game_date >= '2024-10-01'" 2>/dev/null | tail -n1)

    if [[ -n "$phase4_dates" && "$phase4_dates" != "f0_" && $phase4_dates -lt 40 ]]; then
        actions+=("${YELLOW}⚠${NC} Phase 4 coverage low for 2024-25 season (${phase4_dates} dates) - consider backfill")
    fi

    # Check for stale data (no updates in 48h)
    local last_update=$(bq query --use_legacy_sql=false --format=csv --max_rows=1 \
        "SELECT MAX(game_date) FROM \`${PROJECT_ID}.nba_analytics.player_game_summary\`" 2>/dev/null | tail -n1)

    if [[ -n "$last_update" && "$last_update" != "f0_" ]]; then
        local days_old=$(( ( $(date +%s) - $(date -d "$last_update" +%s) ) / 86400 ))
        if [[ $days_old -gt 2 ]]; then
            actions+=("${YELLOW}⚠${NC} Data appears stale - last update: $last_update (${days_old} days ago)")
        fi
    fi

    # Display actions
    if [[ ${#actions[@]} -gt 0 ]]; then
        echo -e "  ${BOLD}Items requiring attention:${NC}"
        echo ""
        for action in "${actions[@]}"; do
            echo -e "    $action"
        done
    else
        echo -e "  $(status_icon "healthy") ${GREEN}No immediate actions required${NC}"
    fi
}

###############################################################################
# Quick Status
###############################################################################

show_quick_status() {
    print_header "⚡ NBA STATS SCRAPER - QUICK STATUS"

    echo -e "${BOLD}Timestamp:${NC} $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo ""

    # Pipeline health (simplified)
    local today=$(date -d "yesterday" +%Y-%m-%d)
    local phase3_count=$(bq query --use_legacy_sql=false --format=csv --max_rows=1 \
        "SELECT COUNT(*) FROM \`${PROJECT_ID}.nba_analytics.player_game_summary\` WHERE game_date = '$today'" 2>/dev/null | tail -n1)

    if [[ -n "$phase3_count" && "$phase3_count" != "f0_" && $phase3_count -gt 0 ]]; then
        echo -e "$(status_icon "healthy") Pipeline Data: ${GREEN}CURRENT${NC} ($phase3_count player-games yesterday)"
    else
        echo -e "$(status_icon "warning") Pipeline Data: ${YELLOW}CHECKING${NC} (no data for yesterday)"
    fi

    # Workflow health
    local healthy_workflows=$(gcloud workflows executions list \
        --filter="state=SUCCEEDED AND startTime>=$(date -d '6 hours ago' -Iseconds)" \
        --format="value(name)" 2>/dev/null | wc -l)

    if [[ $healthy_workflows -ge 1 ]]; then
        echo -e "$(status_icon "healthy") Workflows: ${GREEN}ACTIVE${NC} ($healthy_workflows successful in last 6h)"
    else
        echo -e "$(status_icon "warning") Workflows: ${YELLOW}QUIET${NC} (no successful executions in 6h)"
    fi

    # Recent errors
    local error_count=$(gcloud logging read 'severity>=ERROR' --limit=100 --freshness=1d --format="value(severity)" 2>/dev/null | wc -l)

    if [[ $error_count -eq 0 ]]; then
        echo -e "$(status_icon "healthy") Errors: ${GREEN}NONE${NC} (last 24h)"
    elif [[ $error_count -lt 10 ]]; then
        echo -e "$(status_icon "warning") Errors: ${YELLOW}FEW${NC} ($error_count in last 24h)"
    else
        echo -e "$(status_icon "critical") Errors: ${RED}MULTIPLE${NC} ($error_count in last 24h)"
    fi

    echo ""
    echo -e "${BOLD}Run './bin/operations/ops_dashboard.sh' for full details${NC}"
}

###############################################################################
# Full Dashboard
###############################################################################

show_full_dashboard() {
    print_header "🎛️  NBA STATS SCRAPER - EMERGENCY OPERATIONS DASHBOARD"

    echo -e "${BOLD}Project:${NC} $PROJECT_ID"
    echo -e "${BOLD}Region:${NC} $REGION"
    echo -e "${BOLD}Timestamp:${NC} $(date '+%Y-%m-%d %H:%M:%S %Z')"

    check_pipeline_health
    check_validation_status
    check_workflow_health
    check_backfill_progress
    check_recent_errors
    show_action_items

    echo ""
    print_header "🔚 END OF DASHBOARD"
    echo ""
    echo -e "${BOLD}Quick Commands:${NC}"
    echo -e "  ${CYAN}./bin/operations/ops_dashboard.sh quick${NC}       - Quick status check"
    echo -e "  ${CYAN}./bin/operations/ops_dashboard.sh pipeline${NC}    - Pipeline health only"
    echo -e "  ${CYAN}./bin/operations/ops_dashboard.sh errors${NC}      - Recent errors only"
    echo -e "  ${CYAN}python3 monitoring/scripts/nba-monitor${NC}        - Detailed workflow monitoring"
    echo ""
}

###############################################################################
# Main Entry Point
###############################################################################

main() {
    local mode="${1:-full}"

    case "$mode" in
        "quick"|"q")
            show_quick_status
            ;;
        "pipeline"|"p")
            print_header "📊 PIPELINE HEALTH"
            check_pipeline_health
            ;;
        "validation"|"v")
            print_header "✅ VALIDATION STATUS"
            check_validation_status
            ;;
        "workflows"|"w")
            print_header "🔄 WORKFLOW HEALTH"
            check_workflow_health
            ;;
        "backfill"|"b")
            print_header "⏳ BACKFILL STATUS"
            check_backfill_progress
            ;;
        "errors"|"e")
            print_header "⚠️  RECENT ERRORS"
            check_recent_errors
            ;;
        "actions"|"a")
            print_header "🎯 ACTION ITEMS"
            show_action_items
            ;;
        "full"|"f"|"")
            show_full_dashboard
            ;;
        "help"|"h"|"-h"|"--help")
            echo "Usage: $0 [mode]"
            echo ""
            echo "Modes:"
            echo "  quick, q      - Quick status overview"
            echo "  pipeline, p   - Pipeline health (Phase 1-4)"
            echo "  validation, v - Data quality validation"
            echo "  workflows, w  - Workflow orchestration health"
            echo "  backfill, b   - Backfill progress"
            echo "  errors, e     - Recent errors (24h)"
            echo "  actions, a    - Action items"
            echo "  full, f       - Full dashboard (default)"
            echo "  help, h       - Show this help"
            ;;
        *)
            echo "Unknown mode: $mode"
            echo "Run '$0 help' for usage"
            exit 1
            ;;
    esac
}

# Run main
main "$@"
