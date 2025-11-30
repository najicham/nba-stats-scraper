#!/bin/bash
# Backfill Pre-Flight Verification Script
#
# Runs comprehensive checks before starting 4-year historical backfill.
# Validates infrastructure, data readiness, and job functionality.
#
# Usage:
#   ./bin/backfill/preflight_verification.sh [--quick]
#
# Options:
#   --quick    Skip time-consuming tests (dry-runs)
#
# Exit codes:
#   0 = All checks passed, ready for backfill
#   1 = Critical failures, do not proceed
#   2 = Warnings, proceed with caution
#
# Related: docs/08-projects/current/backfill/BACKFILL-PRE-EXECUTION-HANDOFF.md

# set -e  # Disabled: We want to see all check results, not exit on first error

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ID="nba-props-platform"
REGION="us-west2"
QUICK_MODE=false
BACKFILL_START="2021-10-01"
BACKFILL_END="2024-11-29"

# Counters
PASSED=0
FAILED=0
WARNINGS=0

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --quick)
      QUICK_MODE=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--quick]"
      exit 1
      ;;
  esac
done

# Helper functions
print_header() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_check() {
    echo -e "\n${BLUE}✓${NC} Checking: $1"
}

print_pass() {
    echo -e "${GREEN}  ✅ PASS:${NC} $1"
    ((PASSED++))
}

print_fail() {
    echo -e "${RED}  ❌ FAIL:${NC} $1"
    ((FAILED++))
}

print_warn() {
    echo -e "${YELLOW}  ⚠️  WARN:${NC} $1"
    ((WARNINGS++))
}

print_info() {
    echo -e "  ℹ️  $1"
}

print_summary() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}PRE-FLIGHT VERIFICATION SUMMARY${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo -e "${GREEN}Passed:   $PASSED${NC}"
    echo -e "${RED}Failed:   $FAILED${NC}"
    echo -e "${YELLOW}Warnings: $WARNINGS${NC}"
    echo ""

    if [ $FAILED -eq 0 ]; then
        if [ $WARNINGS -eq 0 ]; then
            echo -e "${GREEN}🎉 ALL CHECKS PASSED - READY FOR BACKFILL${NC}"
            echo ""
            return 0
        else
            echo -e "${YELLOW}⚠️  CHECKS PASSED WITH WARNINGS - PROCEED WITH CAUTION${NC}"
            echo ""
            return 2
        fi
    else
        echo -e "${RED}❌ CRITICAL FAILURES - DO NOT PROCEED WITH BACKFILL${NC}"
        echo -e "${RED}   Fix the failed checks before starting backfill.${NC}"
        echo ""
        return 1
    fi
}

# Check 1: GCP Project & Auth
check_gcp_auth() {
    print_check "GCP Authentication & Project"

    if ! gcloud config get-value project >/dev/null 2>&1; then
        print_fail "Not authenticated with gcloud. Run: gcloud auth login"
        return
    fi

    local current_project=$(gcloud config get-value project 2>/dev/null)
    if [ "$current_project" != "$PROJECT_ID" ]; then
        print_warn "Current project is '$current_project', expected '$PROJECT_ID'"
        print_info "Run: gcloud config set project $PROJECT_ID"
    else
        print_pass "Authenticated and using correct project: $PROJECT_ID"
    fi
}

# Check 2: Cloud Run Services Deployed
check_cloud_run_services() {
    print_check "Cloud Run Services Deployed"

    local required_services=(
        "nba-phase1-scrapers"
        "nba-phase2-raw-processors"
        "nba-phase3-analytics-processors"
        "nba-phase4-precompute-processors"
        "phase2-to-phase3-orchestrator"
        "phase3-to-phase4-orchestrator"
    )

    local all_good=true

    for service in "${required_services[@]}"; do
        if gcloud run services describe $service --region=$REGION --format="value(status.url)" >/dev/null 2>&1; then
            print_info "✓ $service is deployed"
        else
            print_fail "$service is NOT deployed"
            all_good=false
        fi
    done

    if [ "$all_good" = true ]; then
        print_pass "All 6 required Cloud Run services are deployed"
    fi
}

# Check 3: Phase 2 Data Completeness
check_phase2_completeness() {
    print_check "Phase 2 (Raw) Data Completeness"

    local query="
    WITH expected AS (
      SELECT COUNT(DISTINCT game_date) as cnt
      FROM \`$PROJECT_ID.nba_raw.nbac_schedule\`
      WHERE game_status = 3
        AND game_date BETWEEN '$BACKFILL_START' AND '$BACKFILL_END'
    ),
    actual AS (
      SELECT COUNT(DISTINCT game_date) as cnt
      FROM \`$PROJECT_ID.nba_raw.nbac_team_boxscore\`
      WHERE game_date BETWEEN '$BACKFILL_START' AND '$BACKFILL_END'
    )
    SELECT
      a.cnt as actual,
      e.cnt as expected,
      ROUND(100.0 * a.cnt / e.cnt, 1) as pct
    FROM actual a, expected e
    "

    local result=$(bq query --use_legacy_sql=false --format=csv "$query" 2>/dev/null | tail -n 1)
    local actual=$(echo $result | cut -d',' -f1)
    local expected=$(echo $result | cut -d',' -f2)
    local pct=$(echo $result | cut -d',' -f3)

    if [ "$actual" = "$expected" ]; then
        print_pass "Phase 2 complete: $actual/$expected dates (100%)"
    elif (( $(echo "$pct >= 99.0" | bc -l) )); then
        print_warn "Phase 2 mostly complete: $actual/$expected dates ($pct%)"
        print_info "This is acceptable, but some dates may be missing"
    else
        print_fail "Phase 2 incomplete: $actual/$expected dates ($pct%)"
        print_info "Need to backfill Phase 2 first"
    fi
}

# Check 4: Phase 3 Current State
check_phase3_state() {
    print_check "Phase 3 (Analytics) Current State"

    local query="
    SELECT COUNT(DISTINCT game_date) as cnt
    FROM \`$PROJECT_ID.nba_analytics.player_game_summary\`
    WHERE game_date BETWEEN '$BACKFILL_START' AND '$BACKFILL_END'
    "

    local actual=$(bq query --use_legacy_sql=false --format=csv "$query" 2>/dev/null | tail -n 1)

    print_info "Phase 3 has $actual dates (expecting increase to 675 after backfill)"
    print_pass "Phase 3 state captured: $actual dates"
}

# Check 5: Phase 4 Current State
check_phase4_state() {
    print_check "Phase 4 (Precompute) Current State"

    # Check player_shot_zone_analysis as representative Phase 4 table
    local query="
    SELECT COUNT(DISTINCT analysis_date) as cnt
    FROM \`$PROJECT_ID.nba_precompute.player_shot_zone_analysis\`
    WHERE analysis_date BETWEEN '$BACKFILL_START' AND '$BACKFILL_END'
    "

    local actual=$(bq query --use_legacy_sql=false --format=csv "$query" 2>/dev/null | tail -n 1)

    print_info "Phase 4 has $actual dates (expecting ~647 after backfill)"
    print_pass "Phase 4 state captured: $actual dates"
}

# Check 6: Phase 3 Backfill Jobs Exist
check_phase3_jobs() {
    print_check "Phase 3 Backfill Jobs Exist"

    local required_jobs=(
        "player_game_summary"
        "team_defense_game_summary"
        "team_offense_game_summary"
        "upcoming_player_game_context"
        "upcoming_team_game_context"
    )

    local all_exist=true

    for job in "${required_jobs[@]}"; do
        local job_path="backfill_jobs/analytics/$job/${job}_analytics_backfill.py"
        if [ -f "$job_path" ]; then
            print_info "✓ $job job exists"
        else
            print_fail "$job job NOT found at $job_path"
            all_exist=false
        fi
    done

    if [ "$all_exist" = true ]; then
        print_pass "All 5 Phase 3 backfill jobs exist"
    fi
}

# Check 7: Phase 4 Backfill Jobs Exist
check_phase4_jobs() {
    print_check "Phase 4 Backfill Jobs Exist"

    local required_jobs=(
        "team_defense_zone_analysis"
        "player_shot_zone_analysis"
        "player_composite_factors"
        "player_daily_cache"
        "ml_feature_store"
    )

    local all_exist=true

    for job in "${required_jobs[@]}"; do
        local job_path="backfill_jobs/precompute/$job/${job}_precompute_backfill.py"
        if [ -f "$job_path" ]; then
            print_info "✓ $job job exists"
        else
            print_fail "$job job NOT found at $job_path"
            all_exist=false
        fi
    done

    if [ "$all_exist" = true ]; then
        print_pass "All 5 Phase 4 backfill jobs exist"
    fi
}

# Check 8: BettingPros Fallback (Optional but Recommended)
check_bettingpros_fallback() {
    print_check "BettingPros Fallback Implementation"

    local processor_file="data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py"

    if ! [ -f "$processor_file" ]; then
        print_warn "Cannot find processor file: $processor_file"
        return
    fi

    # Check if file references bettingpros
    if grep -q "bettingpros_player_points_props" "$processor_file" 2>/dev/null; then
        print_pass "BettingPros fallback appears to be implemented"
        print_info "This will improve coverage from 40% to 99.7%"
    else
        print_warn "BettingPros fallback may not be implemented"
        print_info "Only Odds API = 40% coverage. With BettingPros = 99.7%"
        print_info "See: docs/09-handoff/2025-11-30-BETTINGPROS-FALLBACK-FIX-TASK.md"
    fi
}

# Check 9: Pub/Sub Topics Exist
check_pubsub_topics() {
    print_check "Pub/Sub Topics Exist"

    local required_topics=(
        "nba-phase2-raw-complete"
        "nba-phase3-analytics-complete"
        "nba-phase4-trigger"
    )

    local all_exist=true

    for topic in "${required_topics[@]}"; do
        if gcloud pubsub topics describe $topic >/dev/null 2>&1; then
            print_info "✓ $topic exists"
        else
            print_fail "$topic NOT found"
            all_exist=false
        fi
    done

    if [ "$all_exist" = true ]; then
        print_pass "All required Pub/Sub topics exist"
    fi
}

# Check 10: BigQuery Datasets Exist
check_bigquery_datasets() {
    print_check "BigQuery Datasets Exist"

    local required_datasets=(
        "nba_raw"
        "nba_analytics"
        "nba_precompute"
        "nba_reference"
    )

    local all_exist=true

    for dataset in "${required_datasets[@]}"; do
        if bq show --dataset $PROJECT_ID:$dataset >/dev/null 2>&1; then
            print_info "✓ $dataset exists"
        else
            print_fail "$dataset NOT found"
            all_exist=false
        fi
    done

    if [ "$all_exist" = true ]; then
        print_pass "All required BigQuery datasets exist"
    fi
}

# Check 11: Test Phase 3 Backfill Job (Dry-Run)
test_phase3_job() {
    if [ "$QUICK_MODE" = true ]; then
        print_info "Skipping Phase 3 dry-run test (--quick mode)"
        return
    fi

    print_check "Test Phase 3 Backfill Job (Dry-Run)"

    local test_job="backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py"

    if ! [ -f "$test_job" ]; then
        print_fail "Cannot find test job: $test_job"
        return
    fi

    print_info "Running dry-run for player_game_summary (this may take 10-20 seconds)..."

    if timeout 30 python3 "$test_job" --dry-run --dates 2023-11-15 >/dev/null 2>&1; then
        print_pass "Phase 3 dry-run successful"
    else
        print_fail "Phase 3 dry-run failed"
        print_info "Try running manually: python3 $test_job --dry-run --dates 2023-11-15"
    fi
}

# Check 12: Test Phase 4 Backfill Job (Dry-Run)
test_phase4_job() {
    if [ "$QUICK_MODE" = true ]; then
        print_info "Skipping Phase 4 dry-run test (--quick mode)"
        return
    fi

    print_check "Test Phase 4 Backfill Job (Dry-Run)"

    local test_job="backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py"

    if ! [ -f "$test_job" ]; then
        print_fail "Cannot find test job: $test_job"
        return
    fi

    print_info "Running dry-run for player_shot_zone_analysis (this may take 10-20 seconds)..."

    if timeout 30 python3 "$test_job" --dry-run --dates 2023-11-15 >/dev/null 2>&1; then
        print_pass "Phase 4 dry-run successful"
    else
        print_warn "Phase 4 dry-run failed (may be normal if dependencies missing)"
        print_info "Try running manually: python3 $test_job --dry-run --dates 2023-11-15"
    fi
}

# Check 13: Verify Backfill Monitor Exists
check_backfill_monitor() {
    print_check "Backfill Progress Monitor Available"

    local monitor="bin/infrastructure/monitoring/backfill_progress_monitor.py"

    if [ -f "$monitor" ]; then
        print_pass "Backfill monitor exists: $monitor"
        print_info "Run during backfill: python3 $monitor --continuous"
    else
        print_warn "Backfill monitor not found"
        print_info "You'll need to monitor progress manually via BigQuery"
    fi
}

# Check 14: Python Dependencies
check_python_deps() {
    print_check "Python Dependencies"

    if ! python3 -c "import google.cloud.bigquery" 2>/dev/null; then
        print_fail "google-cloud-bigquery not installed"
        print_info "Run: pip install google-cloud-bigquery"
        return
    fi

    print_pass "Python dependencies available"
}

# Main execution
main() {
    print_header "NBA BACKFILL PRE-FLIGHT VERIFICATION"

    if [ "$QUICK_MODE" = true ]; then
        print_info "Running in QUICK mode (skipping dry-run tests)"
    fi

    echo ""
    echo "This script will verify that all infrastructure and jobs are ready"
    echo "for the 4-year historical backfill (2021-2024, 675 game dates)."
    echo ""
    echo "Target date range: $BACKFILL_START to $BACKFILL_END"
    echo ""

    # Run all checks
    check_gcp_auth
    check_python_deps
    check_bigquery_datasets
    check_pubsub_topics
    check_cloud_run_services
    check_phase2_completeness
    check_phase3_state
    check_phase4_state
    check_phase3_jobs
    check_phase4_jobs
    check_bettingpros_fallback
    check_backfill_monitor
    test_phase3_job
    test_phase4_job

    # Print summary and exit with appropriate code
    print_summary
    exit $?
}

# Run main
main
