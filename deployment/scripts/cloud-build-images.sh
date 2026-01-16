#!/bin/bash
set -e

# Build Docker images using Google Cloud Build (avoids local Docker issues)

PROJECT_ID="nba-props-platform"
REGION="us-west2"
VERSION="v1.0.0"

echo "Building MLB monitoring and validator images using Cloud Build..."
echo "This avoids local Docker networking issues"
echo ""

# Monitoring images
MONITORING_IMAGES=(
    "prediction-coverage"
    "stall-detector"
)

# Validator images
VALIDATOR_IMAGES=(
    "schedule-validator"
    "pitcher-props-validator"
    "prediction-coverage-validator"
)

# Build monitoring images
for image in "${MONITORING_IMAGES[@]}"; do
    echo "Building monitoring/$image using Cloud Build..."
    gcloud builds submit \
        --config=- \
        --substitutions=_IMAGE_NAME=$image,_VERSION=$VERSION \
        --project=$PROJECT_ID \
        --region=$REGION \
        . <<EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'build'
      - '-t'
      - 'us-west2-docker.pkg.dev/$PROJECT_ID/mlb-monitoring/\${_IMAGE_NAME}:\${_VERSION}'
      - '-t'
      - 'us-west2-docker.pkg.dev/$PROJECT_ID/mlb-monitoring/\${_IMAGE_NAME}:latest'
      - '-f'
      - 'deployment/dockerfiles/mlb/Dockerfile.\${_IMAGE_NAME}'
      - '.'
images:
  - 'us-west2-docker.pkg.dev/$PROJECT_ID/mlb-monitoring/\${_IMAGE_NAME}:\${_VERSION}'
  - 'us-west2-docker.pkg.dev/$PROJECT_ID/mlb-monitoring/\${_IMAGE_NAME}:latest'
timeout: 1200s
EOF
    echo "✓ Built monitoring/$image"
    echo ""
done

# Build validator images
for image in "${VALIDATOR_IMAGES[@]}"; do
    echo "Building validator/$image using Cloud Build..."
    gcloud builds submit \
        --config=- \
        --substitutions=_IMAGE_NAME=$image,_VERSION=$VERSION \
        --project=$PROJECT_ID \
        --region=$REGION \
        . <<EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'build'
      - '-t'
      - 'us-west2-docker.pkg.dev/$PROJECT_ID/mlb-validators/\${_IMAGE_NAME}:\${_VERSION}'
      - '-t'
      - 'us-west2-docker.pkg.dev/$PROJECT_ID/mlb-validators/\${_IMAGE_NAME}:latest'
      - '-f'
      - 'deployment/dockerfiles/mlb/Dockerfile.\${_IMAGE_NAME}'
      - '.'
images:
  - 'us-west2-docker.pkg.dev/$PROJECT_ID/mlb-validators/\${_IMAGE_NAME}:\${_VERSION}'
  - 'us-west2-docker.pkg.dev/$PROJECT_ID/mlb-validators/\${_IMAGE_NAME}:latest'
timeout: 1200s
EOF
    echo "✓ Built validator/$image"
    echo ""
done

echo "=== All images built successfully using Cloud Build ==="
