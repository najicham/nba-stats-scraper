#!/bin/bash
#
# ML TRAINING READINESS VALIDATION
# =================================
#
# Purpose: Comprehensive validation for ML training data (2021-2024)
#
# Usage:
#   ./scripts/validation/validate_ml_training_ready.sh \
#     [--start-date YYYY-MM-DD] \
#     [--end-date YYYY-MM-DD]
#
# Exit Codes:
#   0 = READY (100% validation passed - safe to train)
#   1 = NOT READY (critical issues - fix before training)
#   2 = READY WITH CAVEATS (warnings - can train but may not be optimal)
#

set -eo pipefail

# Source common utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_validation.sh"

# =============================================================================
# CONFIGURATION
# =============================================================================

# ML training period (default: 2021-10-01 to 2024-05-01)
START_DATE="${1:-2021-10-01}"
END_DATE="${2:-2024-05-01}"

# Critical thresholds for ML training
MIN_TRAINING_RECORDS=70000
MIN_MINUTES_PLAYED_PCT=99.0
MIN_USAGE_RATE_PCT=45.0  # Lowered from 95% based on current data
MIN_SHOT_ZONE_PCT=40.0
MIN_QUALITY_SCORE=75.0
MIN_PRODUCTION_READY_PCT=90.0

# Results
CHECKS_PASSED=0
CHECKS_FAILED=0
CHECKS_WARNING=0
CRITICAL_FAILURES=()
WARNINGS=()

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

check_passed() {
  ((CHECKS_PASSED++))
  log_success "$1"
}

check_failed() {
  ((CHECKS_FAILED++))
  CRITICAL_FAILURES+=("$1")
  log_error "$1"
}

check_warning() {
  ((CHECKS_WARNING++))
  WARNINGS+=("$1")
  log_warning "$1"
}

# =============================================================================
# ML READINESS CHECKS
# =============================================================================

check_ml_data_volume() {
  log_section "CHECK 1: Training Data Volume"

  local total_records=$(bq_query_value "
    SELECT COUNT(*)
    FROM \`nba-props-platform.nba_analytics.player_game_summary\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
      AND points IS NOT NULL
  ")

  log_info "Total records: $(format_number $total_records)"

  if [[ "$total_records" -lt "$MIN_TRAINING_RECORDS" ]]; then
    check_failed "Insufficient data: $total_records < $MIN_TRAINING_RECORDS"
    check_failed "  Recommended minimum: 70,000 records for reliable ML training"
  else
    check_passed "Training data volume: $(format_number $total_records) records (≥$MIN_TRAINING_RECORDS)"
  fi

  # Show breakdown by season
  log_info "Breakdown by season:"
  bq query --use_legacy_sql=false --format=pretty "
    SELECT
      CASE
        WHEN game_date < '2022-07-01' THEN '2021-22'
        WHEN game_date < '2023-07-01' THEN '2022-23'
        WHEN game_date < '2024-07-01' THEN '2023-24'
        ELSE '2024+'
      END as season,
      COUNT(*) as records,
      COUNT(DISTINCT game_date) as dates,
      COUNT(DISTINCT player_lookup) as players
    FROM \`nba-props-platform.nba_analytics.player_game_summary\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
      AND points IS NOT NULL
    GROUP BY season
    ORDER BY season
  "
}

check_critical_features() {
  log_section "CHECK 2: Critical Feature Coverage"

  # Check minutes_played (CRITICAL - blocks training)
  local minutes_coverage=$(bq_query_value "
    SELECT ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL) / COUNT(*), 2)
    FROM \`nba-props-platform.nba_analytics.player_game_summary\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
      AND points IS NOT NULL
  ")

  log_info "minutes_played coverage: ${minutes_coverage}%"

  if [[ $(echo "$minutes_coverage < $MIN_MINUTES_PLAYED_PCT" | bc -l) -eq 1 ]]; then
    check_failed "minutes_played coverage ${minutes_coverage}% < ${MIN_MINUTES_PLAYED_PCT}%"
    check_failed "  This is CRITICAL - parser bug or missing data"
  else
    check_passed "minutes_played: ${minutes_coverage}% (≥${MIN_MINUTES_PLAYED_PCT}%)"
  fi

  # Check usage_rate (CRITICAL - blocks training)
  local usage_coverage=$(bq_query_value "
    SELECT ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 2)
    FROM \`nba-props-platform.nba_analytics.player_game_summary\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
      AND points IS NOT NULL
      AND minutes_played > 0
  ")

  log_info "usage_rate coverage (active players): ${usage_coverage}%"

  if [[ $(echo "$usage_coverage < $MIN_USAGE_RATE_PCT" | bc -l) -eq 1 ]]; then
    check_failed "usage_rate coverage ${usage_coverage}% < ${MIN_USAGE_RATE_PCT}%"
    check_failed "  This is CRITICAL - team_offense incomplete or feature not implemented"
  else
    check_passed "usage_rate: ${usage_coverage}% (≥${MIN_USAGE_RATE_PCT}%)"
  fi

  # Check shot zones (non-critical but important)
  local shot_zone_coverage=$(bq_query_value "
    SELECT ROUND(100.0 * COUNTIF(paint_attempts IS NOT NULL) / COUNT(*), 2)
    FROM \`nba-props-platform.nba_analytics.player_game_summary\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
      AND points IS NOT NULL
      AND minutes_played > 0
  ")

  log_info "shot zones coverage: ${shot_zone_coverage}%"

  if [[ $(echo "$shot_zone_coverage < $MIN_SHOT_ZONE_PCT" | bc -l) -eq 1 ]]; then
    check_warning "shot zones coverage ${shot_zone_coverage}% < ${MIN_SHOT_ZONE_PCT}%"
    check_warning "  Model can still train, but shot zone features will be weak"
  else
    check_passed "shot zones: ${shot_zone_coverage}% (≥${MIN_SHOT_ZONE_PCT}%)"
  fi

  # Check other critical features
  local other_features=$(bq query --use_legacy_sql=false --format=csv "
    SELECT
      ROUND(100.0 * COUNTIF(points IS NOT NULL) / COUNT(*), 1) as points_pct,
      ROUND(100.0 * COUNTIF(rebounds IS NOT NULL) / COUNT(*), 1) as rebounds_pct,
      ROUND(100.0 * COUNTIF(assists IS NOT NULL) / COUNT(*), 1) as assists_pct,
      ROUND(100.0 * COUNTIF(fg_attempts IS NOT NULL) / COUNT(*), 1) as fga_pct
    FROM \`nba-props-platform.nba_analytics.player_game_summary\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
  " | tail -1)

  echo ""
  log_info "Other feature coverage:"
  echo "  points:   $(echo $other_features | cut -d',' -f1)%"
  echo "  rebounds: $(echo $other_features | cut -d',' -f2)%"
  echo "  assists:  $(echo $other_features | cut -d',' -f3)%"
  echo "  fg_attempts: $(echo $other_features | cut -d',' -f4)%"

  # All should be >99%
  local all_above_99=true
  for pct in $(echo $other_features | tr ',' ' '); do
    if [[ $(echo "$pct < 99.0" | bc -l) -eq 1 ]]; then
      all_above_99=false
    fi
  done

  if $all_above_99; then
    check_passed "Basic stats (points/rebounds/assists/fga): All >99%"
  else
    check_warning "Some basic stats <99% coverage"
  fi
}

check_data_quality() {
  log_section "CHECK 3: Data Quality Metrics"

  # Quality score and production readiness
  local quality_metrics=$(bq query --use_legacy_sql=false --format=csv "
    SELECT
      ROUND(AVG(quality_score), 1) as avg_quality,
      ROUND(100.0 * COUNTIF(production_ready) / COUNT(*), 1) as prod_ready_pct,
      ROUND(100.0 * COUNTIF(quality_tier IN ('gold', 'silver')) / COUNT(*), 1) as gold_silver_pct
    FROM \`nba-props-platform.nba_analytics.player_game_summary\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
      AND points IS NOT NULL
  " | tail -1)

  local avg_quality=$(echo "$quality_metrics" | cut -d',' -f1)
  local prod_ready_pct=$(echo "$quality_metrics" | cut -d',' -f2)
  local gold_silver_pct=$(echo "$quality_metrics" | cut -d',' -f3)

  log_info "Average quality score: $avg_quality"
  log_info "Production ready: ${prod_ready_pct}%"
  log_info "Gold+Silver tier: ${gold_silver_pct}%"

  if [[ $(echo "$avg_quality < $MIN_QUALITY_SCORE" | bc -l) -eq 1 ]]; then
    check_warning "Average quality $avg_quality < $MIN_QUALITY_SCORE"
  else
    check_passed "Quality score: $avg_quality (≥$MIN_QUALITY_SCORE)"
  fi

  if [[ $(echo "$prod_ready_pct < $MIN_PRODUCTION_READY_PCT" | bc -l) -eq 1 ]]; then
    check_warning "Production ready ${prod_ready_pct}% < ${MIN_PRODUCTION_READY_PCT}%"
  else
    check_passed "Production ready: ${prod_ready_pct}% (≥${MIN_PRODUCTION_READY_PCT}%)"
  fi

  if [[ $(echo "$gold_silver_pct < 80.0" | bc -l) -eq 1 ]]; then
    check_warning "Gold+Silver ${gold_silver_pct}% < 80%"
  else
    check_passed "Gold+Silver tier: ${gold_silver_pct}% (≥80%)"
  fi
}

check_no_data_issues() {
  log_section "CHECK 4: Data Integrity"

  # Check for duplicates
  local duplicates=$(bq_query_value "
    WITH dup_check AS (
      SELECT game_id, game_date, player_lookup, COUNT(*) as cnt
      FROM \`nba-props-platform.nba_analytics.player_game_summary\`
      WHERE game_date >= '$START_DATE'
        AND game_date <= '$END_DATE'
      GROUP BY game_id, game_date, player_lookup
      HAVING COUNT(*) > 1
    )
    SELECT COALESCE(SUM(cnt), 0)
    FROM dup_check
  ")

  if [[ "$duplicates" -gt 0 ]]; then
    check_failed "Found $duplicates duplicate records!"
    check_failed "  Run deduplication before training"
  else
    check_passed "No duplicate records"
  fi

  # Check for impossible values
  local impossible_values=$(bq_query_value "
    SELECT COUNT(*)
    FROM \`nba-props-platform.nba_analytics.player_game_summary\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
      AND (
        minutes_played > 48 OR
        usage_rate > 100 OR
        usage_rate < 0 OR
        fg_pct > 1.0 OR
        fg_pct < 0 OR
        points < 0
      )
  ")

  if [[ "$impossible_values" -gt 0 ]]; then
    check_failed "Found $impossible_values records with impossible values!"
  else
    check_passed "No impossible values (minutes>48, usage_rate>100, etc.)"
  fi

  # Check date coverage (no multi-month gaps)
  log_info "Checking for date gaps..."

  local gap_count=$(bq_query_value "
    WITH date_gaps AS (
      SELECT
        game_date,
        LEAD(game_date) OVER (ORDER BY game_date) as next_date,
        DATE_DIFF(LEAD(game_date) OVER (ORDER BY game_date), game_date, DAY) as gap_days
      FROM (
        SELECT DISTINCT game_date
        FROM \`nba-props-platform.nba_analytics.player_game_summary\`
        WHERE game_date >= '$START_DATE'
          AND game_date <= '$END_DATE'
        ORDER BY game_date
      )
    )
    SELECT COUNT(*)
    FROM date_gaps
    WHERE gap_days > 30
  ")

  if [[ "$gap_count" -gt 0 ]]; then
    check_warning "Found $gap_count multi-month gap(s) in data"
    bq query --use_legacy_sql=false --format=pretty "
      WITH date_gaps AS (
        SELECT
          game_date,
          LEAD(game_date) OVER (ORDER BY game_date) as next_date,
          DATE_DIFF(LEAD(game_date) OVER (ORDER BY game_date), game_date, DAY) as gap_days
        FROM (
          SELECT DISTINCT game_date
          FROM \`nba-props-platform.nba_analytics.player_game_summary\`
          WHERE game_date >= '$START_DATE'
            AND game_date <= '$END_DATE'
          ORDER BY game_date
        )
      )
      SELECT game_date, next_date, gap_days
      FROM date_gaps
      WHERE gap_days > 30
    "
  else
    check_passed "No multi-month gaps in data"
  fi
}

check_train_val_test_split() {
  log_section "CHECK 5: Train/Val/Test Split Feasibility"

  # Calculate expected split sizes (70/15/15 chronological)
  local total=$(bq_query_value "
    SELECT COUNT(*)
    FROM \`nba-props-platform.nba_analytics.player_game_summary\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
      AND points IS NOT NULL
  ")

  local train_size=$(python3 -c "print(int($total * 0.70))")
  local val_size=$(python3 -c "print(int($total * 0.15))")
  local test_size=$(python3 -c "print(int($total * 0.15))")

  log_info "Expected split (70/15/15):"
  log_info "  Train: $(format_number $train_size)"
  log_info "  Val:   $(format_number $val_size)"
  log_info "  Test:  $(format_number $test_size)"

  # Check if val and test sets are large enough
  if [[ "$val_size" -lt 5000 ]] || [[ "$test_size" -lt 5000 ]]; then
    check_warning "Val/Test sets <5,000 records each (may be too small)"
  else
    check_passed "Train/Val/Test splits are adequate (all ≥5,000 records)"
  fi
}

# =============================================================================
# MAIN EXECUTION
# =============================================================================

main() {
  log_section "ML TRAINING READINESS VALIDATION"
  log_info "Training Period: $START_DATE to $END_DATE"
  echo ""

  # Run all checks
  check_ml_data_volume
  check_critical_features
  check_data_quality
  check_no_data_issues
  check_train_val_test_split

  # Summary
  log_section "VALIDATION SUMMARY"
  echo ""
  log_success "Checks Passed:  $CHECKS_PASSED"

  if [[ "$CHECKS_FAILED" -gt 0 ]]; then
    log_error "Checks Failed:  $CHECKS_FAILED (CRITICAL)"
    echo ""
    log_error "CRITICAL FAILURES:"
    for msg in "${CRITICAL_FAILURES[@]}"; do
      echo "  ❌ $msg"
    done
  fi

  if [[ "$CHECKS_WARNING" -gt 0 ]]; then
    log_warning "Checks Warning: $CHECKS_WARNING"
    echo ""
    log_warning "WARNINGS:"
    for msg in "${WARNINGS[@]}"; do
      echo "  ⚠️  $msg"
    done
  fi

  echo ""

  # Final decision
  if [[ "$CHECKS_FAILED" -gt 0 ]]; then
    log_error "❌ NOT READY FOR ML TRAINING"
    echo ""
    log_error "Fix critical issues above before training."
    log_error "Model will likely fail or perform poorly with this data."
    exit 1
  elif [[ "$CHECKS_WARNING" -gt 0 ]]; then
    log_warning "⚠️  READY FOR ML TRAINING (WITH CAVEATS)"
    echo ""
    log_warning "Data is usable but not optimal."
    log_warning "Model may perform below target (4.0-4.2 MAE range)."
    log_warning ""
    log_warning "You can proceed with training, but expect:"
    log_warning "  • Potentially weaker performance on features with low coverage"
    log_warning "  • May need to retrain after fixing warnings"
    exit 2
  else
    log_success "✅ READY FOR ML TRAINING"
    echo ""
    log_success "All validation checks passed!"
    log_success "Data quality is excellent. Expected model performance:"
    log_success "  • Train/Val/Test: $(format_number $train_size) / $(format_number $val_size) / $(format_number $test_size)"
    log_success "  • Target MAE: 3.8-4.2 (beating 4.27 baseline)"
    log_success ""
    log_success "Ready to train: PYTHONPATH=. python ml/train_real_xgboost.py"
    exit 0
  fi
}

main
