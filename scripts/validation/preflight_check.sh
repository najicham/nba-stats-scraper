#!/bin/bash
#
# PRE-FLIGHT VALIDATION - Run BEFORE Starting Backfill
# =====================================================
#
# Purpose: Catch issues BEFORE wasting hours on full backfill
#
# Usage:
#   ./scripts/validation/preflight_check.sh \
#     --phase [2|3|4] \
#     --start-date YYYY-MM-DD \
#     --end-date YYYY-MM-DD \
#     [--config CONFIG_FILE] \
#     [--strict]
#
# Exit Codes:
#   0 = PASS (safe to proceed)
#   1 = FAIL (do NOT proceed)
#   2 = WARNING (proceed with caution)
#
# What it checks:
#   1. Upstream dependencies complete
#   2. Sample test on 1 historical date
#   3. No duplicates in target table
#   4. Required fields present
#   5. No conflicting processes running
#   6. BigQuery quota available
#   7. Estimated runtime reasonable
#

set -eo pipefail

# Source common utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_validation.sh"

# =============================================================================
# CONFIGURATION
# =============================================================================

PHASE=""
START_DATE=""
END_DATE=""
CONFIG_FILE="$SCRIPT_DIR/../config/backfill_thresholds.yaml"
STRICT_MODE=false
DRY_RUN=false

# Table mappings
declare -A PHASE_TABLES
PHASE_TABLES[2_raw]="nba_raw.bdl_player_boxscores"
PHASE_TABLES[3_team_offense]="nba_analytics.team_offense_game_summary"
PHASE_TABLES[3_player]="nba_analytics.player_game_summary"
PHASE_TABLES[4_pcf]="nba_precompute.player_composite_factors"
PHASE_TABLES[4_tdza]="nba_precompute.team_defense_zone_analysis"
PHASE_TABLES[4_psza]="nba_precompute.player_shot_zone_analysis"

# Upstream dependencies
declare -A UPSTREAM_TABLES
UPSTREAM_TABLES[3_team_offense]="nba_raw.nbac_team_boxscore nba_raw.nbac_gamebook_player_stats"
UPSTREAM_TABLES[3_player]="nba_analytics.team_offense_game_summary nba_raw.nbac_gamebook_player_stats nba_raw.bdl_player_boxscores"
UPSTREAM_TABLES[4_pcf]="nba_analytics.player_game_summary nba_precompute.team_defense_zone_analysis nba_precompute.player_shot_zone_analysis"
UPSTREAM_TABLES[4_tdza]="nba_analytics.team_defense_game_summary"
UPSTREAM_TABLES[4_psza]="nba_analytics.player_game_summary"

# Critical fields that MUST exist
declare -A CRITICAL_FIELDS
CRITICAL_FIELDS[3_player]="minutes_played usage_rate points rebounds assists"
CRITICAL_FIELDS[3_team_offense]="points_scored fg_attempts team_pace"
CRITICAL_FIELDS[4_pcf]="fatigue_factor shot_zone_mismatch pace_differential usage_spike"

# Results tracking
CHECKS_PASSED=0
CHECKS_FAILED=0
CHECKS_WARNING=0
FAILURE_MESSAGES=()
WARNING_MESSAGES=()

# =============================================================================
# COMMAND LINE PARSING
# =============================================================================

while [[ $# -gt 0 ]]; do
  case $1 in
    --phase)
      PHASE="$2"
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
    --strict)
      STRICT_MODE=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# Validate required args
if [[ -z "$PHASE" ]] || [[ -z "$START_DATE" ]] || [[ -z "$END_DATE" ]]; then
  echo "Error: Missing required arguments"
  echo "Usage: $0 --phase [2|3|4] --start-date YYYY-MM-DD --end-date YYYY-MM-DD"
  exit 1
fi

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

get_table_for_phase() {
  local phase="$1"
  case "$phase" in
    2) echo "${PHASE_TABLES[2_raw]}" ;;
    3) echo "${PHASE_TABLES[3_player]}" ;;  # Default to player for Phase 3
    4) echo "${PHASE_TABLES[4_pcf]}" ;;     # Default to PCF for Phase 4
    *) echo "" ;;
  esac
}

get_sample_date() {
  # Pick a date ~30 days after start (not first day, to avoid edge cases)
  local start="$1"
  python3 -c "from datetime import datetime, timedelta; d = datetime.strptime('$start', '%Y-%m-%d') + timedelta(days=30); print(d.strftime('%Y-%m-%d'))"
}

estimate_runtime_hours() {
  local start="$1"
  local end="$2"
  local phase="$3"

  # Calculate days
  local days=$(python3 -c "from datetime import datetime; d1=datetime.strptime('$start','%Y-%m-%d'); d2=datetime.strptime('$end','%Y-%m-%d'); print((d2-d1).days)")

  # Rough estimates (seconds per date)
  case "$phase" in
    2) local secs_per_date=20 ;;
    3) local secs_per_date=30 ;;
    4) local secs_per_date=40 ;;
    *) local secs_per_date=30 ;;
  esac

  # Total hours
  python3 -c "print(round($days * $secs_per_date / 3600.0, 1))"
}

# =============================================================================
# CHECK 1: Validate Upstream Dependencies Complete
# =============================================================================

check_upstream_dependencies() {
  log_section "CHECK 1: Upstream Dependencies"

  local phase_key="${PHASE}_player"  # Default
  case "$PHASE" in
    3)
      if [[ "$TABLE_NAME" == *"team_offense"* ]]; then
        phase_key="3_team_offense"
      else
        phase_key="3_player"
      fi
      ;;
    4)
      if [[ "$TABLE_NAME" == *"team_defense"* ]]; then
        phase_key="4_tdza"
      elif [[ "$TABLE_NAME" == *"shot_zone"* ]]; then
        phase_key="4_psza"
      else
        phase_key="4_pcf"
      fi
      ;;
  esac

  local upstream="${UPSTREAM_TABLES[$phase_key]}"

  if [[ -z "$upstream" ]]; then
    check_passed "No upstream dependencies (Phase 2)"
    return 0
  fi

  log_info "Checking upstream tables: $upstream"

  for upstream_table in $upstream; do
    log_info "  Validating $upstream_table..."

    # Check table exists
    if ! bq show "$upstream_table" &>/dev/null; then
      check_failed "Upstream table does not exist: $upstream_table"
      continue
    fi

    # Check has data for date range
    local count=$(bq_query_value "
      SELECT COUNT(DISTINCT game_date)
      FROM \`$upstream_table\`
      WHERE game_date >= '$START_DATE'
        AND game_date <= '$END_DATE'
    ")

    if [[ "$count" -eq 0 ]]; then
      check_failed "Upstream table has NO data for date range: $upstream_table"
      continue
    fi

    # For critical upstream (team_offense), check completeness
    if [[ "$upstream_table" == "nba_analytics.team_offense_game_summary" ]]; then
      log_info "    Checking team_offense completeness (critical for usage_rate)..."

      # Count expected games from bdl
      local expected_dates=$(bq_query_value "
        SELECT COUNT(DISTINCT game_date)
        FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
        WHERE game_date >= '$START_DATE'
          AND game_date <= '$END_DATE'
      ")

      local actual_dates=$(bq_query_value "
        SELECT COUNT(DISTINCT game_date)
        FROM \`$upstream_table\`
        WHERE game_date >= '$START_DATE'
          AND game_date <= '$END_DATE'
      ")

      local coverage=$(python3 -c "print(round($actual_dates * 100.0 / $expected_dates, 1))")

      if [[ $(echo "$coverage < 95.0" | bc -l) -eq 1 ]]; then
        check_failed "team_offense only ${coverage}% complete (need ≥95%)"
        check_failed "  Expected: $expected_dates dates, Actual: $actual_dates dates"
        check_failed "  This will cause low usage_rate coverage!"
      else
        check_passed "  team_offense ${coverage}% complete (≥95%)"
      fi
    fi

    check_passed "  $upstream_table: $count dates available"
  done
}

# =============================================================================
# CHECK 2: Sample Test on 1 Historical Date
# =============================================================================

check_sample_processing() {
  log_section "CHECK 2: Sample Processing Test"

  local sample_date=$(get_sample_date "$START_DATE")
  log_info "Testing processing on sample date: $sample_date"

  # Determine which processor to run
  local processor_script=""
  case "$PHASE" in
    3)
      if [[ "$TABLE_NAME" == *"team_offense"* ]]; then
        processor_script="backfill_jobs/analytics/team_offense_game_summary/team_offense_game_summary_analytics_backfill.py"
      else
        processor_script="backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py"
      fi
      ;;
    4)
      processor_script="backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py"
      ;;
    *)
      log_warning "Sample test not implemented for Phase $PHASE"
      check_warning "Sample test skipped"
      return 0
      ;;
  esac

  if [[ ! -f "$processor_script" ]]; then
    log_warning "Processor script not found: $processor_script"
    check_warning "Sample test skipped (script not found)"
    return 0
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    log_info "DRY RUN: Would test $sample_date"
    check_passed "Sample test skipped (dry run)"
    return 0
  fi

  # Run sample test
  log_info "Running: PYTHONPATH=. python3 $processor_script --start-date $sample_date --end-date $sample_date"

  local before_count=$(bq_query_value "SELECT COUNT(*) FROM \`$TARGET_TABLE\` WHERE game_date = '$sample_date'")

  if PYTHONPATH=. timeout 600 python3 "$processor_script" \
      --start-date "$sample_date" \
      --end-date "$sample_date" \
      --skip-preflight \
      > /tmp/preflight_sample_test.log 2>&1; then

    local after_count=$(bq_query_value "SELECT COUNT(*) FROM \`$TARGET_TABLE\` WHERE game_date = '$sample_date'")

    if [[ "$after_count" -gt "$before_count" ]]; then
      check_passed "Sample test PASSED: Processed $sample_date successfully ($after_count records)"

      # Validate data quality of sample
      local null_rate=$(bq_query_value "
        SELECT ROUND(COUNTIF(minutes_played IS NULL) * 100.0 / COUNT(*), 1)
        FROM \`$TARGET_TABLE\`
        WHERE game_date = '$sample_date'
          AND points IS NOT NULL
      ")

      if [[ $(echo "$null_rate > 60.0" | bc -l) -eq 1 ]]; then
        check_failed "Sample has ${null_rate}% NULL minutes_played (suspicious!)"
      else
        check_passed "  minutes_played NULL rate: ${null_rate}% (acceptable)"
      fi
    else
      check_failed "Sample test FAILED: No new records written ($before_count before, $after_count after)"
    fi
  else
    check_failed "Sample test FAILED: Processor returned non-zero exit code (see /tmp/preflight_sample_test.log)"
  fi
}

# =============================================================================
# CHECK 3: No Duplicates in Target Table
# =============================================================================

check_no_duplicates() {
  log_section "CHECK 3: Duplicate Detection"

  log_info "Checking for existing duplicates in target table..."

  # Build unique key columns based on table
  local unique_cols="game_id, game_date"
  if [[ "$TARGET_TABLE" == *"player"* ]]; then
    unique_cols="game_id, game_date, player_lookup"
  elif [[ "$TARGET_TABLE" == *"team"* ]]; then
    unique_cols="game_id, game_date, team_abbr"
  fi

  local dup_count=$(bq_query_value "
    WITH duplicates AS (
      SELECT $unique_cols, COUNT(*) as dup_count
      FROM \`$TARGET_TABLE\`
      WHERE game_date >= '$START_DATE'
        AND game_date <= '$END_DATE'
      GROUP BY $unique_cols
      HAVING COUNT(*) > 1
    )
    SELECT COALESCE(SUM(dup_count), 0)
    FROM duplicates
  ")

  if [[ "$dup_count" -gt 0 ]]; then
    check_failed "Found $dup_count duplicate records in target table!"
    check_failed "  Run deduplication before backfill or data will be corrupted"

    # Show sample duplicates
    log_error "Sample duplicates:"
    bq query --use_legacy_sql=false --format=pretty "
      SELECT $unique_cols, COUNT(*) as dup_count
      FROM \`$TARGET_TABLE\`
      WHERE game_date >= '$START_DATE'
        AND game_date <= '$END_DATE'
      GROUP BY $unique_cols
      HAVING COUNT(*) > 1
      ORDER BY dup_count DESC
      LIMIT 5
    "
  else
    check_passed "No duplicates found in target table"
  fi
}

# =============================================================================
# CHECK 4: Required Fields Present
# =============================================================================

check_required_fields() {
  log_section "CHECK 4: Required Fields"

  local phase_key="${PHASE}_player"
  case "$PHASE" in
    3)
      if [[ "$TARGET_TABLE" == *"team_offense"* ]]; then
        phase_key="3_team_offense"
      else
        phase_key="3_player"
      fi
      ;;
    4)
      phase_key="4_pcf"
      ;;
  esac

  local required_fields="${CRITICAL_FIELDS[$phase_key]}"

  if [[ -z "$required_fields" ]]; then
    log_info "No critical fields defined for this phase"
    check_passed "Required fields check skipped"
    return 0
  fi

  log_info "Checking for required fields: $required_fields"

  # Get actual schema
  local schema=$(bq show --schema --format=prettyjson "$TARGET_TABLE" 2>/dev/null)

  if [[ -z "$schema" ]]; then
    check_warning "Could not retrieve schema (table may not exist yet)"
    return 0
  fi

  for field in $required_fields; do
    if echo "$schema" | grep -q "\"name\": \"$field\""; then
      check_passed "  Field exists: $field"
    else
      check_failed "  Field MISSING: $field"
    fi
  done
}

# =============================================================================
# CHECK 5: No Conflicting Processes
# =============================================================================

check_no_conflicts() {
  log_section "CHECK 5: Process Conflicts"

  log_info "Checking for running backfill processes..."

  # Check for Python backfill processes
  local running_procs=$(ps aux | grep -E "python.*backfill.*${TABLE_NAME}" | grep -v grep | wc -l)

  if [[ "$running_procs" -gt 0 ]]; then
    check_warning "Found $running_procs running backfill process(es) for this table"
    check_warning "  This may cause conflicts or duplicate processing"
    ps aux | grep -E "python.*backfill.*${TABLE_NAME}" | grep -v grep
  else
    check_passed "No conflicting processes found"
  fi

  # Check for checkpoint files
  local checkpoint_files=$(find /tmp/backfill_checkpoints/ -name "*${TABLE_NAME##*.}*" -mmin -60 2>/dev/null | wc -l)

  if [[ "$checkpoint_files" -gt 0 ]]; then
    check_warning "Found recent checkpoint files (modified in last hour)"
    check_warning "  Another backfill may have run recently"
    find /tmp/backfill_checkpoints/ -name "*${TABLE_NAME##*.}*" -mmin -60 2>/dev/null
  else
    check_passed "No recent checkpoint files found"
  fi
}

# =============================================================================
# CHECK 6: BigQuery Quota Available
# =============================================================================

check_bigquery_quota() {
  log_section "CHECK 6: BigQuery Quota"

  log_info "Checking BigQuery quota availability..."

  # This is a simple check - a real implementation would use Cloud Monitoring API
  # For now, just verify we can run a query

  if bq query --use_legacy_sql=false --format=csv "SELECT 1" > /dev/null 2>&1; then
    check_passed "BigQuery API accessible"
  else
    check_failed "BigQuery API not accessible (quota exhausted or permissions issue?)"
  fi
}

# =============================================================================
# CHECK 7: Estimated Runtime Reasonable
# =============================================================================

check_estimated_runtime() {
  log_section "CHECK 7: Estimated Runtime"

  local estimated_hours=$(estimate_runtime_hours "$START_DATE" "$END_DATE" "$PHASE")

  log_info "Estimated runtime: ${estimated_hours} hours"

  if [[ $(echo "$estimated_hours > 24.0" | bc -l) -eq 1 ]]; then
    check_warning "Estimated runtime >24 hours - consider breaking into smaller ranges"
  elif [[ $(echo "$estimated_hours > 12.0" | bc -l) -eq 1 ]]; then
    check_warning "Estimated runtime >12 hours - monitor progress regularly"
  else
    check_passed "Estimated runtime reasonable (<12 hours)"
  fi

  # Calculate dates
  local days=$(python3 -c "from datetime import datetime; d1=datetime.strptime('$START_DATE','%Y-%m-%d'); d2=datetime.strptime('$END_DATE','%Y-%m-%d'); print((d2-d1).days)")
  log_info "Date range: $days days"

  if [[ "$days" -gt 900 ]]; then
    check_warning "Processing $days days - consider using --parallel flag if available"
  fi
}

# =============================================================================
# MAIN EXECUTION
# =============================================================================

main() {
  log_section "PRE-FLIGHT VALIDATION"
  log_info "Phase: $PHASE"
  log_info "Date Range: $START_DATE to $END_DATE"
  log_info "Config: $CONFIG_FILE"
  log_info "Strict Mode: $STRICT_MODE"
  echo ""

  # Determine target table
  TARGET_TABLE=$(get_table_for_phase "$PHASE")
  TABLE_NAME=$(basename "$TARGET_TABLE")

  if [[ -z "$TARGET_TABLE" ]]; then
    log_error "Invalid phase: $PHASE"
    exit 1
  fi

  log_info "Target Table: $TARGET_TABLE"
  echo ""

  # Run all checks
  check_upstream_dependencies
  check_sample_processing
  check_no_duplicates
  check_required_fields
  check_no_conflicts
  check_bigquery_quota
  check_estimated_runtime

  # Print summary
  log_section "PRE-FLIGHT SUMMARY"
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
    log_error "❌ PRE-FLIGHT FAILED - DO NOT PROCEED WITH BACKFILL"
    echo ""
    log_error "Fix the issues above before running backfill."
    exit 1
  elif [[ "$CHECKS_WARNING" -gt 0 ]] && [[ "$STRICT_MODE" == "true" ]]; then
    log_warning "⚠️  PRE-FLIGHT WARNINGS IN STRICT MODE - ABORTING"
    echo ""
    log_warning "Fix warnings or run without --strict to proceed."
    exit 2
  elif [[ "$CHECKS_WARNING" -gt 0 ]]; then
    log_warning "⚠️  PRE-FLIGHT PASSED WITH WARNINGS"
    echo ""
    log_warning "Review warnings above. Proceed with caution."
    exit 0
  else
    log_success "✅ PRE-FLIGHT PASSED - SAFE TO PROCEED"
    echo ""
    log_success "All checks passed. Ready to start backfill."
    exit 0
  fi
}

main
