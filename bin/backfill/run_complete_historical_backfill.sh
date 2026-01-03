#!/bin/bash
#
# Complete Historical Backfill Execution Script
# =============================================
# Fills all known data gaps across 4 historical seasons (2021-2024)
#
# What this script does:
# 1. Validates current state
# 2. Backfills Phase 3 analytics (playoffs)
# 3. Backfills Phase 4 precompute (playoffs)
# 4. Backfills Phase 5 predictions (playoffs)
# 5. Backfills Phase 5B grading (2024-25 season)
# 6. Validates final state
#
# Usage:
#   ./bin/backfill/run_complete_historical_backfill.sh [--dry-run] [--start-from STEP]
#
# Options:
#   --dry-run        Show what would be done without executing
#   --start-from N   Resume from step N (1-6)
#   --skip-validation Skip pre-flight validation
#
# Date: 2026-01-02
#

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# =============================================================================
# Configuration
# =============================================================================

PROJECT_ROOT="/home/naji/code/nba-stats-scraper"
LOG_DIR="$PROJECT_ROOT/logs/backfill"
LOG_FILE="$LOG_DIR/complete_backfill_$(date +%Y%m%d_%H%M%S).log"

# Playoff date ranges
PLAYOFF_2021_22_START="2022-04-16"
PLAYOFF_2021_22_END="2022-06-17"

PLAYOFF_2022_23_START="2023-04-15"
PLAYOFF_2022_23_END="2023-06-13"

PLAYOFF_2023_24_START="2024-04-16"
PLAYOFF_2023_24_END="2024-06-18"

# 2024-25 Season range (for grading)
SEASON_2024_25_START="2024-10-22"
SEASON_2024_25_END="2025-04-30"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# =============================================================================
# Helper Functions
# =============================================================================

log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $*" | tee -a "$LOG_FILE"
}

log_success() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] ✅ $*${NC}" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ❌ $*${NC}" | tee -a "$LOG_FILE"
}

log_warning() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] ⚠️  $*${NC}" | tee -a "$LOG_FILE"
}

log_header() {
    echo "" | tee -a "$LOG_FILE"
    echo -e "${BLUE}========================================${NC}" | tee -a "$LOG_FILE"
    echo -e "${BLUE}$*${NC}" | tee -a "$LOG_FILE"
    echo -e "${BLUE}========================================${NC}" | tee -a "$LOG_FILE"
    echo "" | tee -a "$LOG_FILE"
}

# Checkpoint: Save progress state
save_checkpoint() {
    local step=$1
    echo "$step" > "$LOG_DIR/checkpoint.txt"
    log "Checkpoint saved: Step $step"
}

# Load last checkpoint
load_checkpoint() {
    if [ -f "$LOG_DIR/checkpoint.txt" ]; then
        cat "$LOG_DIR/checkpoint.txt"
    else
        echo "0"
    fi
}

# Validate BigQuery connectivity
validate_bq_access() {
    log "Validating BigQuery access..."
    if bq ls nba-props-platform:nba_raw > /dev/null 2>&1; then
        log_success "BigQuery access confirmed"
        return 0
    else
        log_error "Cannot access BigQuery. Check authentication."
        return 1
    fi
}

# Run BigQuery query and return result
run_bq_query() {
    local query=$1
    bq query --use_legacy_sql=false --format=csv "$query" 2>/dev/null | tail -n +2
}

# Validate Phase 3 analytics completeness
validate_phase3() {
    log "Validating Phase 3 analytics completeness..."

    local query="
    SELECT
      season_year,
      COUNT(DISTINCT game_code) as games
    FROM \`nba-props-platform.nba_analytics.player_game_summary\`
    WHERE season_year IN (2021, 2022, 2023)
      AND game_date >= CASE
        WHEN season_year = 2021 THEN '2022-04-16'
        WHEN season_year = 2022 THEN '2023-04-15'
        WHEN season_year = 2023 THEN '2024-04-16'
      END
    GROUP BY season_year
    ORDER BY season_year
    "

    local results=$(run_bq_query "$query")

    if [ -z "$results" ]; then
        log_warning "No playoff games found in Phase 3 (expected - needs backfill)"
        return 1
    else
        log_success "Phase 3 playoff data exists"
        echo "$results" | while IFS=, read -r season games; do
            log "  Season $season: $games playoff games"
        done
        return 0
    fi
}

# Validate Phase 4 precompute completeness
validate_phase4() {
    log "Validating Phase 4 precompute completeness..."

    local query="
    SELECT COUNT(DISTINCT game_date) as playoff_dates
    FROM \`nba-props-platform.nba_precompute.player_composite_factors\`
    WHERE (
      (game_date >= '2022-04-16' AND game_date <= '2022-06-17') OR
      (game_date >= '2023-04-15' AND game_date <= '2023-06-13') OR
      (game_date >= '2024-04-16' AND game_date <= '2024-06-18')
    )
    "

    local count=$(run_bq_query "$query")

    if [ "$count" -eq "0" ]; then
        log_warning "No playoff dates in Phase 4 (expected - needs backfill)"
        return 1
    else
        log_success "Phase 4 has $count playoff dates"
        return 0
    fi
}

# Validate Phase 5B grading for 2024-25
validate_phase5b_2024() {
    log "Validating Phase 5B grading for 2024-25..."

    local query="
    SELECT COUNT(*) as graded_predictions
    FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
    WHERE season_year = 2024
    "

    local count=$(run_bq_query "$query")

    if [ "$count" -lt "10000" ]; then
        log_warning "2024-25 grading incomplete ($count records, expected ~100k)"
        return 1
    else
        log_success "2024-25 has $count graded predictions"
        return 0
    fi
}

# =============================================================================
# Backfill Execution Functions
# =============================================================================

# Run Phase 3 analytics backfill for a date range
run_phase3_backfill() {
    local start_date=$1
    local end_date=$2
    local season_name=$3

    log "Running Phase 3 backfill: $season_name ($start_date to $end_date)"

    cd "$PROJECT_ROOT"

    if [ "$DRY_RUN" = true ]; then
        log "[DRY RUN] Would execute: player_game_summary_analytics_backfill.py --start-date $start_date --end-date $end_date"
        return 0
    fi

    PYTHONPATH=. .venv/bin/python \
        backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
        --start-date "$start_date" \
        --end-date "$end_date" \
        2>&1 | tee -a "$LOG_FILE"

    local exit_code=${PIPESTATUS[0]}

    if [ $exit_code -eq 0 ]; then
        log_success "Phase 3 backfill complete: $season_name"
        return 0
    else
        log_error "Phase 3 backfill failed: $season_name (exit code: $exit_code)"
        return 1
    fi
}

# Run Phase 4 precompute backfill for a date range
run_phase4_backfill() {
    local start_date=$1
    local end_date=$2
    local season_name=$3

    log "Running Phase 4 backfill: $season_name ($start_date to $end_date)"

    cd "$PROJECT_ROOT"

    if [ "$DRY_RUN" = true ]; then
        log "[DRY RUN] Would execute: run_phase4_backfill.sh --start-date $start_date --end-date $end_date"
        return 0
    fi

    ./bin/backfill/run_phase4_backfill.sh \
        --start-date "$start_date" \
        --end-date "$end_date" \
        2>&1 | tee -a "$LOG_FILE"

    local exit_code=${PIPESTATUS[0]}

    if [ $exit_code -eq 0 ]; then
        log_success "Phase 4 backfill complete: $season_name"
        return 0
    else
        log_error "Phase 4 backfill failed: $season_name (exit code: $exit_code)"
        return 1
    fi
}

# Run Phase 5 predictions backfill for a date range
run_phase5_backfill() {
    local start_date=$1
    local end_date=$2
    local season_name=$3

    log "Running Phase 5 predictions: $season_name ($start_date to $end_date)"

    if [ "$DRY_RUN" = true ]; then
        log "[DRY RUN] Would trigger prediction coordinator for $start_date to $end_date"
        return 0
    fi

    # Get auth token
    local token
    token=$(gcloud auth print-identity-token 2>/dev/null)

    if [ -z "$token" ]; then
        log_error "Failed to get auth token. Run: gcloud auth login"
        return 1
    fi

    # Start prediction batch
    local response
    response=$(curl -s -X POST \
        https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        -d "{
            \"start_date\": \"$start_date\",
            \"end_date\": \"$end_date\"
        }")

    log "Prediction coordinator response: $response"

    # Extract batch_id (if using jq)
    if command -v jq &> /dev/null; then
        local batch_id
        batch_id=$(echo "$response" | jq -r '.batch_id // empty')

        if [ -n "$batch_id" ]; then
            log "Batch started: $batch_id"
            log "Monitoring progress (this may take 15-30 minutes)..."

            # Monitor progress
            local is_complete=false
            local attempts=0
            local max_attempts=60  # 30 minutes (30 sec intervals)

            while [ "$is_complete" = false ] && [ $attempts -lt $max_attempts ]; do
                sleep 30
                attempts=$((attempts + 1))

                local status
                status=$(curl -s -H "Authorization: Bearer $token" \
                    "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/status?batch_id=$batch_id")

                is_complete=$(echo "$status" | jq -r '.progress.is_complete // false')

                local progress
                progress=$(echo "$status" | jq -r '.progress.percent_complete // 0')
                log "Progress: $progress%"

                if [ "$is_complete" = "true" ]; then
                    log_success "Predictions complete: $season_name"
                    return 0
                fi
            done

            if [ $attempts -ge $max_attempts ]; then
                log_warning "Prediction monitoring timed out after 30 minutes"
                log_warning "Check status manually: curl -H 'Authorization: Bearer TOKEN' 'https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/status?batch_id=$batch_id'"
                return 0  # Don't fail - predictions may still be running
            fi
        else
            log_warning "Could not extract batch_id from response"
            return 0  # Don't fail - may have started successfully
        fi
    else
        log_warning "jq not installed - cannot monitor progress"
        log "Response: $response"
        return 0
    fi
}

# Run Phase 5B grading backfill
run_phase5b_grading() {
    log "Running Phase 5B grading for 2024-25 season..."

    if [ "$DRY_RUN" = true ]; then
        log "[DRY RUN] Would execute grading backfill for 2024-25"
        return 0
    fi

    # First, check if grading script exists
    if [ -f "$PROJECT_ROOT/backfill_jobs/prediction/grade_predictions_backfill.py" ]; then
        cd "$PROJECT_ROOT"
        PYTHONPATH=. .venv/bin/python \
            backfill_jobs/prediction/grade_predictions_backfill.py \
            --start-date "$SEASON_2024_25_START" \
            --end-date "$SEASON_2024_25_END" \
            2>&1 | tee -a "$LOG_FILE"

        local exit_code=${PIPESTATUS[0]}

        if [ $exit_code -eq 0 ]; then
            log_success "Phase 5B grading complete for 2024-25"
            return 0
        else
            log_error "Phase 5B grading failed (exit code: $exit_code)"
            return 1
        fi
    else
        log_warning "Grading backfill script not found at expected location"
        log "Please manually investigate how to grade 2024-25 predictions"
        log "Search: grep -r 'prediction_accuracy' --include='*.py' backfill_jobs/"
        return 1
    fi
}

# =============================================================================
# Main Execution Steps
# =============================================================================

step0_preflight() {
    log_header "STEP 0: Pre-Flight Validation"

    if [ "$SKIP_VALIDATION" = true ]; then
        log_warning "Skipping validation (--skip-validation flag)"
        return 0
    fi

    # Check BigQuery access
    if ! validate_bq_access; then
        log_error "Pre-flight check failed: BigQuery access"
        return 1
    fi

    # Check Python environment
    if [ ! -f "$PROJECT_ROOT/.venv/bin/python" ]; then
        log_error "Python virtual environment not found"
        log "Expected: $PROJECT_ROOT/.venv/bin/python"
        return 1
    fi

    # Check scripts exist
    if [ ! -f "$PROJECT_ROOT/backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py" ]; then
        log_error "Phase 3 backfill script not found"
        return 1
    fi

    if [ ! -f "$PROJECT_ROOT/bin/backfill/run_phase4_backfill.sh" ]; then
        log_error "Phase 4 backfill script not found"
        return 1
    fi

    log_success "Pre-flight validation passed"
    return 0
}

step1_phase3_backfill() {
    log_header "STEP 1: Phase 3 Analytics Backfill (Playoffs)"

    # 2021-22 Playoffs
    if ! run_phase3_backfill "$PLAYOFF_2021_22_START" "$PLAYOFF_2021_22_END" "2021-22 Playoffs"; then
        log_error "Failed to backfill 2021-22 playoffs"
        return 1
    fi

    # 2022-23 Playoffs
    if ! run_phase3_backfill "$PLAYOFF_2022_23_START" "$PLAYOFF_2022_23_END" "2022-23 Playoffs"; then
        log_error "Failed to backfill 2022-23 playoffs"
        return 1
    fi

    # 2023-24 Playoffs
    if ! run_phase3_backfill "$PLAYOFF_2023_24_START" "$PLAYOFF_2023_24_END" "2023-24 Playoffs"; then
        log_error "Failed to backfill 2023-24 playoffs"
        return 1
    fi

    log_success "All Phase 3 backfills complete"
    save_checkpoint 1
    return 0
}

step2_phase4_backfill() {
    log_header "STEP 2: Phase 4 Precompute Backfill (Playoffs)"

    # 2021-22 Playoffs
    if ! run_phase4_backfill "$PLAYOFF_2021_22_START" "$PLAYOFF_2021_22_END" "2021-22 Playoffs"; then
        log_error "Failed to backfill Phase 4 for 2021-22 playoffs"
        return 1
    fi

    # 2022-23 Playoffs
    if ! run_phase4_backfill "$PLAYOFF_2022_23_START" "$PLAYOFF_2022_23_END" "2022-23 Playoffs"; then
        log_error "Failed to backfill Phase 4 for 2022-23 playoffs"
        return 1
    fi

    # 2023-24 Playoffs
    if ! run_phase4_backfill "$PLAYOFF_2023_24_START" "$PLAYOFF_2023_24_END" "2023-24 Playoffs"; then
        log_error "Failed to backfill Phase 4 for 2023-24 playoffs"
        return 1
    fi

    log_success "All Phase 4 backfills complete"
    save_checkpoint 2
    return 0
}

step3_phase5_backfill() {
    log_header "STEP 3: Phase 5 Predictions Backfill (Playoffs)"

    # 2021-22 Playoffs
    if ! run_phase5_backfill "$PLAYOFF_2021_22_START" "$PLAYOFF_2021_22_END" "2021-22 Playoffs"; then
        log_error "Failed to trigger predictions for 2021-22 playoffs"
        return 1
    fi

    # 2022-23 Playoffs
    if ! run_phase5_backfill "$PLAYOFF_2022_23_START" "$PLAYOFF_2022_23_END" "2022-23 Playoffs"; then
        log_error "Failed to trigger predictions for 2022-23 playoffs"
        return 1
    fi

    # 2023-24 Playoffs
    if ! run_phase5_backfill "$PLAYOFF_2023_24_START" "$PLAYOFF_2023_24_END" "2023-24 Playoffs"; then
        log_error "Failed to trigger predictions for 2023-24 playoffs"
        return 1
    fi

    log_success "All Phase 5 predictions triggered"
    save_checkpoint 3
    return 0
}

step4_phase5b_grading() {
    log_header "STEP 4: Phase 5B Grading Backfill (2024-25 Season)"

    if ! run_phase5b_grading; then
        log_error "Failed to run Phase 5B grading"
        return 1
    fi

    log_success "Phase 5B grading complete"
    save_checkpoint 4
    return 0
}

step5_final_validation() {
    log_header "STEP 5: Final Validation"

    if [ "$DRY_RUN" = true ]; then
        log "[DRY RUN] Would run final validation queries"
        return 0
    fi

    local all_passed=true

    # Validate Phase 3
    if validate_phase3; then
        log_success "Phase 3 validation passed"
    else
        log_error "Phase 3 validation failed"
        all_passed=false
    fi

    # Validate Phase 4
    if validate_phase4; then
        log_success "Phase 4 validation passed"
    else
        log_error "Phase 4 validation failed"
        all_passed=false
    fi

    # Validate Phase 5B for 2024-25
    if validate_phase5b_2024; then
        log_success "Phase 5B (2024-25) validation passed"
    else
        log_error "Phase 5B (2024-25) validation failed"
        all_passed=false
    fi

    if [ "$all_passed" = true ]; then
        log_success "All validations passed! ✅"
        save_checkpoint 5
        return 0
    else
        log_error "Some validations failed. Review logs."
        return 1
    fi
}

# =============================================================================
# Main Script
# =============================================================================

main() {
    # Parse arguments
    DRY_RUN=false
    SKIP_VALIDATION=false
    START_FROM_STEP=0

    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --skip-validation)
                SKIP_VALIDATION=true
                shift
                ;;
            --start-from)
                START_FROM_STEP=$2
                shift 2
                ;;
            --help)
                cat << EOF
Complete Historical Backfill Execution Script

Usage: $0 [OPTIONS]

Options:
  --dry-run             Show what would be done without executing
  --start-from STEP     Resume from step N (0-5)
  --skip-validation     Skip pre-flight validation
  --help                Show this help message

Steps:
  0 - Pre-flight validation
  1 - Phase 3 analytics backfill (playoffs)
  2 - Phase 4 precompute backfill (playoffs)
  3 - Phase 5 predictions backfill (playoffs)
  4 - Phase 5B grading backfill (2024-25)
  5 - Final validation

Example:
  # Run complete backfill
  $0

  # Dry run to see what would happen
  $0 --dry-run

  # Resume from step 2 (Phase 4)
  $0 --start-from 2

EOF
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done

    # Create log directory
    mkdir -p "$LOG_DIR"

    # Check for existing checkpoint
    if [ $START_FROM_STEP -eq 0 ]; then
        LAST_CHECKPOINT=$(load_checkpoint)
        if [ "$LAST_CHECKPOINT" -gt 0 ]; then
            log_warning "Found checkpoint at step $LAST_CHECKPOINT"
            read -p "Resume from step $LAST_CHECKPOINT? (y/n) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                START_FROM_STEP=$LAST_CHECKPOINT
            fi
        fi
    fi

    # Print header
    log_header "COMPLETE HISTORICAL BACKFILL"
    log "Project: $PROJECT_ROOT"
    log "Log file: $LOG_FILE"
    log "Dry run: $DRY_RUN"
    log "Starting from step: $START_FROM_STEP"
    log ""
    log "This will backfill:"
    log "  - Phase 3 analytics: 2021-24 playoffs (~430 games)"
    log "  - Phase 4 precompute: 2021-24 playoffs (~186 dates)"
    log "  - Phase 5 predictions: 2021-24 playoffs"
    log "  - Phase 5B grading: 2024-25 season (~100k predictions)"
    log ""
    log "Estimated time: 6-8 hours"
    log ""

    if [ "$DRY_RUN" = false ]; then
        read -p "Continue? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log "Cancelled by user"
            exit 0
        fi
    fi

    local start_time=$(date +%s)

    # Execute steps
    if [ $START_FROM_STEP -le 0 ]; then
        if ! step0_preflight; then
            log_error "Pre-flight validation failed. Exiting."
            exit 1
        fi
    fi

    if [ $START_FROM_STEP -le 1 ]; then
        if ! step1_phase3_backfill; then
            log_error "Step 1 failed. Exiting."
            exit 1
        fi
    fi

    if [ $START_FROM_STEP -le 2 ]; then
        if ! step2_phase4_backfill; then
            log_error "Step 2 failed. Exiting."
            exit 1
        fi
    fi

    if [ $START_FROM_STEP -le 3 ]; then
        if ! step3_phase5_backfill; then
            log_error "Step 3 failed. Exiting."
            exit 1
        fi
    fi

    if [ $START_FROM_STEP -le 4 ]; then
        if ! step4_phase5b_grading; then
            log_error "Step 4 failed. Exiting."
            exit 1
        fi
    fi

    if [ $START_FROM_STEP -le 5 ]; then
        if ! step5_final_validation; then
            log_error "Step 5 failed. Exiting."
            exit 1
        fi
    fi

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local hours=$((duration / 3600))
    local minutes=$(( (duration % 3600) / 60 ))

    log_header "BACKFILL COMPLETE! 🎉"
    log_success "Total duration: ${hours}h ${minutes}m"
    log "Log file: $LOG_FILE"
    log ""
    log "Next steps:"
    log "  1. Review validation results above"
    log "  2. Check BigQuery for complete data"
    log "  3. Start ML work (see ml-model-development/README.md)"
    log ""
    log "See also: docs/08-projects/current/backfill-system-analysis/BACKFILL-COMPLETION-REPORT.md"
}

# Run main function
main "$@"
