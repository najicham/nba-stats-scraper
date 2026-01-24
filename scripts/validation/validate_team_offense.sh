#!/bin/bash
# Validate team_offense_game_summary backfill results
# Usage: validate_team_offense.sh <start_date> <end_date> [config_file]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_validation.sh"

START_DATE=$1
END_DATE=$2
CONFIG_FILE=${3:-"$SCRIPT_DIR/../config/backfill_thresholds.yaml"}

if [[ -z "$START_DATE" || -z "$END_DATE" ]]; then
    log_error "Usage: $0 <start_date> <end_date> [config_file]"
    exit 1
fi

log_section "VALIDATING TEAM_OFFENSE_GAME_SUMMARY"

log_info "Date range: $START_DATE to $END_DATE"
log_info "Config: $CONFIG_FILE"

# Load thresholds from config
MIN_GAMES=$(parse_yaml_value "$CONFIG_FILE" "min_games")
MIN_SUCCESS_RATE=$(parse_yaml_value "$CONFIG_FILE" "min_success_rate")
MIN_QUALITY_SCORE=$(parse_yaml_value "$CONFIG_FILE" "min_quality_score")
MIN_PROD_READY_PCT=$(parse_yaml_value "$CONFIG_FILE" "min_production_ready_pct")

log_info "Thresholds: games≥$(format_number $MIN_GAMES), success≥${MIN_SUCCESS_RATE}%, quality≥${MIN_QUALITY_SCORE}, prod_ready≥${MIN_PROD_READY_PCT}%"
echo ""

# Validation 1: Check game count
log_info "Check 1/4: Game count..."
GAME_COUNT=$(bq_query_value "
SELECT COUNT(DISTINCT game_id)
FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
WHERE game_date >= '$START_DATE' AND game_date <= '$END_DATE'
")

if [[ $? -eq 0 ]]; then
    if check_threshold "$GAME_COUNT" "$MIN_GAMES" ">="; then
        log_success "Game count: $(format_number $GAME_COUNT) (threshold: $(format_number $MIN_GAMES)+) ✓"
        CHECK1_PASS=true
    else
        log_error "Game count: $(format_number $GAME_COUNT) (threshold: $(format_number $MIN_GAMES)+) ✗"
        CHECK1_PASS=false
    fi
else
    log_error "Failed to query game count"
    CHECK1_PASS=false
fi

# Validation 2: Check record count
log_info "Check 2/4: Record count..."
RECORD_COUNT=$(bq_query_value "
SELECT COUNT(*)
FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
WHERE game_date >= '$START_DATE' AND game_date <= '$END_DATE'
")

if [[ $? -eq 0 ]]; then
    EXPECTED_RECORDS=$((GAME_COUNT * 2))  # 2 teams per game
    log_success "Record count: $(format_number $RECORD_COUNT) (~2 per game) ✓"
    CHECK2_PASS=true
else
    log_error "Failed to query record count"
    CHECK2_PASS=false
fi

# Validation 3: Check quality score distribution
log_info "Check 3/4: Quality metrics..."
QUALITY_RESULT=$(bq_query "
SELECT
  ROUND(AVG(quality_score), 1) as avg_quality,
  ROUND(100.0 * COUNTIF(is_production_ready) / COUNT(*), 1) as prod_ready_pct,
  ROUND(100.0 * COUNTIF(quality_tier IN ('gold', 'silver')) / COUNT(*), 1) as gold_silver_pct
FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
WHERE game_date >= '$START_DATE' AND game_date <= '$END_DATE'
" csv)

if [[ $? -eq 0 ]]; then
    AVG_QUALITY=$(echo "$QUALITY_RESULT" | tail -1 | cut -d',' -f1)
    PROD_READY_PCT=$(echo "$QUALITY_RESULT" | tail -1 | cut -d',' -f2)
    GOLD_SILVER_PCT=$(echo "$QUALITY_RESULT" | tail -1 | cut -d',' -f3)

    if check_threshold "$AVG_QUALITY" "$MIN_QUALITY_SCORE" ">="; then
        log_success "Avg quality score: $AVG_QUALITY (threshold: ${MIN_QUALITY_SCORE}+) ✓"
        QUALITY_PASS=true
    else
        log_warning "Avg quality score: $AVG_QUALITY (threshold: ${MIN_QUALITY_SCORE}+) ⚠"
        QUALITY_PASS=false
    fi

    if check_threshold "$PROD_READY_PCT" "$MIN_PROD_READY_PCT" ">="; then
        log_success "Production ready: ${PROD_READY_PCT}% (threshold: ${MIN_PROD_READY_PCT}%+) ✓"
        PROD_READY_PASS=true
    else
        log_warning "Production ready: ${PROD_READY_PCT}% (threshold: ${MIN_PROD_READY_PCT}%+) ⚠"
        PROD_READY_PASS=false
    fi

    log_info "Gold/Silver tier: ${GOLD_SILVER_PCT}%"

    if [[ "$QUALITY_PASS" == "true" && "$PROD_READY_PASS" == "true" ]]; then
        CHECK3_PASS=true
    else
        CHECK3_PASS=false
    fi
else
    log_error "Failed to query quality metrics"
    CHECK3_PASS=false
fi

# Validation 4: Check for critical issues
log_info "Check 4/4: Critical issues..."
CRITICAL_ISSUES=$(bq_query_value "
SELECT COUNT(*)
FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
WHERE game_date >= '$START_DATE' AND game_date <= '$END_DATE'
  AND (
    'all_sources_failed' IN UNNEST(quality_issues)
    OR 'missing_required' IN UNNEST(quality_issues)
  )
")

if [[ $? -eq 0 ]]; then
    if [[ $CRITICAL_ISSUES -eq 0 ]]; then
        log_success "No critical blocking issues ✓"
        CHECK4_PASS=true
    else
        log_warning "Found $CRITICAL_ISSUES records with blocking issues ⚠"
        CHECK4_PASS=false
    fi
else
    log_error "Failed to query critical issues"
    CHECK4_PASS=false
fi

# Final verdict
echo ""
log_section "VALIDATION SUMMARY"

if [[ "$CHECK1_PASS" == "true" && "$CHECK2_PASS" == "true" && "$CHECK3_PASS" == "true" && "$CHECK4_PASS" == "true" ]]; then
    log_success "team_offense_game_summary: ALL CHECKS PASSED ✓"
    log_info "Games: $(format_number $GAME_COUNT), Records: $(format_number $RECORD_COUNT)"
    log_info "Quality: $AVG_QUALITY, Production Ready: ${PROD_READY_PCT}%"
    exit 0
else
    log_error "team_offense_game_summary: VALIDATION FAILED ✗"
    log_info "Failed checks:"
    [[ "$CHECK1_PASS" != "true" ]] && log_error "  - Game count below threshold"
    [[ "$CHECK2_PASS" != "true" ]] && log_error "  - Record count query failed"
    [[ "$CHECK3_PASS" != "true" ]] && log_error "  - Quality metrics below threshold"
    [[ "$CHECK4_PASS" != "true" ]] && log_error "  - Critical issues detected"
    exit 1
fi
