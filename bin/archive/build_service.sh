#!/bin/bash
set -euo pipefail

PROJECT="nba-props-platform"
REGION="us-west2" 
TAG="dev-$(date +%H%M%S)"

# Use Artifact Registry consistently
SERVICE_IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/pipeline/nba-scrapers:${TAG}"

echo "🔨 Building service image using base..."
echo "📦 Image: $SERVICE_IMAGE"
echo "⏱️  This will take ~2 minutes (uses cached base)"

# Create temporary cloudbuild.yaml for service image (fixed substitutions)
cat > /tmp/cloudbuild-service.yaml << EOF
steps:
- name: 'gcr.io/cloud-builders/docker'
  args: ['build', '-t', '${SERVICE_IMAGE}', '-f', 'Dockerfile.service', 
         '--build-arg', 'PROJECT_ID=${PROJECT}',
         '--build-arg', 'REGION=${REGION}',
         '.']
images:
- '${SERVICE_IMAGE}'
EOF

# Build service image using cloudbuild.yaml
gcloud builds submit \
  --config /tmp/cloudbuild-service.yaml \
  .

# Clean up temp file
rm /tmp/cloudbuild-service.yaml

echo "✅ Service image built: ${SERVICE_IMAGE}"
echo "${SERVICE_IMAGE}" > .last_image

echo "🎯 Ready for 30-second deployment!"
