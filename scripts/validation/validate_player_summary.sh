#!/bin/bash
# Validate player_game_summary backfill results
# Usage: validate_player_summary.sh <start_date> <end_date> [config_file]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_validation.sh"

START_DATE=$1
END_DATE=$2
CONFIG_FILE=${3:-"$SCRIPT_DIR/../config/backfill_thresholds.yaml"}

if [[ -z "$START_DATE" || -z "$END_DATE" ]]; then
    log_error "Usage: $0 <start_date> <end_date> [config_file]"
    exit 1
fi

log_section "VALIDATING PLAYER_GAME_SUMMARY"

log_info "Date range: $START_DATE to $END_DATE"
log_info "Config: $CONFIG_FILE"

# Load thresholds from config
MIN_RECORDS=$(parse_yaml_value "$CONFIG_FILE" "min_records")
MIN_SUCCESS_RATE=$(parse_yaml_value "$CONFIG_FILE" "min_success_rate")
MINUTES_PCT=$(parse_yaml_value "$CONFIG_FILE" "minutes_played_pct")
USAGE_PCT=$(parse_yaml_value "$CONFIG_FILE" "usage_rate_pct")
SHOT_ZONES_PCT=$(parse_yaml_value "$CONFIG_FILE" "shot_zones_pct")
MIN_QUALITY=$(parse_yaml_value "$CONFIG_FILE" "min_quality_score")
MIN_PROD_READY=$(parse_yaml_value "$CONFIG_FILE" "min_production_ready_pct")

log_info "Thresholds: records≥$(format_number $MIN_RECORDS), minutes≥${MINUTES_PCT}%, usage≥${USAGE_PCT}%, shot_zones≥${SHOT_ZONES_PCT}%"
echo ""

# Validation 1: Check record count
log_info "Check 1/5: Record count..."
RECORD_COUNT=$(bq_query_value "
SELECT COUNT(*)
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '$START_DATE' AND game_date <= '$END_DATE'
  AND points IS NOT NULL
")

if [[ $? -eq 0 ]]; then
    if check_threshold "$RECORD_COUNT" "$MIN_RECORDS" ">="; then
        log_success "Record count: $(format_number $RECORD_COUNT) (threshold: $(format_number $MIN_RECORDS)+) ✓"
        CHECK1_PASS=true
    else
        log_error "Record count: $(format_number $RECORD_COUNT) (threshold: $(format_number $MIN_RECORDS)+) ✗"
        CHECK1_PASS=false
    fi
else
    log_error "Failed to query record count"
    CHECK1_PASS=false
fi

# Validation 2: Check feature coverage (CRITICAL)
log_info "Check 2/5: Feature coverage (CRITICAL)..."
COVERAGE_RESULT=$(bq_query "
SELECT
  ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL) / COUNT(*), 1) as minutes_pct,
  ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as usage_pct,
  ROUND(100.0 * COUNTIF(paint_attempts IS NOT NULL) / COUNT(*), 1) as shot_zones_pct
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '$START_DATE' AND game_date <= '$END_DATE'
  AND points IS NOT NULL
" csv)

if [[ $? -eq 0 ]]; then
    ACTUAL_MINUTES_PCT=$(echo "$COVERAGE_RESULT" | tail -1 | cut -d',' -f1)
    ACTUAL_USAGE_PCT=$(echo "$COVERAGE_RESULT" | tail -1 | cut -d',' -f2)
    ACTUAL_SHOT_ZONES_PCT=$(echo "$COVERAGE_RESULT" | tail -1 | cut -d',' -f3)

    # Check minutes_played
    if check_threshold "$ACTUAL_MINUTES_PCT" "$MINUTES_PCT" ">="; then
        log_success "minutes_played: ${ACTUAL_MINUTES_PCT}% (threshold: ${MINUTES_PCT}%+) ✓"
        MINUTES_PASS=true
    else
        log_error "minutes_played: ${ACTUAL_MINUTES_PCT}% (threshold: ${MINUTES_PCT}%+) ✗ CRITICAL"
        MINUTES_PASS=false
    fi

    # Check usage_rate
    if check_threshold "$ACTUAL_USAGE_PCT" "$USAGE_PCT" ">="; then
        log_success "usage_rate: ${ACTUAL_USAGE_PCT}% (threshold: ${USAGE_PCT}%+) ✓"
        USAGE_PASS=true
    else
        log_error "usage_rate: ${ACTUAL_USAGE_PCT}% (threshold: ${USAGE_PCT}%+) ✗ CRITICAL"
        USAGE_PASS=false
    fi

    # Check shot_zones (less critical)
    if check_threshold "$ACTUAL_SHOT_ZONES_PCT" "$SHOT_ZONES_PCT" ">="; then
        log_success "shot_zones: ${ACTUAL_SHOT_ZONES_PCT}% (threshold: ${SHOT_ZONES_PCT}%+) ✓"
        SHOT_ZONES_PASS=true
    else
        log_warning "shot_zones: ${ACTUAL_SHOT_ZONES_PCT}% (threshold: ${SHOT_ZONES_PCT}%+) ⚠  (acceptable)"
        SHOT_ZONES_PASS=true  # Don't fail on shot zones
    fi

    if [[ "$MINUTES_PASS" == "true" && "$USAGE_PASS" == "true" && "$SHOT_ZONES_PASS" == "true" ]]; then
        CHECK2_PASS=true
    else
        CHECK2_PASS=false
    fi
else
    log_error "Failed to query feature coverage"
    CHECK2_PASS=false
fi

# Validation 3: Check quality metrics
log_info "Check 3/5: Quality metrics..."
QUALITY_RESULT=$(bq_query "
SELECT
  ROUND(AVG(quality_score), 1) as avg_quality,
  ROUND(100.0 * COUNTIF(is_production_ready) / COUNT(*), 1) as prod_ready_pct,
  ROUND(100.0 * COUNTIF(quality_tier IN ('gold', 'silver')) / COUNT(*), 1) as gold_silver_pct
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '$START_DATE' AND game_date <= '$END_DATE'
  AND points IS NOT NULL
" csv)

if [[ $? -eq 0 ]]; then
    AVG_QUALITY=$(echo "$QUALITY_RESULT" | tail -1 | cut -d',' -f1)
    PROD_READY_PCT=$(echo "$QUALITY_RESULT" | tail -1 | cut -d',' -f2)
    GOLD_SILVER_PCT=$(echo "$QUALITY_RESULT" | tail -1 | cut -d',' -f3)

    if check_threshold "$AVG_QUALITY" "$MIN_QUALITY" ">="; then
        log_success "Avg quality score: $AVG_QUALITY (threshold: ${MIN_QUALITY}+) ✓"
        QUALITY_PASS=true
    else
        log_warning "Avg quality score: $AVG_QUALITY (threshold: ${MIN_QUALITY}+) ⚠"
        QUALITY_PASS=false
    fi

    if check_threshold "$PROD_READY_PCT" "$MIN_PROD_READY" ">="; then
        log_success "Production ready: ${PROD_READY_PCT}% (threshold: ${MIN_PROD_READY}%+) ✓"
        PROD_READY_PASS=true
    else
        log_warning "Production ready: ${PROD_READY_PCT}% (threshold: ${MIN_PROD_READY}%+) ⚠"
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
log_info "Check 4/5: Critical issues..."
CRITICAL_ISSUES=$(bq_query_value "
SELECT COUNT(*)
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '$START_DATE' AND game_date <= '$END_DATE'
  AND points IS NOT NULL
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

# Validation 5: Spot check known data quality
log_info "Check 5/5: Spot check..."
SPOT_CHECK=$(bq_query "
SELECT
  game_date,
  player_full_name,
  minutes_played,
  usage_rate,
  paint_attempts,
  points
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date >= '$START_DATE' AND game_date <= '$END_DATE'
  AND points > 20
ORDER BY game_date DESC, points DESC
LIMIT 3
" csv)

if [[ $? -eq 0 ]]; then
    log_info "Sample high-scorers:"
    echo "$SPOT_CHECK" | column -t -s','
    CHECK5_PASS=true
else
    log_error "Failed to run spot check"
    CHECK5_PASS=false
fi

# Final verdict
echo ""
log_section "VALIDATION SUMMARY"

# Critical checks: 1 (record count) and 2 (feature coverage)
CRITICAL_PASS=true
if [[ "$CHECK1_PASS" != "true" || "$CHECK2_PASS" != "true" ]]; then
    CRITICAL_PASS=false
fi

if [[ "$CRITICAL_PASS" == "true" ]]; then
    log_success "player_game_summary: CRITICAL CHECKS PASSED ✓"
    log_info "Records: $(format_number $RECORD_COUNT)"
    log_info "Coverage: minutes=${ACTUAL_MINUTES_PCT}%, usage=${ACTUAL_USAGE_PCT}%, shot_zones=${ACTUAL_SHOT_ZONES_PCT}%"
    log_info "Quality: $AVG_QUALITY, Production Ready: ${PROD_READY_PCT}%"

    if [[ "$CHECK3_PASS" != "true" || "$CHECK4_PASS" != "true" ]]; then
        log_warning "Some non-critical checks had warnings (acceptable to proceed)"
    fi

    exit 0
else
    log_error "player_game_summary: CRITICAL VALIDATION FAILED ✗"
    log_info "Failed critical checks:"
    [[ "$CHECK1_PASS" != "true" ]] && log_error "  - Record count below threshold"
    [[ "$CHECK2_PASS" != "true" ]] && log_error "  - Feature coverage below threshold (minutes/usage_rate)"
    exit 1
fi
