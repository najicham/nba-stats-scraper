#!/usr/bin/env bash
# bin/deployment/fix_workflows_permissions.sh
# Fix Cloud Workflows service agent and permissions issues

set -euo pipefail

PROJECT_ID=$(gcloud config get-value project 2>/dev/null || echo "unknown")
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🔧 Fixing Cloud Workflows Permissions${NC}"
echo "======================================"
echo "Project ID: $PROJECT_ID"
echo "Project Number: $PROJECT_NUMBER"
echo ""

echo -e "${YELLOW}Step 1: Enable Required APIs${NC}"
echo "============================="

# Enable required APIs
apis_to_enable=(
    "workflows.googleapis.com"
    "workflowexecutions.googleapis.com"
    "cloudscheduler.googleapis.com"
    "iam.googleapis.com"
)

for api in "${apis_to_enable[@]}"; do
    echo "Enabling $api..."
    gcloud services enable $api --quiet
done

echo "✅ All required APIs enabled"
echo ""

echo -e "${YELLOW}Step 2: Create Workflows Service Agent${NC}"
echo "======================================"

# The service agent email format
WORKFLOWS_SA_EMAIL="service-${PROJECT_NUMBER}@gcp-sa-workflows.iam.gserviceaccount.com"

echo "Workflows service agent email: $WORKFLOWS_SA_EMAIL"

# Try to create the service agent by granting it a role (this triggers creation)
echo "Creating/configuring Workflows service agent..."

# Grant the service agent the necessary roles
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$WORKFLOWS_SA_EMAIL" \
    --role="roles/workflows.serviceAgent" \
    --quiet

echo "✅ Workflows service agent configured"
echo ""

echo -e "${YELLOW}Step 3: Configure Compute Service Account for Workflows${NC}"
echo "====================================================="

# Grant the default compute service account permission to invoke workflows
COMPUTE_SA_EMAIL="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

echo "Compute service account: $COMPUTE_SA_EMAIL"

# Grant necessary roles to the compute service account
roles_to_grant=(
    "roles/workflows.invoker"
    "roles/logging.logWriter"
    "roles/monitoring.metricWriter"
)

for role in "${roles_to_grant[@]}"; do
    echo "Granting $role to compute service account..."
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:$COMPUTE_SA_EMAIL" \
        --role="$role" \
        --quiet
done

echo "✅ Compute service account configured"
echo ""

echo -e "${YELLOW}Step 4: Wait for Propagation${NC}"
echo "=============================="

echo "Waiting 30 seconds for IAM changes to propagate..."
sleep 30

echo "✅ Permission propagation complete"
echo ""

echo -e "${YELLOW}Step 5: Verify Service Agent${NC}"
echo "============================"

# Check if the service agent exists
if gcloud iam service-accounts describe $WORKFLOWS_SA_EMAIL --quiet >/dev/null 2>&1; then
    echo "✅ Workflows service agent exists and is accessible"
else
    echo "⚠️  Service agent may still be propagating. This is normal for new projects."
    echo "The deployment script should work now, but may take a few more minutes."
fi

echo ""
echo -e "${GREEN}🎉 Permissions Fix Complete!${NC}"
echo "============================="
echo ""
echo "You can now retry the deployment:"
echo "./bin/deployment/deploy_real_time_business.sh"
echo ""
echo "If you still get errors, wait 2-3 minutes and try again."
echo "New projects sometimes take time to fully initialize service agents."