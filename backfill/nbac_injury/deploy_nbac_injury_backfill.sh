#!/bin/bash
# FILE: backfill/nbac_injury/deploy_nbac_injury_backfill.sh
# Purpose: Deploy NBA.com Injury Reports backfill Cloud Run job
# Usage: ./backfill/nbac_injury/deploy_nbac_injury_backfill.sh

set -e

# Configuration
PROJECT_ID="nba-props-platform"
REGION="us-west2"
JOB_NAME="nba-injury-backfill"
IMAGE_NAME="nba-injury-backfill"
ARTIFACT_REGISTRY="us-west2-docker.pkg.dev/nba-props-platform/nba-scrapers"
SERVICE_ACCOUNT="nba-scrapers@nba-props-platform.iam.gserviceaccount.com"

# Default scraper service URL (can be overridden)
DEFAULT_SCRAPER_SERVICE_URL="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🏥 Deploying NBA Injury Reports Backfill Job${NC}"
echo "=============================================="
echo ""

# Verify we're in the right directory structure
if [[ ! -f "backfill/nbac_injury/nbac_injury_backfill_job.py" ]]; then
    echo -e "${RED}❌ Error: Must run from project root directory${NC}"
    echo "Expected file: backfill/nbac_injury/nbac_injury_backfill_job.py"
    exit 1
fi

# Check if gcloud is authenticated
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q "@"; then
    echo -e "${RED}❌ Error: gcloud not authenticated${NC}"
    echo "Run: gcloud auth login"
    exit 1
fi

# Set project
echo -e "${YELLOW}📋 Setting project: $PROJECT_ID${NC}"
gcloud config set project $PROJECT_ID

# Create Dockerfile for injury backfill
echo -e "${YELLOW}📝 Creating Dockerfile...${NC}"
cat > backfill/nbac_injury/Dockerfile.nbac_injury_backfill << 'EOF'
# Dockerfile for NBA Injury Reports Backfill Job
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backfill/nbac_injury/nbac_injury_backfill_job.py .
COPY shared/ ./shared/

# Install Google Cloud SDK (needed for gcloud commands in backfill)
RUN curl -sSL https://sdk.cloud.google.com | bash
ENV PATH $PATH:/root/google-cloud-sdk/bin

# Set environment variables
ENV PYTHONPATH=/app
ENV GOOGLE_CLOUD_PROJECT=nba-props-platform

# Default command
CMD ["python", "nbac_injury_backfill_job.py", "--service-url", "${SCRAPER_SERVICE_URL:-https://nba-scrapers-f7p3g7f6ya-wl.a.run.app}"]
EOF

# Build the image
echo -e "${YELLOW}🔨 Building Docker image...${NC}"
FULL_IMAGE_NAME="${ARTIFACT_REGISTRY}/${IMAGE_NAME}:latest"

docker build \
    -f backfill/nbac_injury/Dockerfile.nbac_injury_backfill \
    -t $FULL_IMAGE_NAME \
    .

# Push to Artifact Registry
echo -e "${YELLOW}📤 Pushing image to Artifact Registry...${NC}"
docker push $FULL_IMAGE_NAME

# Deploy Cloud Run Job
echo -e "${YELLOW}🚀 Deploying Cloud Run Job...${NC}"
gcloud run jobs replace - <<EOF
apiVersion: run.googleapis.com/v1
kind: Job
metadata:
  name: $JOB_NAME
  namespace: '$PROJECT_ID'
  labels:
    cloud.googleapis.com/location: $REGION
    purpose: 'nba-injury-backfill'
    component: 'data-collection'
spec:
  spec:
    template:
      spec:
        template:
          spec:
            serviceAccountName: $SERVICE_ACCOUNT
            timeoutSeconds: 86400  # 24 hours max runtime
            containers:
            - name: $JOB_NAME
              image: $FULL_IMAGE_NAME
              resources:
                limits:
                  cpu: '2'
                  memory: '4Gi'
              env:
              - name: SCRAPER_SERVICE_URL
                value: '$DEFAULT_SCRAPER_SERVICE_URL'
              - name: GOOGLE_CLOUD_PROJECT
                value: '$PROJECT_ID'
            restartPolicy: OnFailure
            completions: 1
            parallelism: 1
EOF

# Set IAM permissions
echo -e "${YELLOW}🔐 Setting IAM permissions...${NC}"
gcloud run jobs add-iam-policy-binding $JOB_NAME \
    --region=$REGION \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/run.invoker"

echo ""
echo -e "${GREEN}✅ NBA Injury Reports Backfill Job deployed successfully!${NC}"
echo ""
echo -e "${BLUE}📋 Job Details:${NC}"
echo "  Name: $JOB_NAME"
echo "  Region: $REGION"
echo "  Image: $FULL_IMAGE_NAME"
echo "  Service Account: $SERVICE_ACCOUNT"
echo "  Max Runtime: 24 hours"
echo ""
echo -e "${BLUE}🎯 Usage Examples:${NC}"
echo ""
echo -e "${YELLOW}1. Dry run (see what would be processed):${NC}"
echo "  gcloud run jobs execute $JOB_NAME \\"
echo "    --args=\"--service-url=$DEFAULT_SCRAPER_SERVICE_URL --dry-run --seasons=2024\" \\"
echo "    --region=$REGION"
echo ""
echo -e "${YELLOW}2. Single season test (2024):${NC}"
echo "  gcloud run jobs execute $JOB_NAME \\"
echo "    --args=\"--service-url=$DEFAULT_SCRAPER_SERVICE_URL --seasons=2024 --limit=100\" \\"
echo "    --region=$REGION"
echo ""
echo -e "${YELLOW}3. Full 4-season backfill:${NC}"
echo "  gcloud run jobs execute $JOB_NAME \\"
echo "    --region=$REGION"
echo ""
echo -e "${YELLOW}4. Monitor progress:${NC}"
echo "  ./bin/backfill/nbac_injury_monitor.sh quick"
echo "  ./bin/backfill/nbac_injury_monitor.sh progress"
echo "  ./bin/backfill/nbac_injury_monitor.sh patterns"
echo ""
echo -e "${BLUE}💡 Pro Tips:${NC}"
echo "  • Use --limit for testing (e.g., --limit=50 for first 50 intervals)"
echo "  • Monitor with: ./bin/backfill/nbac_injury_monitor.sh watch"
echo "  • Check patterns after collection for optimization insights"
echo "  • Expected runtime: ~8-12 hours for full 4-season backfill"
echo ""
echo -e "${GREEN}🎉 Ready to start NBA injury reports historical collection!${NC}"