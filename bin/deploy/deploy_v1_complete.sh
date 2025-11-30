#!/bin/bash
# Master Deployment Script for NBA Props Platform v1.0
#
# This script deploys the complete event-driven pipeline:
# - Phase 1-2: Scrapers + Raw processors (already deployed)
# - Phase 2→3 Orchestrator: Cloud Function
# - Phase 3: Analytics processors (already deployed)
# - Phase 3→4 Orchestrator: Cloud Function
# - Phase 4: Precompute processors (already deployed)
# - Phase 5: Prediction coordinator
#
# Usage:
#   ./bin/deploy/deploy_v1_complete.sh [--skip-infrastructure] [--skip-orchestrators] [--skip-phase5]
#
# Options:
#   --skip-infrastructure  Skip Pub/Sub topic creation
#   --skip-orchestrators   Skip orchestrator deployment
#   --skip-phase5         Skip Phase 5 coordinator deployment
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - Docker installed (for Phase 5)
#   - All code tested locally (47/47 tests passing)

set -e  # Exit on error

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

# Configuration
PROJECT_ID="nba-props-platform"
REGION="us-west2"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Parse arguments
SKIP_INFRASTRUCTURE=false
SKIP_ORCHESTRATORS=false
SKIP_PHASE5=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-infrastructure)
            SKIP_INFRASTRUCTURE=true
            shift
            ;;
        --skip-orchestrators)
            SKIP_ORCHESTRATORS=true
            shift
            ;;
        --skip-phase5)
            SKIP_PHASE5=true
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Usage: $0 [--skip-infrastructure] [--skip-orchestrators] [--skip-phase5]"
            exit 1
            ;;
    esac
done

# ============================================================================
# Helper Functions
# ============================================================================

log() {
    echo -e "${CYAN}[$(date +'%H:%M:%S')]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[$(date +'%H:%M:%S')] ✓${NC} $*"
}

log_warning() {
    echo -e "${YELLOW}[$(date +'%H:%M:%S')] ⚠${NC} $*"
}

log_error() {
    echo -e "${RED}[$(date +'%H:%M:%S')] ✗${NC} $*" >&2
}

log_section() {
    echo ""
    echo -e "${MAGENTA}========================================${NC}"
    echo -e "${MAGENTA}$*${NC}"
    echo -e "${MAGENTA}========================================${NC}"
}

check_prerequisites() {
    log_section "Checking Prerequisites"

    # Check gcloud
    if ! command -v gcloud &> /dev/null; then
        log_error "gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
        exit 1
    fi
    log_success "gcloud CLI installed"

    # Check authentication
    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
        log_error "Not authenticated with gcloud. Run: gcloud auth login"
        exit 1
    fi
    log_success "Authenticated with gcloud"

    # Check project access
    if ! gcloud projects describe "$PROJECT_ID" &> /dev/null; then
        log_error "Cannot access project: $PROJECT_ID"
        exit 1
    fi
    log_success "Project access verified: $PROJECT_ID"

    # Set active project
    CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null)
    if [ "$CURRENT_PROJECT" != "$PROJECT_ID" ]; then
        log "Setting active project to $PROJECT_ID"
        gcloud config set project $PROJECT_ID
    fi

    # Check if Docker is needed (for Phase 5)
    if [ "$SKIP_PHASE5" = false ]; then
        if ! command -v docker &> /dev/null; then
            log_error "Docker not found. Install: https://docs.docker.com/get-docker/"
            exit 1
        fi
        log_success "Docker installed"
    fi

    # Check if we're in project root
    if [ ! -f "$PROJECT_ROOT/orchestrators/phase2_to_phase3/main.py" ]; then
        log_error "Not in project root directory. Run from: nba-stats-scraper/"
        exit 1
    fi
    log_success "Project root verified"

    echo ""
    log_success "All prerequisites met!"
}

# ============================================================================
# Deployment Steps
# ============================================================================

deploy_infrastructure() {
    if [ "$SKIP_INFRASTRUCTURE" = true ]; then
        log_warning "Skipping infrastructure deployment (--skip-infrastructure)"
        return
    fi

    log_section "Step 1: Deploy Infrastructure (Pub/Sub Topics)"

    cd "$PROJECT_ROOT"

    log "Creating Pub/Sub topics..."
    if [ -f "bin/pubsub/create_topics.sh" ]; then
        bash bin/pubsub/create_topics.sh
        log_success "Pub/Sub topics created"
    else
        log_error "Pub/Sub creation script not found: bin/pubsub/create_topics.sh"
        exit 1
    fi

    log "Checking Firestore initialization..."
    if gcloud firestore databases list --project=$PROJECT_ID &>/dev/null; then
        log_success "Firestore initialized"
    else
        log_warning "Cannot verify Firestore - ensure it's initialized in GCP console"
        log_warning "Visit: https://console.firebase.google.com/project/$PROJECT_ID/firestore"
    fi
}

deploy_phase2_to_phase3_orchestrator() {
    if [ "$SKIP_ORCHESTRATORS" = true ]; then
        log_warning "Skipping orchestrator deployment (--skip-orchestrators)"
        return
    fi

    log_section "Step 2: Deploy Phase 2→3 Orchestrator"

    cd "$PROJECT_ROOT"

    if [ ! -f "bin/orchestrators/deploy_phase2_to_phase3.sh" ]; then
        log_error "Deployment script not found: bin/orchestrators/deploy_phase2_to_phase3.sh"
        exit 1
    fi

    log "Deploying Phase 2→3 orchestrator Cloud Function..."
    bash bin/orchestrators/deploy_phase2_to_phase3.sh

    log_success "Phase 2→3 orchestrator deployed"
}

deploy_phase3_to_phase4_orchestrator() {
    if [ "$SKIP_ORCHESTRATORS" = true ]; then
        log_warning "Skipping orchestrator deployment (--skip-orchestrators)"
        return
    fi

    log_section "Step 3: Deploy Phase 3→4 Orchestrator"

    cd "$PROJECT_ROOT"

    if [ ! -f "bin/orchestrators/deploy_phase3_to_phase4.sh" ]; then
        log_error "Deployment script not found: bin/orchestrators/deploy_phase3_to_phase4.sh"
        exit 1
    fi

    log "Deploying Phase 3→4 orchestrator Cloud Function..."
    bash bin/orchestrators/deploy_phase3_to_phase4.sh

    log_success "Phase 3→4 orchestrator deployed"
}

deploy_phase5_coordinator() {
    if [ "$SKIP_PHASE5" = true ]; then
        log_warning "Skipping Phase 5 deployment (--skip-phase5)"
        return
    fi

    log_section "Step 4: Deploy Phase 5 Prediction Coordinator"

    cd "$PROJECT_ROOT"

    if [ ! -f "bin/predictions/deploy/deploy_prediction_coordinator.sh" ]; then
        log_error "Deployment script not found: bin/predictions/deploy/deploy_prediction_coordinator.sh"
        exit 1
    fi

    log "Deploying Phase 5 prediction coordinator to Cloud Run..."
    bash bin/predictions/deploy/deploy_prediction_coordinator.sh prod

    log_success "Phase 5 coordinator deployed"
}

verify_deployments() {
    log_section "Step 5: Verify Deployments"

    log "Checking Phase 2→3 orchestrator..."
    if gcloud functions describe phase2-to-phase3-orchestrator \
        --region $REGION \
        --gen2 \
        --project $PROJECT_ID \
        --format="value(state)" 2>/dev/null | grep -q "ACTIVE"; then
        log_success "Phase 2→3 orchestrator is ACTIVE"
    else
        log_warning "Phase 2→3 orchestrator not found or not active"
    fi

    log "Checking Phase 3→4 orchestrator..."
    if gcloud functions describe phase3-to-phase4-orchestrator \
        --region $REGION \
        --gen2 \
        --project $PROJECT_ID \
        --format="value(state)" 2>/dev/null | grep -q "ACTIVE"; then
        log_success "Phase 3→4 orchestrator is ACTIVE"
    else
        log_warning "Phase 3→4 orchestrator not found or not active"
    fi

    log "Checking Phase 5 coordinator..."
    if gcloud run services describe prediction-coordinator \
        --region $REGION \
        --project $PROJECT_ID \
        --format="value(status.url)" 2>/dev/null | grep -q "https://"; then
        COORDINATOR_URL=$(gcloud run services describe prediction-coordinator \
            --region $REGION \
            --project $PROJECT_ID \
            --format="value(status.url)")
        log_success "Phase 5 coordinator is deployed: $COORDINATOR_URL"
    else
        log_warning "Phase 5 coordinator not found"
    fi
}

show_deployment_summary() {
    log_section "Deployment Summary"

    echo ""
    echo -e "${BLUE}Project:${NC} $PROJECT_ID"
    echo -e "${BLUE}Region:${NC} $REGION"
    echo ""

    echo -e "${GREEN}✓ Deployed Components:${NC}"
    echo "  1. Pub/Sub Topics"
    echo "     - nba-phase2-raw-complete"
    echo "     - nba-phase3-trigger"
    echo "     - nba-phase3-analytics-complete"
    echo "     - nba-phase4-trigger"
    echo "     - nba-phase4-precompute-complete"
    echo "     - nba-phase5-predictions-complete"
    echo ""
    echo "  2. Phase 2→3 Orchestrator (Cloud Function)"
    echo "     - Tracks 21 Phase 2 processors"
    echo "     - Firestore: phase2_completion/{game_date}"
    echo ""
    echo "  3. Phase 3→4 Orchestrator (Cloud Function)"
    echo "     - Tracks 5 Phase 3 processors"
    echo "     - Firestore: phase3_completion/{analysis_date}"
    echo ""
    echo "  4. Phase 5 Prediction Coordinator (Cloud Run)"
    COORDINATOR_URL=$(gcloud run services describe prediction-coordinator \
        --region $REGION \
        --project $PROJECT_ID \
        --format="value(status.url)" 2>/dev/null || echo "Not deployed")
    echo "     - URL: $COORDINATOR_URL"
    echo ""

    echo -e "${CYAN}📊 Event Flow:${NC}"
    echo "  Phase 1 Scrapers → nba-phase1-scrape-complete"
    echo "  Phase 2 Processors → nba-phase2-raw-complete"
    echo "  Phase 2→3 Orchestrator → nba-phase3-trigger"
    echo "  Phase 3 Analytics → nba-phase3-analytics-complete"
    echo "  Phase 3→4 Orchestrator → nba-phase4-trigger"
    echo "  Phase 4 Precompute → nba-phase4-precompute-complete"
    echo "  Phase 5 Coordinator → Predictions!"
    echo ""

    echo -e "${YELLOW}📖 Next Steps:${NC}"
    echo "  1. Test end-to-end pipeline:"
    echo "     ${BLUE}./bin/deploy/verify_deployment.sh${NC}"
    echo ""
    echo "  2. View orchestrator logs:"
    echo "     ${BLUE}gcloud functions logs read phase2-to-phase3-orchestrator --region $REGION --limit 50${NC}"
    echo "     ${BLUE}gcloud functions logs read phase3-to-phase4-orchestrator --region $REGION --limit 50${NC}"
    echo ""
    echo "  3. View coordinator logs:"
    echo "     ${BLUE}gcloud run services logs read prediction-coordinator --region $REGION --limit 50${NC}"
    echo ""
    echo "  4. Monitor Firestore state:"
    echo "     ${BLUE}https://console.firebase.google.com/project/$PROJECT_ID/firestore${NC}"
    echo ""
    echo "  5. Test Phase 5 manually:"
    echo "     ${BLUE}curl -X POST $COORDINATOR_URL/start -H 'Content-Type: application/json' -d '{\"game_date\":\"2025-11-29\"}'${NC}"
    echo ""
}

# ============================================================================
# Main
# ============================================================================

main() {
    log_section "NBA Props Platform v1.0 - Complete Deployment"

    echo ""
    echo -e "${CYAN}This script will deploy:${NC}"
    echo "  ✓ Pub/Sub topics (infrastructure)"
    echo "  ✓ Phase 2→3 Orchestrator (Cloud Function)"
    echo "  ✓ Phase 3→4 Orchestrator (Cloud Function)"
    echo "  ✓ Phase 5 Prediction Coordinator (Cloud Run)"
    echo ""
    echo -e "${YELLOW}Project:${NC} $PROJECT_ID"
    echo -e "${YELLOW}Region:${NC} $REGION"
    echo ""

    read -p "Continue with deployment? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log "Deployment cancelled"
        exit 0
    fi

    echo ""
    log "Starting deployment..."

    # Run deployment steps
    check_prerequisites
    deploy_infrastructure
    deploy_phase2_to_phase3_orchestrator
    deploy_phase3_to_phase4_orchestrator
    deploy_phase5_coordinator
    verify_deployments
    show_deployment_summary

    echo ""
    log_success "Deployment complete! 🚀"
    echo ""
}

# Run main
cd "$PROJECT_ROOT"
main
