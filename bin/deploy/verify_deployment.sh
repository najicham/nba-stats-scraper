#!/bin/bash
# Verify NBA Props Platform v1.0 Deployment
#
# This script verifies that all components are deployed and healthy:
# - Pub/Sub topics exist
# - Cloud Functions are active
# - Cloud Run services are running
# - Firestore is initialized
#
# Usage:
#   ./bin/deploy/verify_deployment.sh

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configuration
PROJECT_ID="nba-props-platform"
REGION="us-west2"

# Counters
TOTAL_CHECKS=0
PASSED_CHECKS=0
FAILED_CHECKS=0

# ============================================================================
# Helper Functions
# ============================================================================

log() {
    echo -e "${CYAN}$*${NC}"
}

log_success() {
    echo -e "${GREEN}✓${NC} $*"
    ((PASSED_CHECKS++))
}

log_fail() {
    echo -e "${RED}✗${NC} $*"
    ((FAILED_CHECKS++))
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $*"
}

log_section() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$*${NC}"
    echo -e "${BLUE}========================================${NC}"
}

check_item() {
    ((TOTAL_CHECKS++))
}

# ============================================================================
# Verification Checks
# ============================================================================

verify_authentication() {
    log_section "Authentication & Project Access"

    check_item
    if gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
        ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)")
        log_success "Authenticated as: $ACCOUNT"
    else
        log_fail "Not authenticated with gcloud"
        return 1
    fi

    check_item
    CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null)
    if [ "$CURRENT_PROJECT" = "$PROJECT_ID" ]; then
        log_success "Active project: $PROJECT_ID"
    else
        log_warning "Active project is $CURRENT_PROJECT (expected: $PROJECT_ID)"
        gcloud config set project $PROJECT_ID
    fi
}

verify_pubsub_topics() {
    log_section "Pub/Sub Topics"

    REQUIRED_TOPICS=(
        "nba-phase1-scrapers-complete"
        "nba-phase2-raw-complete"
        "nba-phase3-trigger"
        "nba-phase3-analytics-complete"
        "nba-phase4-trigger"
        "nba-phase4-processor-complete"
        "nba-phase4-precompute-complete"
        "nba-phase5-predictions-complete"
    )

    for topic in "${REQUIRED_TOPICS[@]}"; do
        check_item
        if gcloud pubsub topics describe "$topic" --project=$PROJECT_ID &>/dev/null; then
            log_success "Topic exists: $topic"
        else
            log_fail "Topic missing: $topic"
        fi
    done
}

verify_cloud_functions() {
    log_section "Cloud Functions (Orchestrators)"

    # Phase 2→3 Orchestrator
    check_item
    if gcloud functions describe phase2-to-phase3-orchestrator \
        --region $REGION \
        --gen2 \
        --project $PROJECT_ID \
        --format="value(state)" 2>/dev/null | grep -q "ACTIVE"; then
        log_success "Phase 2→3 orchestrator: ACTIVE"
    else
        log_fail "Phase 2→3 orchestrator: NOT FOUND or INACTIVE"
    fi

    # Phase 3→4 Orchestrator
    check_item
    if gcloud functions describe phase3-to-phase4-orchestrator \
        --region $REGION \
        --gen2 \
        --project $PROJECT_ID \
        --format="value(state)" 2>/dev/null | grep -q "ACTIVE"; then
        log_success "Phase 3→4 orchestrator: ACTIVE"
    else
        log_fail "Phase 3→4 orchestrator: NOT FOUND or INACTIVE"
    fi
}

verify_cloud_run() {
    log_section "Cloud Run Services"

    # Phase 5 Prediction Coordinator
    check_item
    if gcloud run services describe prediction-coordinator \
        --region $REGION \
        --project $PROJECT_ID \
        --format="value(status.url)" 2>/dev/null | grep -q "https://"; then
        COORDINATOR_URL=$(gcloud run services describe prediction-coordinator \
            --region $REGION \
            --project $PROJECT_ID \
            --format="value(status.url)")
        log_success "Prediction coordinator: DEPLOYED"
        echo "     URL: $COORDINATOR_URL"
    else
        log_fail "Prediction coordinator: NOT FOUND"
    fi
}

verify_firestore() {
    log_section "Firestore Database"

    check_item
    if gcloud firestore databases list --project=$PROJECT_ID &>/dev/null; then
        log_success "Firestore: INITIALIZED"

        # Check if orchestrator collections exist (optional - they'll be created on first run)
        log "     Collections will be created on first orchestrator run:"
        log "     - phase2_completion/{game_date}"
        log "     - phase3_completion/{analysis_date}"
    else
        log_fail "Firestore: NOT INITIALIZED"
        log "     Initialize at: https://console.firebase.google.com/project/$PROJECT_ID/firestore"
    fi
}

verify_iam_permissions() {
    log_section "IAM Permissions (Basic Check)"

    # Check if we can list Cloud Functions (indicates proper permissions)
    check_item
    if gcloud functions list --region $REGION --project $PROJECT_ID &>/dev/null; then
        log_success "Can list Cloud Functions (sufficient permissions)"
    else
        log_fail "Cannot list Cloud Functions (permission issues)"
    fi

    # Check if we can list Cloud Run services
    check_item
    if gcloud run services list --region $REGION --project $PROJECT_ID &>/dev/null; then
        log_success "Can list Cloud Run services (sufficient permissions)"
    else
        log_fail "Cannot list Cloud Run services (permission issues)"
    fi
}

show_pipeline_status() {
    log_section "Pipeline Status Summary"

    echo ""
    echo -e "${CYAN}Event-Driven Pipeline:${NC}"
    echo ""
    echo "  Phase 1: Scrapers"
    echo "    ↓ Pub/Sub: nba-phase1-scrape-complete"
    echo "  Phase 2: Raw Processors (21 processors)"
    echo "    ↓ Pub/Sub: nba-phase2-raw-complete"
    echo "  Phase 2→3: Orchestrator (Cloud Function)"
    echo "    ↓ Pub/Sub: nba-phase3-trigger"
    echo "  Phase 3: Analytics (5 processors)"
    echo "    ↓ Pub/Sub: nba-phase3-analytics-complete"
    echo "  Phase 3→4: Orchestrator (Cloud Function)"
    echo "    ↓ Pub/Sub: nba-phase4-trigger"
    echo "  Phase 4: Precompute (5 processors)"
    echo "    ↓ Pub/Sub: nba-phase4-precompute-complete"
    echo "  Phase 5: Prediction Coordinator (Cloud Run)"
    echo "    ↓ Predictions Generated!"
    echo ""
}

show_test_commands() {
    log_section "Next Steps: Testing"

    COORDINATOR_URL=$(gcloud run services describe prediction-coordinator \
        --region $REGION \
        --project $PROJECT_ID \
        --format="value(status.url)" 2>/dev/null || echo "NOT_DEPLOYED")

    echo ""
    echo -e "${YELLOW}1. Test Phase 5 Coordinator Manually:${NC}"
    if [ "$COORDINATOR_URL" != "NOT_DEPLOYED" ]; then
        echo "   ${BLUE}curl -X POST $COORDINATOR_URL/start \\${NC}"
        echo "   ${BLUE}  -H 'Content-Type: application/json' \\${NC}"
        echo "   ${BLUE}  -d '{\"game_date\":\"2025-11-29\"}'${NC}"
    else
        echo "   ${RED}Coordinator not deployed${NC}"
    fi
    echo ""

    echo -e "${YELLOW}2. View Orchestrator Logs:${NC}"
    echo "   ${BLUE}# Phase 2→3${NC}"
    echo "   ${BLUE}gcloud functions logs read phase2-to-phase3-orchestrator \\${NC}"
    echo "   ${BLUE}     --region $REGION --limit 50${NC}"
    echo ""
    echo "   ${BLUE}# Phase 3→4${NC}"
    echo "   ${BLUE}gcloud functions logs read phase3-to-phase4-orchestrator \\${NC}"
    echo "   ${BLUE}     --region $REGION --limit 50${NC}"
    echo ""

    echo -e "${YELLOW}3. View Coordinator Logs:${NC}"
    echo "   ${BLUE}gcloud run services logs read prediction-coordinator \\${NC}"
    echo "   ${BLUE}     --region $REGION --limit 50${NC}"
    echo ""

    echo -e "${YELLOW}4. Monitor Firestore State:${NC}"
    echo "   ${BLUE}https://console.firebase.google.com/project/$PROJECT_ID/firestore/data${NC}"
    echo ""

    echo -e "${YELLOW}5. Trigger End-to-End Test:${NC}"
    echo "   - Manually trigger a Phase 1 scraper for today's date"
    echo "   - Watch the correlation_id flow through all phases"
    echo "   - Verify predictions are generated"
    echo ""
}

show_summary() {
    log_section "Verification Summary"

    echo ""
    echo -e "${CYAN}Results:${NC}"
    echo "  Total Checks:  $TOTAL_CHECKS"
    echo -e "  ${GREEN}Passed:        $PASSED_CHECKS${NC}"
    echo -e "  ${RED}Failed:        $FAILED_CHECKS${NC}"
    echo ""

    if [ $FAILED_CHECKS -eq 0 ]; then
        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}✓ All checks passed!${NC}"
        echo -e "${GREEN}✓ v1.0 deployment verified${NC}"
        echo -e "${GREEN}========================================${NC}"
        return 0
    else
        echo -e "${RED}========================================${NC}"
        echo -e "${RED}✗ $FAILED_CHECKS check(s) failed${NC}"
        echo -e "${RED}✗ Review errors above${NC}"
        echo -e "${RED}========================================${NC}"
        return 1
    fi
}

# ============================================================================
# Main
# ============================================================================

main() {
    log_section "NBA Props Platform v1.0 - Deployment Verification"

    verify_authentication
    verify_pubsub_topics
    verify_cloud_functions
    verify_cloud_run
    verify_firestore
    verify_iam_permissions
    show_pipeline_status
    show_test_commands
    show_summary
}

# Run main
main
