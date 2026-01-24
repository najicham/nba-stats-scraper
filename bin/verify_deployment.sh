#!/bin/bash
#
# Deployment Verification Script
#
# Verifies all required infrastructure exists after deployment.
# Prevents "deployed but not verified" issues that caused Week 0 incidents.
#
# Usage:
#   ./bin/verify_deployment.sh
#   ./bin/verify_deployment.sh --quick  # Skip API checks (faster)
#
# Exit codes:
#   0 = All checks passed
#   1 = One or more checks failed
#
# Examples:
#   # In CI/CD pipeline
#   bin/verify_deployment.sh || exit 1
#
#   # Before marking deployment complete
#   bin/verify_deployment.sh && echo "Deployment verified!"
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Counters
CHECKS_PASSED=0
CHECKS_FAILED=0

# Functions
check_passed() {
    echo -e "  ${GREEN}✅${NC} $1"
    ((CHECKS_PASSED++))
}

check_failed() {
    echo -e "  ${RED}❌ ERROR${NC}: $1"
    ((CHECKS_FAILED++))
}

check_warning() {
    echo -e "  ${YELLOW}⚠️  WARNING${NC}: $1"
}

# Parse arguments
QUICK_MODE=false
if [[ "$1" == "--quick" ]]; then
    QUICK_MODE=true
fi

echo "🔍 Verifying NBA Props Platform Deployment..."
echo ""

# ============================================================================
# CHECK 1: Cloud Schedulers
# ============================================================================
echo "📅 Checking Cloud Schedulers..."

EXPECTED_SCHEDULERS=(
    "grading-readiness-monitor"
    "grading-backup-6am"
    "grading-backup-10am"
    "box-score-completeness-alert"
    "phase4-failure-alert"
)

for scheduler in "${EXPECTED_SCHEDULERS[@]}"; do
    if gcloud scheduler jobs describe "$scheduler" --location=us-central1 >/dev/null 2>&1; then
        check_passed "$scheduler"
    else
        check_failed "Scheduler '$scheduler' not found in us-central1"
    fi
done

echo ""

# ============================================================================
# CHECK 2: Cloud Functions (Gen2)
# ============================================================================
echo "⚡ Checking Cloud Functions..."

EXPECTED_FUNCTIONS=(
    "box-score-completeness-alert"
    "phase4-failure-alert"
    "grading-readiness-monitor"
)

for func in "${EXPECTED_FUNCTIONS[@]}"; do
    if gcloud functions describe "$func" --gen2 --region=us-west1 >/dev/null 2>&1; then
        check_passed "$func"
    else
        check_failed "Function '$func' not found in us-west1"
    fi
done

echo ""

# ============================================================================
# CHECK 3: BigQuery Datasets
# ============================================================================
echo "💾 Checking BigQuery Datasets..."

EXPECTED_DATASETS=(
    "nba_raw"
    "nba_analytics"
    "nba_precompute"
    "nba_predictions"
    "nba_monitoring"
)

for dataset in "${EXPECTED_DATASETS[@]}"; do
    if bq show "$dataset" >/dev/null 2>&1; then
        check_passed "$dataset"
    else
        check_failed "Dataset '$dataset' not found"
    fi
done

echo ""

# ============================================================================
# CHECK 4: Critical BigQuery Tables
# ============================================================================
echo "📊 Checking Critical BigQuery Tables..."

EXPECTED_TABLES=(
    "nba_raw.nbac_schedule"
    "nba_raw.bdl_player_boxscores"
    "nba_analytics.player_game_summary"
    "nba_precompute.player_daily_cache"
    "nba_predictions.player_prop_predictions"
    "nba_predictions.prediction_grades"
)

for table in "${EXPECTED_TABLES[@]}"; do
    if bq show "$table" >/dev/null 2>&1; then
        check_passed "$table"
    else
        check_failed "Table '$table' not found"
    fi
done

echo ""

# ============================================================================
# CHECK 5: APIs Enabled (skip in quick mode)
# ============================================================================
if [[ "$QUICK_MODE" == false ]]; then
    echo "🔌 Checking Required APIs..."

    EXPECTED_APIS=(
        "bigquery.googleapis.com"
        "bigquerydatatransfer.googleapis.com"
        "cloudscheduler.googleapis.com"
        "cloudfunctions.googleapis.com"
        "cloudrun.googleapis.com"
        "pubsub.googleapis.com"
    )

    for api in "${EXPECTED_APIS[@]}"; do
        if gcloud services list --enabled 2>/dev/null | grep -q "$api"; then
            check_passed "$api"
        else
            check_failed "API '$api' not enabled"
        fi
    done

    echo ""
else
    check_warning "Skipping API checks (--quick mode)"
    echo ""
fi

# ============================================================================
# CHECK 6: Pub/Sub Topics
# ============================================================================
echo "📬 Checking Pub/Sub Topics..."

EXPECTED_TOPICS=(
    "grading-trigger"
    "phase4-complete"
)

for topic in "${EXPECTED_TOPICS[@]}"; do
    if gcloud pubsub topics describe "$topic" >/dev/null 2>&1; then
        check_passed "$topic"
    else
        check_warning "Topic '$topic' not found (may be optional)"
    fi
done

echo ""

# ============================================================================
# CHECK 7: Environment Variables (Sample Function)
# ============================================================================
echo "🔧 Checking Environment Variables..."

# Check if box-score alert has Slack webhook configured
if gcloud functions describe box-score-completeness-alert --gen2 --region=us-west1 2>/dev/null | grep -q "SLACK_WEBHOOK"; then
    check_passed "SLACK_WEBHOOK configured in box-score alert"
else
    check_warning "SLACK_WEBHOOK may not be configured in box-score alert"
fi

echo ""

# ============================================================================
# SUMMARY
# ============================================================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "DEPLOYMENT VERIFICATION SUMMARY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

TOTAL_CHECKS=$((CHECKS_PASSED + CHECKS_FAILED))

echo ""
if [[ $CHECKS_FAILED -eq 0 ]]; then
    echo -e "${GREEN}✅ ALL CHECKS PASSED${NC} ($CHECKS_PASSED/$TOTAL_CHECKS)"
    echo ""
    echo "Deployment verified successfully!"
    echo ""
    exit 0
else
    echo -e "${RED}❌ SOME CHECKS FAILED${NC} (Passed: $CHECKS_PASSED, Failed: $CHECKS_FAILED)"
    echo ""
    echo "Please fix the errors above before marking deployment complete."
    echo ""
    echo "Common fixes:"
    echo "  - Missing schedulers: Run deployment script again"
    echo "  - Missing functions: Check Cloud Build logs"
    echo "  - Missing APIs: Run 'gcloud services enable <API_NAME>'"
    echo "  - Missing tables: Run database migration scripts"
    echo ""
    exit 1
fi
