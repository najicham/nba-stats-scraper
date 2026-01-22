#!/bin/bash
# Deploy Robustness Improvements to Production Environment
# Part of: Robustness Improvements - Week 7 Deployment
# Created: January 21, 2026
#
# IMPORTANT: This is a gradual rollout script
# Follow the deployment guide carefully and monitor between each step

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ID="${PROJECT_ID:-nba-props-platform}"
ENVIRONMENT="prod"
REGION="us-west1"
SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL_PROD}"

# Deployment phase (passed as argument)
PHASE="${1:-}"

echo -e "${BLUE}=================================="
echo "Robustness Improvements Deployment"
echo "Environment: ${ENVIRONMENT}"
echo "Project: ${PROJECT_ID}"
echo "Deployment Phase: ${PHASE:-NOT_SPECIFIED}"
echo "==================================${NC}"
echo ""

# Function to print section headers
print_section() {
    echo -e "\n${BLUE}[$(date +%H:%M:%S)]${NC} ${GREEN}$1${NC}"
}

# Function to print warnings
print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Function to print errors
print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# Function to print success
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# Function to print critical warnings
print_critical() {
    echo -e "\n${PURPLE}╔════════════════════════════════════════╗${NC}"
    echo -e "${PURPLE}║  CRITICAL: $1${NC}"
    echo -e "${PURPLE}╚════════════════════════════════════════╝${NC}\n"
}

# Function to require confirmation
require_confirmation() {
    echo -e "${YELLOW}"
    read -p "⚠ $1 Are you sure? (type 'YES' to continue): " -r
    echo -e "${NC}"
    if [[ ! $REPLY == "YES" ]]; then
        echo -e "${RED}Deployment cancelled.${NC}"
        exit 1
    fi
}

# Show usage if no phase specified
if [ -z "$PHASE" ]; then
    echo -e "${RED}Error: No deployment phase specified${NC}"
    echo ""
    echo "Usage: $0 <phase>"
    echo ""
    echo "Deployment Phases (must be done in order):"
    echo "  phase1  - Deploy rate limiting only (Week 1)"
    echo "  phase2  - Add validation gates in WARNING mode (Week 2)"
    echo "  phase3  - Enable BLOCKING mode for phase3→4 (Week 3)"
    echo "  phase4  - Deploy self-heal expansion (Week 4)"
    echo "  verify  - Verify all components are deployed correctly"
    echo ""
    echo "Example:"
    echo "  $0 phase1"
    echo "  # Wait 3 days, monitor, then..."
    echo "  $0 phase2"
    echo "  # Wait 3 days, monitor, then..."
    echo "  $0 phase3"
    echo ""
    exit 1
fi

# Pre-flight checks
print_section "Pre-flight Checks"

# Check gcloud authentication
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q "@"; then
    print_error "Not authenticated with gcloud. Run: gcloud auth login"
    exit 1
fi
print_success "Authenticated with gcloud"

# Check project access
if ! gcloud projects describe "$PROJECT_ID" &>/dev/null; then
    print_error "Cannot access project $PROJECT_ID"
    exit 1
fi
print_success "Project $PROJECT_ID accessible"

# Set active project
gcloud config set project "$PROJECT_ID"
print_success "Active project set to $PROJECT_ID"

# Verify staging was successful
print_critical "Have you successfully tested this in staging?"
require_confirmation "Deploying to PRODUCTION without staging verification is dangerous."

# Deploy based on phase
case $PHASE in
    phase1)
        print_section "PHASE 1: Deploy Rate Limiting Only"
        print_warning "Timeline: Week 1 (Monitor for 3 days)"
        echo ""
        require_confirmation "This will update PRODUCTION scrapers with rate limiting."

        # Run tests
        print_section "Running Tests"
        cd "$(dirname "$0")/../../.."
        pytest tests/unit/shared/utils/test_rate_limit_handler.py -v
        pytest tests/unit/shared/config/test_rate_limit_config.py -v

        # Deploy scrapers with rate limiting
        print_section "Deploying Scrapers with Rate Limiting"
        gcloud functions deploy "phase1-scrapers-${ENVIRONMENT}" \
            --gen2 \
            --region="$REGION" \
            --runtime=python312 \
            --source=scrapers \
            --entry-point=main \
            --trigger-http \
            --no-allow-unauthenticated \
            --set-env-vars="RATE_LIMIT_MAX_RETRIES=5,RATE_LIMIT_BASE_BACKOFF=2.0,RATE_LIMIT_MAX_BACKOFF=120.0,RATE_LIMIT_CB_THRESHOLD=10,RATE_LIMIT_CB_TIMEOUT=300,RATE_LIMIT_CB_ENABLED=true,RATE_LIMIT_RETRY_AFTER_ENABLED=true" \
            --timeout=540s \
            --memory=1GB \
            --max-instances=20 \
            --quiet

        print_success "Phase 1 deployed successfully"
        echo ""
        print_section "Monitoring Instructions"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "Monitor for 3 days before proceeding to Phase 2"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        echo "Daily checklist:"
        echo "  □ Check Cloud Logging for rate limit events"
        echo "  □ Verify circuit breaker not over-tripping"
        echo "  □ Confirm 429 errors reduced by >80%"
        echo "  □ Check for any pipeline failures"
        echo ""
        echo "Success criteria:"
        echo "  ✓ No pipeline failures due to rate limiting"
        echo "  ✓ Circuit breaker trips < 5/day"
        echo "  ✓ 429 errors reduced by >80%"
        echo ""
        echo "If successful after 3 days, run: $0 phase2"
        ;;

    phase2)
        print_section "PHASE 2: Add Validation Gates (WARNING Mode)"
        print_warning "Timeline: Week 2 (Monitor for 3 days)"
        echo ""
        require_confirmation "This will enable validation gates in WARNING mode."

        # Run tests
        print_section "Running Tests"
        cd "$(dirname "$0")/../../.."
        pytest tests/unit/shared/validation/test_phase_boundary_validator.py -v

        # Create BigQuery table
        print_section "Creating BigQuery Infrastructure"
        if ! bq show --project_id="$PROJECT_ID" nba_monitoring.phase_boundary_validations &>/dev/null; then
            bq mk \
                --project_id="$PROJECT_ID" \
                --table \
                --time_partitioning_field=game_date \
                --clustering_fields=phase_name,is_valid \
                nba_monitoring.phase_boundary_validations \
                orchestration/bigquery_schemas/phase_boundary_validations_schema.json
            print_success "BigQuery table created"
        else
            print_success "BigQuery table already exists"
        fi

        # Deploy phase transitions with validation
        print_section "Deploying Phase Transitions with Validation"

        # Phase 1→2
        gcloud functions deploy "phase1-to-phase2-${ENVIRONMENT}" \
            --gen2 \
            --region="$REGION" \
            --runtime=python312 \
            --source=orchestration/cloud_functions/phase1_to_phase2 \
            --entry-point=phase1_to_phase2 \
            --trigger-http \
            --no-allow-unauthenticated \
            --set-env-vars="PHASE_VALIDATION_ENABLED=true,PHASE_VALIDATION_MODE=warning" \
            --timeout=540s \
            --quiet

        # Phase 2→3
        gcloud functions deploy "phase2-to-phase3-${ENVIRONMENT}" \
            --gen2 \
            --region="$REGION" \
            --runtime=python312 \
            --source=orchestration/cloud_functions/phase2_to_phase3 \
            --entry-point=phase2_to_phase3 \
            --trigger-http \
            --no-allow-unauthenticated \
            --set-env-vars="PHASE_VALIDATION_ENABLED=true,PHASE_VALIDATION_MODE=warning" \
            --timeout=540s \
            --quiet

        # Phase 3→4 (still WARNING)
        gcloud functions deploy "phase3-to-phase4-${ENVIRONMENT}" \
            --gen2 \
            --region="$REGION" \
            --runtime=python312 \
            --source=orchestration/cloud_functions/phase3_to_phase4 \
            --entry-point=phase3_to_phase4 \
            --trigger-http \
            --no-allow-unauthenticated \
            --set-env-vars="PHASE_VALIDATION_ENABLED=true,PHASE_VALIDATION_MODE=warning" \
            --timeout=540s \
            --quiet

        print_success "Phase 2 deployed successfully"
        echo ""
        print_section "Monitoring Instructions"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "Monitor for 3 days before proceeding to Phase 3"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        echo "Daily checklist:"
        echo "  □ Check BigQuery for validation records"
        echo "  □ Review validation failure rate"
        echo "  □ Identify any false positives"
        echo "  □ Verify game count thresholds are appropriate"
        echo ""
        echo "Success criteria:"
        echo "  ✓ Validation records appearing in BigQuery"
        echo "  ✓ False positive rate < 5%"
        echo "  ✓ Expected issues are being caught"
        echo ""
        echo "If successful after 3 days, run: $0 phase3"
        ;;

    phase3)
        print_section "PHASE 3: Enable BLOCKING Mode for Phase 3→4"
        print_warning "Timeline: Week 3 (Monitor for 7 days)"
        echo ""
        print_critical "This will BLOCK Phase 4 if validation fails!"
        require_confirmation "Enabling BLOCKING mode in production is a critical change."

        # Enable BLOCKING mode for phase3→4 only
        print_section "Enabling BLOCKING Mode"
        gcloud functions deploy "phase3-to-phase4-${ENVIRONMENT}" \
            --gen2 \
            --region="$REGION" \
            --runtime=python312 \
            --source=orchestration/cloud_functions/phase3_to_phase4 \
            --entry-point=phase3_to_phase4 \
            --trigger-http \
            --no-allow-unauthenticated \
            --update-env-vars="PHASE_VALIDATION_MODE=blocking" \
            --timeout=540s \
            --quiet

        print_success "BLOCKING mode enabled for phase3→4"
        echo ""
        print_section "Monitoring Instructions"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "Monitor for 7 days before proceeding to Phase 4"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        echo "Daily checklist:"
        echo "  □ Check for BLOCKING events in BigQuery"
        echo "  □ Verify blocks are legitimate (bad data)"
        echo "  □ Ensure no false positive blocks"
        echo "  □ Confirm alerts sent when blocking occurs"
        echo ""
        echo "Success criteria:"
        echo "  ✓ Bad quality data blocked from Phase 4"
        echo "  ✓ No false positive blocks"
        echo "  ✓ Pipeline continues normally with good data"
        echo ""
        echo "If successful after 7 days, run: $0 phase4"
        ;;

    phase4)
        print_section "PHASE 4: Deploy Self-Heal Expansion"
        print_warning "Timeline: Week 4 (Monitor ongoing)"
        echo ""
        require_confirmation "This will deploy expanded self-heal functionality."

        if [ -z "$SLACK_WEBHOOK_URL" ]; then
            print_error "SLACK_WEBHOOK_URL_PROD not set"
            exit 1
        fi

        # Deploy self-heal
        print_section "Deploying Self-Heal Function"
        gcloud functions deploy "self-heal-check-${ENVIRONMENT}" \
            --gen2 \
            --region="$REGION" \
            --runtime=python312 \
            --source=orchestration/cloud_functions/self_heal \
            --entry-point=self_heal_check \
            --trigger-http \
            --no-allow-unauthenticated \
            --set-env-vars="SLACK_WEBHOOK_URL=$SLACK_WEBHOOK_URL" \
            --timeout=540s \
            --quiet

        print_success "Self-heal deployed successfully"
        echo ""
        print_section "Monitoring Instructions"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "Monitor ongoing"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        echo "Daily checklist:"
        echo "  □ Check Firestore self_heal_history collection"
        echo "  □ Verify Slack alerts being sent"
        echo "  □ Confirm healing operations working"
        echo "  □ Review correlation IDs for tracking"
        echo ""
        echo "Success criteria:"
        echo "  ✓ Phase 2 missing data detected and alerted"
        echo "  ✓ Phase 4 missing data detected and healed"
        echo "  ✓ Slack alerts received"
        echo "  ✓ Firestore logging working"
        echo ""
        print_success "ALL PHASES DEPLOYED!"
        echo ""
        echo "Run verification: $0 verify"
        ;;

    verify)
        print_section "Verifying Deployment"

        # Check BigQuery table
        echo "Checking BigQuery table..."
        if bq show --project_id="$PROJECT_ID" nba_monitoring.phase_boundary_validations &>/dev/null; then
            print_success "BigQuery table exists"

            # Check for recent data
            RECENT_COUNT=$(bq query --project_id="$PROJECT_ID" --use_legacy_sql=false --format=csv \
                "SELECT COUNT(*) as count FROM nba_monitoring.phase_boundary_validations WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)" \
                | tail -n 1)
            if [ "$RECENT_COUNT" -gt 0 ]; then
                print_success "Recent validation records found: $RECENT_COUNT"
            else
                print_warning "No recent validation records (< 24 hours)"
            fi
        else
            print_error "BigQuery table not found"
        fi

        # Check Cloud Functions
        echo ""
        echo "Checking Cloud Functions..."
        FUNCTIONS=(
            "phase1-scrapers-${ENVIRONMENT}"
            "phase1-to-phase2-${ENVIRONMENT}"
            "phase2-to-phase3-${ENVIRONMENT}"
            "phase3-to-phase4-${ENVIRONMENT}"
            "self-heal-check-${ENVIRONMENT}"
        )

        for func in "${FUNCTIONS[@]}"; do
            if gcloud functions describe "$func" --region="$REGION" --gen2 &>/dev/null; then
                print_success "$func deployed"
            else
                print_warning "$func not deployed (may be expected depending on phase)"
            fi
        done

        # Check environment variables
        echo ""
        echo "Checking phase3-to-phase4 validation mode..."
        MODE=$(gcloud functions describe "phase3-to-phase4-${ENVIRONMENT}" --region="$REGION" --gen2 --format="value(serviceConfig.environmentVariables.PHASE_VALIDATION_MODE)" 2>/dev/null || echo "not_set")
        if [ "$MODE" == "blocking" ]; then
            print_success "BLOCKING mode enabled for phase3→4"
        elif [ "$MODE" == "warning" ]; then
            print_warning "Still in WARNING mode (expected if before Phase 3)"
        else
            print_error "Validation mode not set correctly"
        fi

        echo ""
        print_section "Deployment Status Summary"
        echo "View full deployment status in Cloud Console:"
        echo "https://console.cloud.google.com/functions/list?project=$PROJECT_ID"
        ;;

    *)
        print_error "Unknown phase: $PHASE"
        echo "Valid phases: phase1, phase2, phase3, phase4, verify"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}Deployment completed at: $(date)${NC}"
echo ""
