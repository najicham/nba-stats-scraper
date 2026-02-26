# predictions/worker/Dockerfile
# Phase 5 Prediction Worker - Cloud Run Deployment
#
# Build from repository root to include shared/ module:
#   docker build -f predictions/worker/Dockerfile -t worker .
#
# Or use gcloud run deploy with --source from repo root

FROM python:3.11-slim

# Build-time arguments for tracking what code is in this image
ARG BUILD_COMMIT=unknown
ARG BUILD_TIMESTAMP=unknown

# Store build info as environment variables (queryable at runtime)
ENV BUILD_COMMIT=${BUILD_COMMIT}
ENV BUILD_TIMESTAMP=${BUILD_TIMESTAMP}

# Add labels for image inspection
LABEL build.commit="${BUILD_COMMIT}"
LABEL build.timestamp="${BUILD_TIMESTAMP}"

# Set working directory
WORKDIR /app

# Copy ONLY requirements first (cached layer - deps rarely change)
COPY shared/requirements.txt ./shared/requirements.txt
COPY predictions/worker/requirements-lock.txt ./predictions/worker/requirements-lock.txt

# Install dependencies before copying code (code changes don't bust pip cache)
RUN pip install --no-cache-dir -r shared/requirements.txt
RUN pip install --no-cache-dir -r predictions/worker/requirements-lock.txt

# Now copy all source code
COPY shared/ ./shared/

# Copy predictions package structure (required for predictions.worker imports)
COPY predictions/__init__.py ./predictions/__init__.py

# Copy predictions/shared module (contains mock models, etc.)
COPY predictions/shared/ ./predictions/shared/

# Copy worker code and dependencies
COPY predictions/worker/ ./predictions/worker/

# Copy ml module (breakout_classifier_v1 imports ml.features.breakout_features)
COPY ml/ ./ml/

# Copy V9 model files from build context (Session 70, fixed Sessions 148, 163)
# Models are gitignored — Cloud Build downloads them from GCS in cloudbuild.yaml Step 0.
# The code globs for catboost_v9*.cbm so filenames must match that pattern.
# For local builds, ensure models/ has the required .cbm files.
COPY models/ ./models/

# Breakout classifier model loaded from GCS via BREAKOUT_CLASSIFIER_MODEL_PATH env var
# See: gs://nba-props-platform-models/breakout/v1/

# Set working directory to worker for running the service
WORKDIR /app/predictions/worker

# Set Python path to include /app for shared module imports
ENV PYTHONPATH=/app:$PYTHONPATH

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=5)"

# Run worker with gunicorn
# - Single worker process (Cloud Run handles scaling)
# - 5 threads for concurrent processing
# - 300s timeout for long-running predictions
# - Bind to PORT env var (Cloud Run default: 8080)
CMD exec gunicorn \
  --bind :${PORT:-8080} \
  --workers 1 \
  --threads 5 \
  --timeout 300 \
  --access-logfile - \
  --error-logfile - \
  --log-level info \
  worker:app
