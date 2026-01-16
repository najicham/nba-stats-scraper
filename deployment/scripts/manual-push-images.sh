#!/bin/bash
# Manual image push script with retry logic

PROJECT_ID="nba-props-platform"
REGION="us-west2"
VERSION="v1.0.0"

push_with_retry() {
    local image=$1
    local max_attempts=3
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        echo "Attempt $attempt/$max_attempts: Pushing $image..."
        if docker push "$image"; then
            echo "✓ Successfully pushed $image"
            return 0
        else
            echo "✗ Failed to push $image (attempt $attempt/$max_attempts)"
            if [ $attempt -lt $max_attempts ]; then
                echo "Waiting 10 seconds before retry..."
                sleep 10
            fi
        fi
        attempt=$((attempt + 1))
    done

    echo "✗ Failed to push $image after $max_attempts attempts"
    return 1
}

# Remaining monitoring images (2 of 4 done)
echo "=== Pushing remaining monitoring images ==="

echo "Building prediction-coverage..."
docker build -t us-west2-docker.pkg.dev/$PROJECT_ID/mlb-monitoring/prediction-coverage:$VERSION \
  -t us-west2-docker.pkg.dev/$PROJECT_ID/mlb-monitoring/prediction-coverage:latest \
  -f deployment/dockerfiles/mlb/Dockerfile.prediction-coverage . || exit 1

push_with_retry "us-west2-docker.pkg.dev/$PROJECT_ID/mlb-monitoring/prediction-coverage:$VERSION"
push_with_retry "us-west2-docker.pkg.dev/$PROJECT_ID/mlb-monitoring/prediction-coverage:latest"

echo "Building stall-detector..."
docker build -t us-west2-docker.pkg.dev/$PROJECT_ID/mlb-monitoring/stall-detector:$VERSION \
  -t us-west2-docker.pkg.dev/$PROJECT_ID/mlb-monitoring/stall-detector:latest \
  -f deployment/dockerfiles/mlb/Dockerfile.stall-detector . || exit 1

push_with_retry "us-west2-docker.pkg.dev/$PROJECT_ID/mlb-monitoring/stall-detector:$VERSION"
push_with_retry "us-west2-docker.pkg.dev/$PROJECT_ID/mlb-monitoring/stall-detector:latest"

# Validator images (0 of 3 done)
echo "=== Pushing validator images ==="

echo "Building schedule-validator..."
docker build -t us-west2-docker.pkg.dev/$PROJECT_ID/mlb-validators/schedule-validator:$VERSION \
  -t us-west2-docker.pkg.dev/$PROJECT_ID/mlb-validators/schedule-validator:latest \
  -f deployment/dockerfiles/mlb/Dockerfile.schedule-validator . || exit 1

push_with_retry "us-west2-docker.pkg.dev/$PROJECT_ID/mlb-validators/schedule-validator:$VERSION"
push_with_retry "us-west2-docker.pkg.dev/$PROJECT_ID/mlb-validators/schedule-validator:latest"

echo "Building pitcher-props-validator..."
docker build -t us-west2-docker.pkg.dev/$PROJECT_ID/mlb-validators/pitcher-props-validator:$VERSION \
  -t us-west2-docker.pkg.dev/$PROJECT_ID/mlb-validators/pitcher-props-validator:latest \
  -f deployment/dockerfiles/mlb/Dockerfile.pitcher-props-validator . || exit 1

push_with_retry "us-west2-docker.pkg.dev/$PROJECT_ID/mlb-validators/pitcher-props-validator:$VERSION"
push_with_retry "us-west2-docker.pkg.dev/$PROJECT_ID/mlb-validators/pitcher-props-validator:latest"

echo "Building prediction-coverage-validator..."
docker build -t us-west2-docker.pkg.dev/$PROJECT_ID/mlb-validators/prediction-coverage-validator:$VERSION \
  -t us-west2-docker.pkg.dev/$PROJECT_ID/mlb-validators/prediction-coverage-validator:latest \
  -f deployment/dockerfiles/mlb/Dockerfile.prediction-coverage-validator . || exit 1

push_with_retry "us-west2-docker.pkg.dev/$PROJECT_ID/mlb-validators/prediction-coverage-validator:$VERSION"
push_with_retry "us-west2-docker.pkg.dev/$PROJECT_ID/mlb-validators/prediction-coverage-validator:latest"

echo ""
echo "=== Image push complete ==="
