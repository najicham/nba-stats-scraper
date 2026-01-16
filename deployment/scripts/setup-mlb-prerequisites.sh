#!/bin/bash
set -e

# MLB Monitoring Prerequisites Setup Script
# Creates Artifact Registry repositories and verifies permissions

# Configuration
PROJECT_ID="nba-props-platform"
REGION="us-west2"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_info "Setting up MLB monitoring prerequisites..."
log_info "Project: $PROJECT_ID"
log_info "Region: $REGION"

# Check if user is authenticated
log_info "Checking GCP authentication..."
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null | grep -q "@"; then
    log_error "Not authenticated to GCP. Run: gcloud auth login"
    exit 1
fi
log_info "✓ Authenticated"

# Check if project is set
log_info "Verifying project configuration..."
CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null)
if [ "$CURRENT_PROJECT" != "$PROJECT_ID" ]; then
    log_warn "Current project is $CURRENT_PROJECT, expected $PROJECT_ID"
    log_info "Setting project to $PROJECT_ID..."
    gcloud config set project "$PROJECT_ID"
fi
log_info "✓ Project: $PROJECT_ID"

# Check if Docker is configured for Artifact Registry
log_info "Configuring Docker for Artifact Registry..."
if gcloud auth configure-docker us-west2-docker.pkg.dev --quiet; then
    log_info "✓ Docker configured for Artifact Registry"
else
    log_error "Failed to configure Docker"
    exit 1
fi

# Create MLB monitoring repository
log_info "Creating mlb-monitoring Artifact Registry repository..."
if gcloud artifacts repositories describe mlb-monitoring --location="$REGION" &>/dev/null; then
    log_warn "Repository mlb-monitoring already exists"
else
    gcloud artifacts repositories create mlb-monitoring \
        --repository-format=docker \
        --location="$REGION" \
        --description="MLB monitoring Docker images" \
        --quiet
    log_info "✓ Created mlb-monitoring repository"
fi

# Create MLB validators repository
log_info "Creating mlb-validators Artifact Registry repository..."
if gcloud artifacts repositories describe mlb-validators --location="$REGION" &>/dev/null; then
    log_warn "Repository mlb-validators already exists"
else
    gcloud artifacts repositories create mlb-validators \
        --repository-format=docker \
        --location="$REGION" \
        --description="MLB validator Docker images" \
        --quiet
    log_info "✓ Created mlb-validators repository"
fi

# Enable required APIs
log_info "Enabling required Google Cloud APIs..."
APIS=(
    "run.googleapis.com"
    "cloudscheduler.googleapis.com"
    "artifactregistry.googleapis.com"
    "secretmanager.googleapis.com"
)

for api in "${APIS[@]}"; do
    log_info "  - Enabling $api"
    gcloud services enable "$api" --project="$PROJECT_ID" --quiet
done
log_info "✓ APIs enabled"

# Verify Docker is running
log_info "Checking Docker daemon..."
if ! docker info &>/dev/null; then
    log_error "Docker daemon is not running. Please start Docker."
    exit 1
fi
log_info "✓ Docker is running"

# Check if Cloud Scheduler location is available
log_info "Verifying Cloud Scheduler location..."
if gcloud scheduler locations list --format="value(locationId)" 2>/dev/null | grep -q "^$REGION$"; then
    log_info "✓ Cloud Scheduler available in $REGION"
else
    log_warn "Cloud Scheduler may not be available in $REGION"
fi

# Summary
log_info ""
log_info "═══════════════════════════════════════════════════════════"
log_info "  Prerequisites Setup Complete!"
log_info "═══════════════════════════════════════════════════════════"
log_info ""
log_info "Created Resources:"
log_info "  ✓ Artifact Registry repository: mlb-monitoring"
log_info "  ✓ Artifact Registry repository: mlb-validators"
log_info "  ✓ Docker configured for Artifact Registry"
log_info "  ✓ Required APIs enabled"
log_info ""
log_info "You can now run the deployment script:"
log_info "  ./deployment/scripts/deploy-mlb-monitoring.sh --dry-run"
log_info "  ./deployment/scripts/deploy-mlb-monitoring.sh"
log_info ""
