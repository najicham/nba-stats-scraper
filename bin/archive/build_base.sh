#!/bin/bash
set -e

PROJECT="nba-props-platform"
REGION="us-west2"
BASE_TAG="latest"

# Use Artifact Registry as intended
BASE_IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/pipeline/nba-base:${BASE_TAG}"

echo "🔨 Building sophisticated base image..."
echo "📦 Image: $BASE_IMAGE"
echo "⏱️  This will take ~5 minutes (one-time setup)"

# Create temporary cloudbuild.yaml for base image
cat > /tmp/cloudbuild-base.yaml << EOF
steps:
- name: 'gcr.io/cloud-builders/docker'
  args: ['build', '-t', '${BASE_IMAGE}', '-f', 'docker/base.Dockerfile', '.']
images:
- '${BASE_IMAGE}'
EOF

# Build base image using cloudbuild.yaml
gcloud builds submit \
  --config /tmp/cloudbuild-base.yaml \
  .

# Clean up temp file
rm /tmp/cloudbuild-base.yaml

echo "✅ Base image built: ${BASE_IMAGE}"
echo "🎯 Next: Build service image"
