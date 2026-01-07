#!/bin/bash
# Backfill Orchestrator - Smart Phase Transition with Validation
# Monitors Phase 1 → Validates → Auto-starts Phase 2 → Validates → Reports
#
# Usage:
#   ./scripts/backfill_orchestrator.sh \
#     --phase1-pid 3022978 \
#     --phase1-log logs/team_offense_backfill_phase1.log \
#     --phase1-dates "2021-10-19 2026-01-02" \
#     --phase2-dates "2024-05-01 2026-01-02"

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/validation/common_validation.sh"

# Configuration
CONFIG_FILE="$SCRIPT_DIR/config/backfill_thresholds.yaml"
POLL_INTERVAL=$(parse_yaml_value "$CONFIG_FILE" "interval_seconds" || echo "60")
PROGRESS_UPDATE=$(parse_yaml_value "$CONFIG_FILE" "progress_update_interval" || echo "10")

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --phase1-pid)
            PHASE1_PID="$2"
            shift 2
            ;;
        --phase1-log)
            PHASE1_LOG="$2"
            shift 2
            ;;
        --phase1-dates)
            PHASE1_START=$(echo "$2" | cut -d' ' -f1)
            PHASE1_END=$(echo "$2" | cut -d' ' -f2)
            shift 2
            ;;
        --phase2-dates)
            PHASE2_START=$(echo "$2" | cut -d' ' -f1)
            PHASE2_END=$(echo "$2" | cut -d' ' -f2)
            shift 2
            ;;
        --config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Validate required arguments
if [[ -z "$PHASE1_PID" || -z "$PHASE1_LOG" || -z "$PHASE1_START" || -z "$PHASE1_END" ]]; then
    cat <<EOF
Usage: $0 \\
  --phase1-pid <PID> \\
  --phase1-log <log_file> \\
  --phase1-dates "<start_date> <end_date>" \\
  --phase2-dates "<start_date> <end_date>" \\
  [--config <config_file>] \\
  [--dry-run]

Example:
  $0 \\
    --phase1-pid 3022978 \\
    --phase1-log logs/team_offense_backfill_phase1.log \\
    --phase1-dates "2021-10-19 2026-01-02" \\
    --phase2-dates "2024-05-01 2026-01-02"
EOF
    exit 1
fi

# Start orchestration
START_TIME=$(date +%s)

log_section "BACKFILL ORCHESTRATOR STARTED"
log_info "Configuration:"
log_info "  Phase 1: team_offense_game_summary"
log_info "    PID: $PHASE1_PID"
log_info "    Log: $PHASE1_LOG"
log_info "    Dates: $PHASE1_START to $PHASE1_END"

if [[ -n "$PHASE2_START" ]]; then
    log_info "  Phase 2: player_game_summary (auto-start if Phase 1 passes)"
    log_info "    Dates: $PHASE2_START to $PHASE2_END"
fi

log_info "  Config: $CONFIG_FILE"
log_info "  Poll interval: ${POLL_INTERVAL}s"
[[ "$DRY_RUN" == "true" ]] && log_warning "DRY RUN MODE - No Phase 2 auto-start"
echo ""

# ============================================================================
# PHASE 1: Monitor team_offense backfill
# ============================================================================

log_section "PHASE 1: MONITORING TEAM_OFFENSE BACKFILL"

# Check if process is running
if ! kill -0 "$PHASE1_PID" 2>/dev/null; then
    log_error "Phase 1 process (PID $PHASE1_PID) is not running!"
    log_info "It may have already completed. Checking logs..."
else
    log_info "Process is running (PID $PHASE1_PID)"
    log_info "Monitoring until completion..."
    echo ""

    POLL_COUNT=0
    while kill -0 "$PHASE1_PID" 2>/dev/null; do
        POLL_COUNT=$((POLL_COUNT + 1))

        # Show progress update every N polls
        if [[ $((POLL_COUNT % PROGRESS_UPDATE)) -eq 0 ]]; then
            ELAPSED=$(($(date +%s) - START_TIME))
            DURATION=$(format_duration $ELAPSED)

            # Parse log for progress
            if [[ -f "$PHASE1_LOG" ]]; then
                METRICS=$(bash "$SCRIPT_DIR/monitoring/parse_backfill_log.sh" "$PHASE1_LOG" 2>/dev/null)

                if [[ $? -eq 0 ]]; then
                    CURRENT_DAY=$(echo "$METRICS" | grep -oP '"current_day": \K\d+')
                    TOTAL_DAYS=$(echo "$METRICS" | grep -oP '"total_days": \K\d+')
                    SUCCESS_RATE=$(echo "$METRICS" | grep -oP '"success_rate": \K[\d.]+')
                    TOTAL_RECORDS=$(echo "$METRICS" | grep -oP '"total_records": \K\d+')

                    if [[ -n "$CURRENT_DAY" && "$TOTAL_DAYS" -gt 0 ]]; then
                        PROGRESS_PCT=$(echo "scale=1; ($CURRENT_DAY / $TOTAL_DAYS) * 100" | bc -l)
                        REMAINING=$((TOTAL_DAYS - CURRENT_DAY))

                        log_info "Progress: $CURRENT_DAY/$TOTAL_DAYS days (${PROGRESS_PCT}%), $REMAINING remaining"
                        log_info "  Success rate: $(format_pct $SUCCESS_RATE), Records: $(format_number $TOTAL_RECORDS)"
                        log_info "  Elapsed: $DURATION"
                    fi
                fi
            fi
        fi

        sleep "$POLL_INTERVAL"
    done

    # Process has exited
    ELAPSED=$(($(date +%s) - START_TIME))
    DURATION=$(format_duration $ELAPSED)
    log_info "Process exited after $DURATION"
fi

# Parse final log results
echo ""
log_info "Parsing Phase 1 results..."

if [[ ! -f "$PHASE1_LOG" ]]; then
    log_error "Log file not found: $PHASE1_LOG"
    exit 1
fi

METRICS=$(bash "$SCRIPT_DIR/monitoring/parse_backfill_log.sh" "$PHASE1_LOG")

if [[ $? -ne 0 ]]; then
    log_error "Failed to parse Phase 1 log"
    exit 1
fi

# Extract metrics
COMPLETED=$(echo "$METRICS" | grep -oP '"completed": \K\w+')
SUCCESS_DAYS=$(echo "$METRICS" | grep -oP '"successful_days": \K\d+')
FAILED_DAYS=$(echo "$METRICS" | grep -oP '"failed_days": \K\d+')
TOTAL_DAYS=$(echo "$METRICS" | grep -oP '"total_days": \K\d+')
SUCCESS_RATE=$(echo "$METRICS" | grep -oP '"success_rate": \K[\d.]+')
TOTAL_RECORDS=$(echo "$METRICS" | grep -oP '"total_records": \K\d+')
FATAL_ERRORS=$(echo "$METRICS" | grep -oP '"fatal_errors": \K\d+')

log_info "Results:"
log_info "  Completed: $COMPLETED"
log_info "  Successful: $SUCCESS_DAYS/$TOTAL_DAYS ($(format_pct $SUCCESS_RATE))"
log_info "  Failed: $FAILED_DAYS"
log_info "  Records: $(format_number $TOTAL_RECORDS)"
log_info "  Fatal errors: $FATAL_ERRORS"

# Check if completed
if [[ "$COMPLETED" != "true" ]]; then
    log_error "Phase 1 did not complete properly"
    log_info "Check log file: $PHASE1_LOG"
    exit 1
fi

# Check success rate threshold
MIN_SUCCESS_RATE=$(parse_yaml_value "$CONFIG_FILE" "min_success_rate")
if ! check_threshold "$SUCCESS_RATE" "$MIN_SUCCESS_RATE" ">="; then
    log_error "Success rate $(format_pct $SUCCESS_RATE) below threshold ${MIN_SUCCESS_RATE}%"
    exit 1
fi

log_success "Phase 1 execution completed successfully"

# ============================================================================
# PHASE 1: Validate team_offense data quality
# ============================================================================

echo ""
log_section "PHASE 1: VALIDATING DATA QUALITY"

bash "$SCRIPT_DIR/validation/validate_team_offense.sh" "$PHASE1_START" "$PHASE1_END" "$CONFIG_FILE"
PHASE1_VALIDATION=$?

if [[ $PHASE1_VALIDATION -ne 0 ]]; then
    log_error "Phase 1 validation FAILED"
    log_info "team_offense backfill completed but data quality issues detected"
    log_info "Manual review required before proceeding to Phase 2"
    exit 1
fi

log_success "Phase 1 validation PASSED - data quality confirmed"

# ============================================================================
# PHASE 2: Auto-start player_game_summary backfill
# ============================================================================

echo ""
log_section "PHASE 2: PLAYER_GAME_SUMMARY BACKFILL"

if [[ -z "$PHASE2_START" ]]; then
    log_info "Phase 2 dates not provided - stopping here"
    log_success "Orchestrator completed successfully (Phase 1 only)"
    exit 0
fi

if [[ "$DRY_RUN" == "true" ]]; then
    log_warning "DRY RUN MODE - Would start Phase 2 here"
    log_info "Command: PYTHONPATH=. .venv/bin/python \\"
    log_info "  backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \\"
    log_info "  --start-date $PHASE2_START --end-date $PHASE2_END --parallel --workers 15 --no-resume"
    exit 0
fi

log_success "Phase 1 complete and validated - starting Phase 2"
log_info "Date range: $PHASE2_START to $PHASE2_END"
echo ""

# Create Phase 2 log file
PHASE2_LOG="logs/player_game_summary_backfill_phase2.log"
log_info "Phase 2 log: $PHASE2_LOG"

# Start Phase 2 in background
PHASE2_CMD="PYTHONPATH=. .venv/bin/python \
  backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date $PHASE2_START \
  --end-date $PHASE2_END \
  --parallel \
  --workers 15 \
  --no-resume"

log_info "Starting Phase 2..."
nohup $PHASE2_CMD > "$PHASE2_LOG" 2>&1 &
PHASE2_PID=$!

if ! kill -0 "$PHASE2_PID" 2>/dev/null; then
    log_error "Failed to start Phase 2"
    exit 1
fi

log_success "Phase 2 started (PID $PHASE2_PID)"
log_info "Monitor with: tail -f $PHASE2_LOG"
echo ""

# Monitor Phase 2
PHASE2_START_TIME=$(date +%s)
log_info "Monitoring Phase 2..."
echo ""

POLL_COUNT=0
while kill -0 "$PHASE2_PID" 2>/dev/null; do
    POLL_COUNT=$((POLL_COUNT + 1))

    # Show progress update every N polls
    if [[ $((POLL_COUNT % PROGRESS_UPDATE)) -eq 0 ]]; then
        ELAPSED=$(($(date +%s) - PHASE2_START_TIME))
        DURATION=$(format_duration $ELAPSED)

        # Parse log for progress
        if [[ -f "$PHASE2_LOG" ]]; then
            METRICS=$(bash "$SCRIPT_DIR/monitoring/parse_backfill_log.sh" "$PHASE2_LOG" 2>/dev/null)

            if [[ $? -eq 0 ]]; then
                CURRENT_DAY=$(echo "$METRICS" | grep -oP '"current_day": \K\d+')
                TOTAL_DAYS=$(echo "$METRICS" | grep -oP '"total_days": \K\d+')
                SUCCESS_RATE=$(echo "$METRICS" | grep -oP '"success_rate": \K[\d.]+')
                TOTAL_RECORDS=$(echo "$METRICS" | grep -oP '"total_records": \K\d+')

                if [[ -n "$CURRENT_DAY" && "$TOTAL_DAYS" -gt 0 ]]; then
                    PROGRESS_PCT=$(echo "scale=1; ($CURRENT_DAY / $TOTAL_DAYS) * 100" | bc -l)
                    REMAINING=$((TOTAL_DAYS - CURRENT_DAY))

                    log_info "Progress: $CURRENT_DAY/$TOTAL_DAYS days (${PROGRESS_PCT}%), $REMAINING remaining"
                    log_info "  Success rate: $(format_pct $SUCCESS_RATE), Records: $(format_number $TOTAL_RECORDS)"
                    log_info "  Elapsed: $DURATION"
                fi
            fi
        fi
    fi

    sleep "$POLL_INTERVAL"
done

# Phase 2 has exited
ELAPSED=$(($(date +%s) - PHASE2_START_TIME))
DURATION=$(format_duration $ELAPSED)
log_info "Process exited after $DURATION"

# Parse Phase 2 results
echo ""
log_info "Parsing Phase 2 results..."

METRICS=$(bash "$SCRIPT_DIR/monitoring/parse_backfill_log.sh" "$PHASE2_LOG")

if [[ $? -ne 0 ]]; then
    log_error "Failed to parse Phase 2 log"
    exit 1
fi

COMPLETED=$(echo "$METRICS" | grep -oP '"completed": \K\w+')
SUCCESS_DAYS=$(echo "$METRICS" | grep -oP '"successful_days": \K\d+')
FAILED_DAYS=$(echo "$METRICS" | grep -oP '"failed_days": \K\d+')
TOTAL_DAYS=$(echo "$METRICS" | grep -oP '"total_days": \K\d+')
SUCCESS_RATE=$(echo "$METRICS" | grep -oP '"success_rate": \K[\d.]+')
TOTAL_RECORDS=$(echo "$METRICS" | grep -oP '"total_records": \K\d+')

log_info "Results:"
log_info "  Completed: $COMPLETED"
log_info "  Successful: $SUCCESS_DAYS/$TOTAL_DAYS ($(format_pct $SUCCESS_RATE))"
log_info "  Failed: $FAILED_DAYS"
log_info "  Records: $(format_number $TOTAL_RECORDS)"

if [[ "$COMPLETED" != "true" ]]; then
    log_error "Phase 2 did not complete properly"
    exit 1
fi

log_success "Phase 2 execution completed successfully"

# ============================================================================
# PHASE 2: Validate player_game_summary data quality
# ============================================================================

echo ""
log_section "PHASE 2: VALIDATING DATA QUALITY"

bash "$SCRIPT_DIR/validation/validate_player_summary.sh" "$PHASE2_START" "$PHASE2_END" "$CONFIG_FILE"
PHASE2_VALIDATION=$?

if [[ $PHASE2_VALIDATION -ne 0 ]]; then
    log_error "Phase 2 validation FAILED"
    log_info "player_game_summary backfill completed but data quality issues detected"
    exit 1
fi

log_success "Phase 2 validation PASSED - data quality confirmed"

# ============================================================================
# FINAL REPORT
# ============================================================================

TOTAL_ELAPSED=$(($(date +%s) - START_TIME))
TOTAL_DURATION=$(format_duration $TOTAL_ELAPSED)

echo ""
log_section "ORCHESTRATOR FINAL REPORT"

log_success "ALL PHASES COMPLETE & VALIDATED ✓"
echo ""
log_info "Phase 1: team_offense_game_summary"
log_info "  Duration: $(format_duration $ELAPSED)"
log_info "  Success rate: $(format_pct $SUCCESS_RATE)"
log_info "  Records: $(format_number $TOTAL_RECORDS)"
log_info "  Validation: ✅ PASSED"
echo ""
log_info "Phase 2: player_game_summary"
log_info "  Duration: $DURATION"
log_info "  Success rate: $(format_pct $SUCCESS_RATE)"
log_info "  Records: $(format_number $TOTAL_RECORDS)"
log_info "  Validation: ✅ PASSED"
echo ""
log_info "Total Duration: $TOTAL_DURATION"
log_success "Data is ready for ML training! 🎉"
echo ""
log_info "Next steps:"
log_info "  1. ⏭️  Run Phase 4 backfill (precompute)"
log_info "  2. ⏭️  Train XGBoost v5 model"
log_info "  3. ⏭️  Compare to 4.27 MAE baseline"

exit 0
