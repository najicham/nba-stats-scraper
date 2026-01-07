#!/bin/bash
#
# WRITE VERIFICATION - Verify API Success = Data Actually Written
# ================================================================
#
# Purpose: Catch "silent failures" where processor returns HTTP 200 but no data written
#
# Usage:
#   ./scripts/validation/validate_write_succeeded.sh \
#     --table TABLE_NAME \
#     --date YYYY-MM-DD \
#     --expected-min RECORDS \
#     [--timeout SECONDS]
#
# Exit Codes:
#   0 = PASS (data written successfully)
#   1 = FAIL (no data or insufficient data)
#
# What it checks:
#   1. Data exists for the date
#   2. Record count >= expected minimum
#   3. Records have recent processed_at timestamps
#   4. No partial writes (team A present but team B missing)
#

set -eo pipefail

# Source common utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_validation.sh"

# =============================================================================
# CONFIGURATION
# =============================================================================

TABLE_NAME=""
DATE=""
EXPECTED_MIN=0
TIMEOUT_SECONDS=300
MAX_RETRIES=3
RETRY_DELAY=30

# =============================================================================
# COMMAND LINE PARSING
# =============================================================================

while [[ $# -gt 0 ]]; do
  case $1 in
    --table)
      TABLE_NAME="$2"
      shift 2
      ;;
    --date)
      DATE="$2"
      shift 2
      ;;
    --expected-min)
      EXPECTED_MIN="$2"
      shift 2
      ;;
    --timeout)
      TIMEOUT_SECONDS="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# Validate required args
if [[ -z "$TABLE_NAME" ]] || [[ -z "$DATE" ]] || [[ "$EXPECTED_MIN" -eq 0 ]]; then
  echo "Error: Missing required arguments"
  echo "Usage: $0 --table TABLE_NAME --date YYYY-MM-DD --expected-min RECORDS"
  exit 1
fi

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

get_full_table_name() {
  local table="$1"
  if [[ "$table" == *"."* ]]; then
    echo "$table"
  else
    # Infer dataset
    if [[ "$table" == *"player_composite_factors"* ]] || [[ "$table" == *"_zone_"* ]]; then
      echo "nba-props-platform.nba_precompute.$table"
    elif [[ "$table" == *"player_game_summary"* ]] || [[ "$table" == *"team_"* ]]; then
      echo "nba-props-platform.nba_analytics.$table"
    else
      echo "nba-props-platform.nba_raw.$table"
    fi
  fi
}

wait_for_data() {
  local table="$1"
  local date="$2"
  local min_records="$3"
  local timeout="$4"

  local start_time=$(date +%s)
  local elapsed=0

  log_info "Waiting up to ${timeout}s for data to appear..."

  while [[ "$elapsed" -lt "$timeout" ]]; do
    local actual=$(bq_query_value "
      SELECT COUNT(*)
      FROM \`$table\`
      WHERE game_date = '$date'
    " 2>/dev/null || echo "0")

    if [[ "$actual" -ge "$min_records" ]]; then
      log_success "Data appeared after ${elapsed}s: $actual records"
      return 0
    fi

    sleep 10
    elapsed=$(( $(date +%s) - start_time ))
    log_info "  Still waiting... (${elapsed}s elapsed, $actual records so far)"
  done

  log_error "Timeout after ${elapsed}s - only $actual records (expected ≥$min_records)"
  return 1
}

# =============================================================================
# MAIN VALIDATION LOGIC
# =============================================================================

main() {
  log_section "WRITE VERIFICATION"
  log_info "Table: $TABLE_NAME"
  log_info "Date: $DATE"
  log_info "Expected minimum: $EXPECTED_MIN records"
  echo ""

  local full_table=$(get_full_table_name "$TABLE_NAME")
  log_info "Full table name: $full_table"
  echo ""

  # ==========================================================================
  # CHECK 1: Data Exists
  # ==========================================================================

  log_section "CHECK 1: Data Exists"

  local actual_count=$(bq_query_value "
    SELECT COUNT(*)
    FROM \`$full_table\`
    WHERE game_date = '$DATE'
  " 2>/dev/null || echo "0")

  log_info "Actual records: $(format_number $actual_count)"

  if [[ "$actual_count" -eq 0 ]]; then
    log_warning "No data found - will wait and retry"

    # Wait for data to appear (sometimes BigQuery has delay)
    if wait_for_data "$full_table" "$DATE" "$EXPECTED_MIN" "$TIMEOUT_SECONDS"; then
      actual_count=$(bq_query_value "
        SELECT COUNT(*)
        FROM \`$full_table\`
        WHERE game_date = '$DATE'
      ")
      log_success "Data found after waiting: $(format_number $actual_count) records"
    else
      log_error "❌ VERIFICATION FAILED: No data written for $DATE"
      exit 1
    fi
  else
    log_success "Data exists: $(format_number $actual_count) records"
  fi

  # ==========================================================================
  # CHECK 2: Record Count >= Expected Minimum
  # ==========================================================================

  log_section "CHECK 2: Record Count Validation"

  if [[ "$actual_count" -lt "$EXPECTED_MIN" ]]; then
    log_error "Record count $actual_count < expected minimum $EXPECTED_MIN"
    log_error "Possible partial write - data incomplete!"

    # Show what we got
    log_info "Sample of data written:"
    bq query --use_legacy_sql=false --format=pretty "
      SELECT *
      FROM \`$full_table\`
      WHERE game_date = '$DATE'
      LIMIT 10
    "

    log_error "❌ VERIFICATION FAILED: Insufficient data"
    exit 1
  else
    log_success "Record count $actual_count ≥ minimum $EXPECTED_MIN"
  fi

  # ==========================================================================
  # CHECK 3: Recent Processed Timestamps
  # ==========================================================================

  log_section "CHECK 3: Processing Timestamps"

  # Check if processed_at exists
  local has_processed_at=$(bq show --schema --format=prettyjson "$full_table" 2>/dev/null | grep -c '"name": "processed_at"' || echo "0")

  if [[ "$has_processed_at" -eq 0 ]]; then
    log_info "No processed_at column - skipping timestamp check"
  else
    # Check how recent the processing was
    local processing_age=$(bq_query_value "
      SELECT DATETIME_DIFF(CURRENT_DATETIME(), MAX(DATETIME(processed_at)), MINUTE)
      FROM \`$full_table\`
      WHERE game_date = '$DATE'
    ")

    log_info "Data processed ${processing_age} minutes ago"

    if [[ "$processing_age" -gt 1440 ]]; then
      log_warning "Data was processed >24 hours ago (may be stale)"
    elif [[ "$processing_age" -gt 60 ]]; then
      log_info "Data processed ${processing_age} minutes ago (within 24 hours)"
    else
      log_success "Data freshly processed (${processing_age} minutes ago)"
    fi
  fi

  # ==========================================================================
  # CHECK 4: No Partial Writes (Game-Level)
  # ==========================================================================

  log_section "CHECK 4: Partial Write Detection"

  # For player tables, check if we have data for all games
  if [[ "$TABLE_NAME" == *"player"* ]]; then
    # Get expected games for this date
    local expected_games=$(bq_query_value "
      SELECT COUNT(DISTINCT game_id)
      FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
      WHERE game_date = '$DATE'
    " 2>/dev/null || echo "0")

    if [[ "$expected_games" -eq 0 ]]; then
      log_info "No reference games found in raw data - skipping partial write check"
    else
      local actual_games=$(bq_query_value "
        SELECT COUNT(DISTINCT game_id)
        FROM \`$full_table\`
        WHERE game_date = '$DATE'
      ")

      log_info "Games: $actual_games / $expected_games"

      if [[ "$actual_games" -lt "$expected_games" ]]; then
        log_warning "Only $actual_games of $expected_games games present (partial write?)"

        # Show which games are missing
        bq query --use_legacy_sql=false --format=pretty "
          SELECT game_id
          FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
          WHERE game_date = '$DATE'
          EXCEPT DISTINCT
          SELECT game_id
          FROM \`$full_table\`
          WHERE game_date = '$DATE'
        "
      else
        log_success "All $actual_games games present"
      fi
    fi
  fi

  # For team tables, check we have both teams for each game
  if [[ "$TABLE_NAME" == *"team_"* ]]; then
    local games_with_both_teams=$(bq_query_value "
      SELECT COUNT(DISTINCT game_id)
      FROM (
        SELECT game_id, COUNT(DISTINCT team_abbr) as team_count
        FROM \`$full_table\`
        WHERE game_date = '$DATE'
        GROUP BY game_id
        HAVING COUNT(DISTINCT team_abbr) = 2
      )
    ")

    local total_games=$(bq_query_value "
      SELECT COUNT(DISTINCT game_id)
      FROM \`$full_table\`
      WHERE game_date = '$DATE'
    ")

    log_info "Games with both teams: $games_with_both_teams / $total_games"

    if [[ "$games_with_both_teams" -ne "$total_games" ]]; then
      log_warning "Some games missing one team (partial write!)"

      # Show games with only 1 team
      bq query --use_legacy_sql=false --format=pretty "
        SELECT game_id, COUNT(DISTINCT team_abbr) as team_count,
               STRING_AGG(team_abbr) as teams_present
        FROM \`$full_table\`
        WHERE game_date = '$DATE'
        GROUP BY game_id
        HAVING COUNT(DISTINCT team_abbr) < 2
      "
    else
      log_success "All games have both teams"
    fi
  fi

  # ==========================================================================
  # FINAL RESULT
  # ==========================================================================

  log_section "VERIFICATION RESULT"
  echo ""
  log_success "✅ WRITE VERIFICATION PASSED"
  echo ""
  log_success "Summary:"
  log_success "  Date: $DATE"
  log_success "  Records: $(format_number $actual_count) (expected ≥$(format_number $EXPECTED_MIN))"
  log_success "  Status: Data successfully written"
  echo ""

  exit 0
}

main
