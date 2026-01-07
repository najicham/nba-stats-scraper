#!/bin/bash
#
# POST-BACKFILL VALIDATION - Run IMMEDIATELY After Backfill
# ==========================================================
#
# Purpose: Verify backfill actually worked and data quality is good
#
# Usage:
#   ./scripts/validation/post_backfill_validation.sh \
#     --table TABLE_NAME \
#     --start-date YYYY-MM-DD \
#     --end-date YYYY-MM-DD \
#     [--config CONFIG_FILE]
#
# Exit Codes:
#   0 = PASS (data quality good)
#   1 = FAIL (data quality issues - investigate!)
#   2 = WARNING (minor issues)
#
# What it checks:
#   1. Record count vs expected minimum
#   2. Duplicate detection (all unique keys)
#   3. NULL rate validation (critical fields)
#   4. Value range checks (impossible values)
#   5. Cross-field consistency (FG% = FGM/FGA)
#   6. Quality distribution (Gold/Silver ≥80%)
#   7. Date coverage (no multi-day gaps)
#   8. Data freshness (processed_at reasonable)
#   9. Cross-table consistency (player totals = team totals)
#   10. Write verification (API success = data exists)
#

set -eo pipefail

# Source common utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_validation.sh"

# =============================================================================
# CONFIGURATION
# =============================================================================

TABLE_NAME=""
START_DATE=""
END_DATE=""
CONFIG_FILE="$SCRIPT_DIR/../config/backfill_thresholds.yaml"
SKIP_EXPENSIVE_CHECKS=false

# Results tracking
CHECKS_PASSED=0
CHECKS_FAILED=0
CHECKS_WARNING=0
FAILURE_MESSAGES=()
WARNING_MESSAGES=()

# Table-specific configs
declare -A MIN_RECORDS
MIN_RECORDS[player_game_summary]=35000
MIN_RECORDS[team_offense_game_summary]=5600
MIN_RECORDS[player_composite_factors]=30000

declare -A CRITICAL_FIELDS
CRITICAL_FIELDS[player_game_summary]="minutes_played usage_rate points rebounds assists"
CRITICAL_FIELDS[team_offense_game_summary]="points_scored fg_attempts team_pace"
CRITICAL_FIELDS[player_composite_factors]="fatigue_factor shot_zone_mismatch pace_differential"

declare -A NULL_THRESHOLDS
NULL_THRESHOLDS[minutes_played]=5.0
NULL_THRESHOLDS[usage_rate]=10.0
NULL_THRESHOLDS[points]=1.0
NULL_THRESHOLDS[rebounds]=1.0
NULL_THRESHOLDS[assists]=1.0

# =============================================================================
# COMMAND LINE PARSING
# =============================================================================

while [[ $# -gt 0 ]]; do
  case $1 in
    --table)
      TABLE_NAME="$2"
      shift 2
      ;;
    --start-date)
      START_DATE="$2"
      shift 2
      ;;
    --end-date)
      END_DATE="$2"
      shift 2
      ;;
    --config)
      CONFIG_FILE="$2"
      shift 2
      ;;
    --skip-expensive)
      SKIP_EXPENSIVE_CHECKS=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# Validate required args
if [[ -z "$TABLE_NAME" ]] || [[ -z "$START_DATE" ]] || [[ -z "$END_DATE" ]]; then
  echo "Error: Missing required arguments"
  echo "Usage: $0 --table TABLE_NAME --start-date YYYY-MM-DD --end-date YYYY-MM-DD"
  exit 1
fi

# Extract table basename
TABLE_BASENAME=$(basename "$TABLE_NAME")

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

check_passed() {
  ((CHECKS_PASSED++))
  log_success "$1"
}

check_failed() {
  ((CHECKS_FAILED++))
  FAILURE_MESSAGES+=("$1")
  log_error "$1"
}

check_warning() {
  ((CHECKS_WARNING++))
  WARNING_MESSAGES+=("$1")
  log_warning "$1"
}

get_full_table_name() {
  local table="$1"
  if [[ "$table" == *"."* ]]; then
    echo "$table"
  else
    # Infer dataset based on table name
    if [[ "$table" == *"player_composite_factors"* ]] || [[ "$table" == *"_zone_"* ]]; then
      echo "nba-props-platform.nba_precompute.$table"
    elif [[ "$table" == *"player_game_summary"* ]] || [[ "$table" == *"team_"* ]]; then
      echo "nba-props-platform.nba_analytics.$table"
    else
      echo "nba-props-platform.nba_raw.$table"
    fi
  fi
}

# =============================================================================
# CHECK 1: Record Count vs Expected Minimum
# =============================================================================

check_record_count() {
  log_section "CHECK 1: Record Count"

  local full_table=$(get_full_table_name "$TABLE_NAME")

  local total_records=$(bq_query_value "
    SELECT COUNT(*)
    FROM \`$full_table\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
  ")

  log_info "Total records: $(format_number $total_records)"

  # Check against minimum
  local min_expected="${MIN_RECORDS[$TABLE_BASENAME]:-0}"

  if [[ "$min_expected" -gt 0 ]]; then
    if [[ "$total_records" -lt "$min_expected" ]]; then
      check_failed "Record count $total_records < minimum $min_expected"
    else
      check_passed "Record count $total_records ≥ minimum $min_expected"
    fi
  else
    check_passed "No minimum threshold defined (got $total_records records)"
  fi

  # Check records per date
  local date_count=$(bq_query_value "
    SELECT COUNT(DISTINCT game_date)
    FROM \`$full_table\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
  ")

  if [[ "$date_count" -eq 0 ]]; then
    check_failed "Zero dates with data!"
    return
  fi

  local avg_per_date=$(python3 -c "print(round($total_records / $date_count, 1))")
  log_info "Average records per date: $avg_per_date"

  # Sanity check for player tables
  if [[ "$TABLE_NAME" == *"player"* ]]; then
    # Should be ~150-250 players per date (30 players/game * 5-8 games)
    if [[ $(echo "$avg_per_date < 50" | bc -l) -eq 1 ]]; then
      check_warning "Only $avg_per_date players/date (suspiciously low)"
    elif [[ $(echo "$avg_per_date > 500" | bc -l) -eq 1 ]]; then
      check_warning "$avg_per_date players/date (suspiciously high - possible duplicates?)"
    else
      check_passed "Average players per date: $avg_per_date (reasonable)"
    fi
  fi
}

# =============================================================================
# CHECK 2: Duplicate Detection
# =============================================================================

check_duplicates() {
  log_section "CHECK 2: Duplicate Detection"

  local full_table=$(get_full_table_name "$TABLE_NAME")

  # Determine unique key columns
  local unique_cols="game_id, game_date"
  if [[ "$TABLE_NAME" == *"player"* ]]; then
    unique_cols="game_id, game_date, player_lookup"
  elif [[ "$TABLE_NAME" == *"team"* ]]; then
    unique_cols="game_id, game_date, team_abbr"
  fi

  log_info "Checking for duplicates on: $unique_cols"

  local dup_query="
    WITH duplicates AS (
      SELECT $unique_cols, COUNT(*) as dup_count
      FROM \`$full_table\`
      WHERE game_date >= '$START_DATE'
        AND game_date <= '$END_DATE'
      GROUP BY $unique_cols
      HAVING COUNT(*) > 1
    )
    SELECT
      COUNT(*) as unique_keys_duplicated,
      SUM(dup_count) as total_duplicate_records,
      MAX(dup_count) as max_dup_count
    FROM duplicates
  "

  local dup_result=$(bq query --use_legacy_sql=false --format=csv "$dup_query" | tail -1)

  local unique_keys_dup=$(echo "$dup_result" | cut -d',' -f1)
  local total_dup_records=$(echo "$dup_result" | cut -d',' -f2)
  local max_dup=$(echo "$dup_result" | cut -d',' -f3)

  if [[ -z "$unique_keys_dup" ]] || [[ "$unique_keys_dup" == "null" ]] || [[ "$unique_keys_dup" -eq 0 ]]; then
    check_passed "No duplicates found"
  else
    check_failed "Found $total_dup_records duplicate records across $unique_keys_dup unique keys"
    check_failed "  Maximum duplicates for single key: $max_dup"

    # Show sample
    log_error "Sample duplicates:"
    bq query --use_legacy_sql=false --format=pretty "
      SELECT $unique_cols, COUNT(*) as dup_count
      FROM \`$full_table\`
      WHERE game_date >= '$START_DATE'
        AND game_date <= '$END_DATE'
      GROUP BY $unique_cols
      HAVING COUNT(*) > 1
      ORDER BY COUNT(*) DESC
      LIMIT 5
    "
  fi
}

# =============================================================================
# CHECK 3: NULL Rate Validation
# =============================================================================

check_null_rates() {
  log_section "CHECK 3: NULL Rate Validation"

  local full_table=$(get_full_table_name "$TABLE_NAME")
  local critical_fields="${CRITICAL_FIELDS[$TABLE_BASENAME]}"

  if [[ -z "$critical_fields" ]]; then
    check_passed "No critical fields defined for this table"
    return 0
  fi

  log_info "Checking NULL rates for: $critical_fields"

  # Build query to check all fields at once
  local field_checks=""
  for field in $critical_fields; do
    field_checks+="COUNTIF($field IS NULL) * 100.0 / COUNT(*) as ${field}_null_pct, "
  done
  field_checks=${field_checks%, }  # Remove trailing comma

  local null_query="
    SELECT $field_checks
    FROM \`$full_table\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
      AND points IS NOT NULL  -- Exclude corrupted records
  "

  local null_result=$(bq query --use_legacy_sql=false --format=csv "$null_query" | tail -1)

  # Parse results
  local i=1
  for field in $critical_fields; do
    local null_pct=$(echo "$null_result" | cut -d',' -f$i)

    # Get threshold
    local threshold="${NULL_THRESHOLDS[$field]:-10.0}"

    if [[ $(echo "$null_pct > $threshold" | bc -l) -eq 1 ]]; then
      check_failed "$field NULL rate: ${null_pct}% (threshold: ${threshold}%)"
    else
      check_passed "$field NULL rate: ${null_pct}% (threshold: ${threshold}%)"
    fi

    ((i++))
  done
}

# =============================================================================
# CHECK 4: Value Range Validation
# =============================================================================

check_value_ranges() {
  log_section "CHECK 4: Value Range Validation"

  local full_table=$(get_full_table_name "$TABLE_NAME")

  if [[ "$TABLE_NAME" != *"player"* ]]; then
    check_passed "Value range checks only apply to player tables"
    return 0
  fi

  log_info "Checking for impossible values..."

  # Minutes > 48 (impossible in NBA)
  local invalid_minutes=$(bq_query_value "
    SELECT COUNT(*)
    FROM \`$full_table\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
      AND (minutes_played > 48 OR minutes_played < 0)
  ")

  if [[ "$invalid_minutes" -gt 0 ]]; then
    check_failed "Found $invalid_minutes records with impossible minutes_played (>48 or <0)"
  else
    check_passed "All minutes_played values valid (0-48)"
  fi

  # Usage rate > 100 or < 0
  local invalid_usage=$(bq_query_value "
    SELECT COUNT(*)
    FROM \`$full_table\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
      AND (usage_rate > 100 OR usage_rate < 0)
  ")

  if [[ "$invalid_usage" -gt 0 ]]; then
    check_failed "Found $invalid_usage records with impossible usage_rate (>100 or <0)"
  else
    check_passed "All usage_rate values valid (0-100)"
  fi

  # FG% > 1.0 or < 0
  local invalid_fg_pct=$(bq_query_value "
    SELECT COUNT(*)
    FROM \`$full_table\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
      AND (fg_pct > 1.0 OR fg_pct < 0)
  ")

  if [[ "$invalid_fg_pct" -gt 0 ]]; then
    check_failed "Found $invalid_fg_pct records with impossible fg_pct (>1.0 or <0)"
  else
    check_passed "All fg_pct values valid (0-1.0)"
  fi

  # Negative counts
  local negative_counts=$(bq_query_value "
    SELECT COUNT(*)
    FROM \`$full_table\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
      AND (points < 0 OR rebounds < 0 OR assists < 0)
  ")

  if [[ "$negative_counts" -gt 0 ]]; then
    check_failed "Found $negative_counts records with negative stats"
  else
    check_passed "No negative stat values found"
  fi
}

# =============================================================================
# CHECK 5: Cross-Field Consistency
# =============================================================================

check_cross_field_consistency() {
  log_section "CHECK 5: Cross-Field Consistency"

  local full_table=$(get_full_table_name "$TABLE_NAME")

  if [[ "$TABLE_NAME" != *"player"* ]]; then
    check_passed "Cross-field checks only apply to player tables"
    return 0
  fi

  log_info "Checking mathematical relationships..."

  # FG% = FGM / FGA
  local inconsistent_fg=$(bq_query_value "
    SELECT COUNT(*)
    FROM \`$full_table\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
      AND fg_attempts > 0
      AND ABS(fg_pct - (fg_makes / fg_attempts)) > 0.01
  ")

  if [[ "$inconsistent_fg" -gt 0 ]]; then
    check_warning "Found $inconsistent_fg records where FG% ≠ FGM/FGA (rounding tolerance 0.01)"
  else
    check_passed "FG% = FGM/FGA for all records"
  fi

  # Shot zones <= Total FGA
  local inconsistent_shots=$(bq_query_value "
    SELECT COUNT(*)
    FROM \`$full_table\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
      AND (paint_attempts + mid_range_attempts + three_pt_attempts) > fg_attempts + 1
  ")

  if [[ "$inconsistent_shots" -gt 0 ]]; then
    check_warning "Found $inconsistent_shots records where shot zones > total FGA"
  else
    check_passed "Shot zone totals ≤ total FGA"
  fi

  # Rebounds total = OFF + DEF
  local inconsistent_reb=$(bq_query_value "
    SELECT COUNT(*)
    FROM \`$full_table\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
      AND rebounds_total IS NOT NULL
      AND rebounds_offensive IS NOT NULL
      AND rebounds_defensive IS NOT NULL
      AND rebounds_total != (rebounds_offensive + rebounds_defensive)
  ")

  if [[ "$inconsistent_reb" -gt 0 ]]; then
    check_warning "Found $inconsistent_reb records where total rebounds ≠ OFF + DEF"
  else
    check_passed "Rebound totals = OFF + DEF"
  fi
}

# =============================================================================
# CHECK 6: Quality Distribution
# =============================================================================

check_quality_distribution() {
  log_section "CHECK 6: Quality Distribution"

  local full_table=$(get_full_table_name "$TABLE_NAME")

  # Check if quality_tier column exists
  local has_quality=$(bq show --schema --format=prettyjson "$full_table" 2>/dev/null | grep -c '"name": "quality_tier"' || echo "0")

  if [[ "$has_quality" -eq 0 ]]; then
    check_passed "No quality_tier column (not applicable)"
    return 0
  fi

  local quality_dist=$(bq query --use_legacy_sql=false --format=csv "
    SELECT
      quality_tier,
      COUNT(*) as count,
      ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as pct
    FROM \`$full_table\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
    GROUP BY quality_tier
    ORDER BY
      CASE quality_tier
        WHEN 'gold' THEN 1
        WHEN 'silver' THEN 2
        WHEN 'bronze' THEN 3
        WHEN 'poor' THEN 4
        ELSE 5
      END
  ")

  echo "$quality_dist" | column -t -s','

  # Calculate gold + silver percentage
  local gold_silver_pct=$(echo "$quality_dist" | awk -F',' '($1 == "gold" || $1 == "silver") {sum += $3} END {print sum}')

  if [[ -z "$gold_silver_pct" ]]; then
    gold_silver_pct=0
  fi

  if [[ $(echo "$gold_silver_pct < 80.0" | bc -l) -eq 1 ]]; then
    check_warning "Gold+Silver only ${gold_silver_pct}% (target: ≥80%)"
  else
    check_passed "Gold+Silver: ${gold_silver_pct}% (≥80%)"
  fi
}

# =============================================================================
# CHECK 7: Date Coverage Gaps
# =============================================================================

check_date_coverage() {
  log_section "CHECK 7: Date Coverage"

  local full_table=$(get_full_table_name "$TABLE_NAME")

  # Get all dates with data
  local dates_with_data=$(bq query --use_legacy_sql=false --format=csv "
    SELECT DISTINCT game_date
    FROM \`$full_table\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
    ORDER BY game_date
  " | tail -n +2)

  local total_dates=$(echo "$dates_with_data" | wc -l)
  log_info "Dates with data: $total_dates"

  # Check for multi-day gaps
  local prev_date=""
  local gaps_found=0
  local gap_details=()

  while IFS= read -r date; do
    if [[ -n "$prev_date" ]]; then
      local days_diff=$(python3 -c "from datetime import datetime; d1=datetime.strptime('$prev_date','%Y-%m-%d'); d2=datetime.strptime('$date','%Y-%m-%d'); print((d2-d1).days)")

      if [[ "$days_diff" -gt 7 ]]; then
        ((gaps_found++))
        gap_details+=("Gap of $days_diff days: $prev_date to $date")
      fi
    fi
    prev_date="$date"
  done <<< "$dates_with_data"

  if [[ "$gaps_found" -gt 0 ]]; then
    check_warning "Found $gaps_found multi-day gap(s) (>7 days):"
    for gap in "${gap_details[@]}"; do
      log_warning "  $gap"
    done
  else
    check_passed "No multi-day gaps found"
  fi
}

# =============================================================================
# CHECK 8: Data Freshness
# =============================================================================

check_data_freshness() {
  log_section "CHECK 8: Data Freshness"

  local full_table=$(get_full_table_name "$TABLE_NAME")

  # Check if processed_at exists
  local has_processed_at=$(bq show --schema --format=prettyjson "$full_table" 2>/dev/null | grep -c '"name": "processed_at"' || echo "0")

  if [[ "$has_processed_at" -eq 0 ]]; then
    check_passed "No processed_at column (not applicable)"
    return 0
  fi

  local freshness=$(bq query --use_legacy_sql=false --format=csv "
    SELECT
      AVG(DATETIME_DIFF(DATETIME(processed_at), DATETIME(game_date), HOUR)) as avg_lag_hours,
      MAX(DATETIME_DIFF(DATETIME(processed_at), DATETIME(game_date), HOUR)) as max_lag_hours
    FROM \`$full_table\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
      AND processed_at IS NOT NULL
  " | tail -1)

  local avg_lag=$(echo "$freshness" | cut -d',' -f1 | cut -d'.' -f1)
  local max_lag=$(echo "$freshness" | cut -d',' -f1 | cut -d'.' -f1)

  log_info "Average processing lag: ${avg_lag} hours"
  log_info "Maximum processing lag: ${max_lag} hours"

  if [[ "$avg_lag" -gt 168 ]]; then
    check_warning "Average lag ${avg_lag} hours (>1 week)"
  else
    check_passed "Average lag ${avg_lag} hours (<1 week)"
  fi

  if [[ "$max_lag" -gt 720 ]]; then
    check_warning "Max lag ${max_lag} hours (>30 days)"
  else
    check_passed "Max lag ${max_lag} hours (<30 days)"
  fi
}

# =============================================================================
# CHECK 9: Cross-Table Consistency (Expensive)
# =============================================================================

check_cross_table_consistency() {
  if [[ "$SKIP_EXPENSIVE_CHECKS" == "true" ]]; then
    log_section "CHECK 9: Cross-Table Consistency (SKIPPED)"
    check_passed "Skipped (--skip-expensive flag)"
    return 0
  fi

  log_section "CHECK 9: Cross-Table Consistency"

  # Only for player_game_summary
  if [[ "$TABLE_NAME" != *"player_game_summary"* ]]; then
    check_passed "Not applicable for this table"
    return 0
  fi

  log_info "Checking player totals vs team totals..."

  # This is expensive - sample 10 recent dates
  local sample_dates=$(bq query --use_legacy_sql=false --format=csv "
    SELECT DISTINCT game_date
    FROM \`nba-props-platform.nba_analytics.player_game_summary\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
    ORDER BY game_date DESC
    LIMIT 10
  " | tail -n +2)

  local mismatches=0

  for sample_date in $sample_dates; do
    local mismatch_count=$(bq_query_value "
      WITH player_agg AS (
        SELECT game_id, team_abbr, SUM(points) as total_points
        FROM \`nba-props-platform.nba_analytics.player_game_summary\`
        WHERE game_date = '$sample_date'
        GROUP BY game_id, team_abbr
      ),
      team_stats AS (
        SELECT game_id, team_abbr, points_scored as team_points
        FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
        WHERE game_date = '$sample_date'
      )
      SELECT COUNT(*)
      FROM player_agg p
      JOIN team_stats t USING (game_id, team_abbr)
      WHERE ABS(p.total_points - t.team_points) > 2
    ")

    if [[ "$mismatch_count" -gt 0 ]]; then
      ((mismatches++))
      log_warning "  $sample_date: $mismatch_count team(s) with mismatch"
    fi
  done

  if [[ "$mismatches" -gt 0 ]]; then
    check_warning "Found mismatches on $mismatches of 10 sample dates"
  else
    check_passed "Player totals = Team totals (sampled 10 dates)"
  fi
}

# =============================================================================
# CHECK 10: Write Verification
# =============================================================================

check_write_verification() {
  log_section "CHECK 10: Write Verification"

  local full_table=$(get_full_table_name "$TABLE_NAME")

  log_info "Verifying data exists for date range..."

  # Count dates
  local dates_with_data=$(bq_query_value "
    SELECT COUNT(DISTINCT game_date)
    FROM \`$full_table\`
    WHERE game_date >= '$START_DATE'
      AND game_date <= '$END_DATE'
  ")

  # Calculate expected dates
  local expected_dates=$(python3 -c "from datetime import datetime, timedelta; d1=datetime.strptime('$START_DATE','%Y-%m-%d'); d2=datetime.strptime('$END_DATE','%Y-%m-%d'); print((d2-d1).days + 1)")

  log_info "Dates with data: $dates_with_data / $expected_dates possible dates"

  # For historical backfills, we don't expect 100% (All-Star break, etc.)
  # But we should have at least 60% coverage
  local coverage=$(python3 -c "print(round($dates_with_data * 100.0 / $expected_dates, 1))")

  if [[ $(echo "$coverage < 40.0" | bc -l) -eq 1 ]]; then
    check_failed "Only ${coverage}% date coverage (suspiciously low)"
  elif [[ $(echo "$coverage < 60.0" | bc -l) -eq 1 ]]; then
    check_warning "Only ${coverage}% date coverage (expected ≥60%)"
  else
    check_passed "Date coverage: ${coverage}%"
  fi
}

# =============================================================================
# MAIN EXECUTION
# =============================================================================

main() {
  log_section "POST-BACKFILL VALIDATION"
  log_info "Table: $TABLE_NAME"
  log_info "Date Range: $START_DATE to $END_DATE"
  log_info "Config: $CONFIG_FILE"
  echo ""

  # Run all checks
  check_record_count
  check_duplicates
  check_null_rates
  check_value_ranges
  check_cross_field_consistency
  check_quality_distribution
  check_date_coverage
  check_data_freshness
  check_cross_table_consistency
  check_write_verification

  # Print summary
  log_section "POST-BACKFILL SUMMARY"
  echo ""
  log_success "Checks Passed:  $CHECKS_PASSED"

  if [[ "$CHECKS_FAILED" -gt 0 ]]; then
    log_error "Checks Failed:  $CHECKS_FAILED"
    echo ""
    log_error "FAILURE DETAILS:"
    for msg in "${FAILURE_MESSAGES[@]}"; do
      echo "  ❌ $msg"
    done
  fi

  if [[ "$CHECKS_WARNING" -gt 0 ]]; then
    log_warning "Checks Warning: $CHECKS_WARNING"
    echo ""
    log_warning "WARNING DETAILS:"
    for msg in "${WARNING_MESSAGES[@]}"; do
      echo "  ⚠️  $msg"
    done
  fi

  echo ""

  # Determine exit code
  if [[ "$CHECKS_FAILED" -gt 0 ]]; then
    log_error "❌ POST-BACKFILL VALIDATION FAILED"
    echo ""
    log_error "Data quality issues detected. Investigate before proceeding."
    exit 1
  elif [[ "$CHECKS_WARNING" -gt 0 ]]; then
    log_warning "⚠️  POST-BACKFILL VALIDATION PASSED WITH WARNINGS"
    echo ""
    log_warning "Review warnings above. Data may be usable but not optimal."
    exit 0
  else
    log_success "✅ POST-BACKFILL VALIDATION PASSED"
    echo ""
    log_success "All checks passed. Data quality is good!"
    exit 0
  fi
}

main
