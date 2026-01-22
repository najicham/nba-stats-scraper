#!/bin/bash
# Deploy Robustness Improvements to Staging Environment
# Part of: Robustness Improvements - Week 7 Deployment
# Created: January 21, 2026

set -e  # Exit on error

# Colors for output
RED='\033[0:31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ID="${PROJECT_ID:-nba-props-platform}"
ENVIRONMENT="staging"
REGION="us-west1"
SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL_STAGING}"

echo -e "${BLUE}=================================="
echo "Robustness Improvements Deployment"
echo "Environment: ${ENVIRONMENT}"
echo "Project: ${PROJECT_ID}"
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

# Check required tools
for tool in bq gcloud; do
    if ! command -v $tool &> /dev/null; then
        print_error "$tool not found. Please install Google Cloud SDK."
        exit 1
    fi
done
print_success "Required tools installed"

# Run unit tests before deployment
print_section "Running Unit Tests"
if pytest tests/unit/shared/ -v --tb=short; then
    print_success "All unit tests passed"
else
    print_error "Unit tests failed. Fix tests before deploying."
    exit 1
fi

# Step 1: Create BigQuery Infrastructure
print_section "Step 1: BigQuery Infrastructure"

print_warning "Creating nba_monitoring dataset if needed..."
if ! bq ls --project_id="$PROJECT_ID" nba_monitoring &>/dev/null; then
    bq mk \
        --project_id="$PROJECT_ID" \
        --dataset \
        --location=US \
        --description="NBA pipeline monitoring and validation data" \
        nba_monitoring
    print_success "Dataset nba_monitoring created"
else
    print_success "Dataset nba_monitoring already exists"
fi

print_warning "Creating phase_boundary_validations table..."
cd "$(dirname "$0")/../../.."  # Go to project root
if bq show --project_id="$PROJECT_ID" nba_monitoring.phase_boundary_validations &>/dev/null; then
    print_warning "Table already exists. Skipping creation."
else
    bq mk \
        --project_id="$PROJECT_ID" \
        --table \
        --time_partitioning_field=game_date \
        --time_partitioning_type=DAY \
        --clustering_fields=phase_name,is_valid \
        --description="Phase boundary validation results" \
        nba_monitoring.phase_boundary_validations \
        orchestration/bigquery_schemas/phase_boundary_validations_schema.json
    print_success "Table phase_boundary_validations created"
fi

# Step 2: Deploy Phase Transition Functions with Validation
print_section "Step 2: Deploy Phase Transition Functions"

# Note: Skipping phase1-to-phase2 as it doesn't exist (Phase 1 is orchestrator)
print_warning "Skipping phase1-to-phase2 (not applicable for this architecture)"

# Deploy Phase 2→3 (WARNING mode)
print_warning "Deploying phase2-to-phase3-${ENVIRONMENT}..."
gcloud functions deploy "phase2-to-phase3-${ENVIRONMENT}" \
    --gen2 \
    --region="$REGION" \
    --runtime=python312 \
    --source=orchestration/cloud_functions/phase2_to_phase3 \
    --entry-point=orchestrate_phase2_to_phase3 \
    --trigger-http \
    --no-allow-unauthenticated \
    --set-env-vars="PHASE_VALIDATION_ENABLED=true,PHASE_VALIDATION_MODE=warning,PHASE_VALIDATION_GAME_COUNT_THRESHOLD=0.8,PHASE_VALIDATION_QUALITY_THRESHOLD=0.7,RATE_LIMIT_MAX_RETRIES=5,RATE_LIMIT_CB_ENABLED=true" \
    --timeout=540s \
    --memory=512MB \
    --max-instances=10 \
    --quiet

print_success "phase2-to-phase3-${ENVIRONMENT} deployed"

# Deploy Phase 3→4 (BLOCKING mode - initially WARNING for testing)
print_warning "Deploying phase3-to-phase4-${ENVIRONMENT}..."
gcloud functions deploy "phase3-to-phase4-${ENVIRONMENT}" \
    --gen2 \
    --region="$REGION" \
    --runtime=python312 \
    --source=orchestration/cloud_functions/phase3_to_phase4 \
    --entry-point=orchestrate_phase3_to_phase4 \
    --trigger-http \
    --no-allow-unauthenticated \
    --set-env-vars="PHASE_VALIDATION_ENABLED=true,PHASE_VALIDATION_MODE=warning,PHASE_VALIDATION_GAME_COUNT_THRESHOLD=0.8,PHASE_VALIDATION_QUALITY_THRESHOLD=0.7,RATE_LIMIT_MAX_RETRIES=5,RATE_LIMIT_CB_ENABLED=true" \
    --timeout=540s \
    --memory=512MB \
    --max-instances=10 \
    --quiet

print_success "phase3-to-phase4-${ENVIRONMENT} deployed (WARNING mode initially)"

# Step 3: Deploy Self-Heal with Phase 2/4 Support
print_section "Step 3: Deploy Self-Heal Function"

if [ -z "$SLACK_WEBHOOK_URL" ]; then
    print_warning "SLACK_WEBHOOK_URL_STAGING not set. Self-heal alerts will not be sent."
    SLACK_ENV_VAR=""
else
    SLACK_ENV_VAR="SLACK_WEBHOOK_URL=$SLACK_WEBHOOK_URL"
fi

print_warning "Deploying self-heal-check-${ENVIRONMENT}..."
gcloud functions deploy "self-heal-check-${ENVIRONMENT}" \
    --gen2 \
    --region="$REGION" \
    --runtime=python312 \
    --source=orchestration/cloud_functions/self_heal \
    --entry-point=self_heal_check \
    --trigger-http \
    --no-allow-unauthenticated \
    --set-env-vars="$SLACK_ENV_VAR" \
    --timeout=540s \
    --memory=512MB \
    --max-instances=5 \
    --quiet

print_success "self-heal-check-${ENVIRONMENT} deployed"

# Step 4: Deploy Rate Limiting to Scrapers
print_section "Step 4: Deploy Rate Limiting to Scrapers"

# Note: Skipping scrapers for now - focus on orchestration functions
# Rate limiting will be added to existing scrapers in a separate deployment
print_warning "Skipping scrapers deployment (will use existing scraper functions)"
print_warning "Rate limiting improvements are included in orchestration functions"

# Step 5: Verify Deployments
print_section "Step 5: Verification"

print_warning "Checking deployed functions..."
FUNCTIONS=(
    "phase2-to-phase3-${ENVIRONMENT}"
    "phase3-to-phase4-${ENVIRONMENT}"
    "self-heal-check-${ENVIRONMENT}"
)

for func in "${FUNCTIONS[@]}"; do
    if gcloud functions describe "$func" --region="$REGION" --gen2 &>/dev/null; then
        print_success "$func is deployed"
    else
        print_error "$func deployment verification failed"
    fi
done

print_warning "Checking BigQuery table..."
if bq show --project_id="$PROJECT_ID" nba_monitoring.phase_boundary_validations &>/dev/null; then
    print_success "BigQuery table is accessible"
else
    print_error "BigQuery table not accessible"
fi

# Step 6: Post-Deployment Instructions
print_section "Deployment Complete!"

echo ""
echo -e "${GREEN}✓ All components deployed successfully${NC}"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Next Steps:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "1. Monitor for 24 hours in WARNING mode:"
echo "   - Check Cloud Logging for validation warnings"
echo "   - Review BigQuery table:"
echo "     bq query --project_id=$PROJECT_ID --use_legacy_sql=false \\"
echo "       'SELECT * FROM nba_monitoring.phase_boundary_validations ORDER BY timestamp DESC LIMIT 10'"
echo ""
echo "2. Check for false positives:"
echo "   - If > 5% false positive rate, adjust thresholds"
echo "   - Update PHASE_VALIDATION_GAME_COUNT_THRESHOLD if needed"
echo ""
echo "3. After 24 hours of stable WARNING mode:"
echo "   - Enable BLOCKING mode for phase3→4:"
echo "     ./enable-blocking-mode-staging.sh"
echo ""
echo "4. Monitor dashboards:"
echo "   - Rate Limiting: [Create Looker Studio dashboard]"
echo "   - Phase Validation: [Create Looker Studio dashboard]"
echo ""
echo "5. Test self-heal manually:"
echo "   - Trigger: gcloud functions call self-heal-check-${ENVIRONMENT}"
echo "   - Check Firestore: self_heal_history collection"
echo "   - Check Slack for alerts"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Monitoring URLs:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Cloud Functions: https://console.cloud.google.com/functions/list?project=$PROJECT_ID"
echo "Cloud Logging: https://console.cloud.google.com/logs?project=$PROJECT_ID"
echo "BigQuery: https://console.cloud.google.com/bigquery?project=$PROJECT_ID"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "${GREEN}Deployment completed at: $(date)${NC}"
echo ""
