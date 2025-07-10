#!/bin/bash
# bin/deploy_all_services.sh
# Master deployment script for all NBA platform services

set -e

# Configuration
PROJECT_ID=${1:-$(gcloud config get-value project)}
REGION=${2:-"us-central1"}
DEPLOY_SERVICES=${3:-"false"}

echo "🏀 NBA Platform Deployment"
echo "================================"
echo "Project: $PROJECT_ID"
echo "Region: $REGION" 
echo "Auto-deploy: $DEPLOY_SERVICES"
echo ""

# Validate prerequisites
echo "🔍 Validating prerequisites..."

# Check if logged into gcloud
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -1 > /dev/null; then
    echo "❌ Not authenticated with gcloud. Run: gcloud auth login"
    exit 1
fi

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Check required files exist
required_files=(
    "docker/base.Dockerfile"
    "scrapers/Dockerfile" 
    "processors/Dockerfile"
    "reportgen/Dockerfile"
    "docker/cloudbuild.yaml"
)

for file in "${required_files[@]}"; do
    if [[ ! -f "$file" ]]; then
        echo "❌ Required file not found: $file"
        exit 1
    fi
done

echo "✅ Prerequisites validated"

# Build and push images
echo ""
echo "🔨 Building all service images..."
gcloud builds submit \
    --config docker/cloudbuild.yaml \
    --substitutions _REGION=$REGION,_DEPLOY_SERVICES=$DEPLOY_SERVICES \
    .

# Apply Terraform infrastructure (if exists)
if [[ -f "infra/main.tf" ]]; then
    echo ""
    echo "🏗️  Applying Terraform infrastructure..."
    cd infra/
    terraform init -upgrade
    terraform plan -var="project_id=$PROJECT_ID" -var="region=$REGION"
    terraform apply -var="project_id=$PROJECT_ID" -var="region=$REGION" -auto-approve
    cd ..
    echo "✅ Infrastructure updated"
fi

# Manual deployment commands (if auto-deploy was disabled)
if [[ "$DEPLOY_SERVICES" == "false" ]]; then
    echo ""
    echo "📝 Manual deployment commands:"
    echo ""
    echo "# Deploy scrapers:"
    echo "gcloud run deploy nba-scraper-events \\"
    echo "  --image gcr.io/$PROJECT_ID/nba-scrapers:latest \\"
    echo "  --region $REGION --args='events,--serve'"
    echo ""
    echo "gcloud run deploy nba-scraper-odds \\"
    echo "  --image gcr.io/$PROJECT_ID/nba-scrapers:latest \\"
    echo "  --region $REGION --args='odds,--serve'"
    echo ""
    echo "# Deploy processors:"
    echo "gcloud run deploy nba-processor-events \\"
    echo "  --image gcr.io/$PROJECT_ID/nba-processors:latest \\"
    echo "  --region $REGION --args='events,--serve'"
    echo ""
    echo "# Deploy report generators:"  
    echo "gcloud run deploy nba-reportgen-player \\"
    echo "  --image gcr.io/$PROJECT_ID/nba-reportgen:latest \\"
    echo "  --region $REGION --args='player-reports,--serve'"
fi

# Get service URLs (if deployed)
echo ""
echo "🔗 Service URLs:"
services=("nba-scraper-events" "nba-scraper-odds" "nba-processor-events" "nba-reportgen-player")

for service in "${services[@]}"; do
    if gcloud run services describe $service --region=$REGION --format="value(status.url)" 2>/dev/null; then
        url=$(gcloud run services describe $service --region=$REGION --format="value(status.url)")
        echo "$service: $url"
    else
        echo "$service: Not deployed"
    fi
done

# Test health endpoints
echo ""
echo "🏥 Testing health endpoints..."
for service in "${services[@]}"; do
    if url=$(gcloud run services describe $service --region=$REGION --format="value(status.url)" 2>/dev/null); then
        if curl -f "$url/health" > /dev/null 2>&1; then
            echo "✅ $service: Healthy"
        else
            echo "⚠️  $service: Health check failed"
        fi
    fi
done

echo ""
echo "🎉 Deployment complete!"
echo ""
echo "Next steps:"
echo "1. Test scrapers: curl \$SCRAPER_URL/health"
echo "2. Deploy workflows: ./bin/deploy_workflow.sh"
echo "3. Set up monitoring: ./bin/setup_monitoring.sh"
echo "4. Configure schedulers: ./cloud_scripts/manage_schedulers.sh"

