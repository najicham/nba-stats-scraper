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

# Copy shared module from repository root (relative to build context)
COPY shared/ ./shared/

# Copy predictions package structure (required for predictions.worker imports)
COPY predictions/__init__.py ./predictions/__init__.py

# Copy predictions/shared module (contains mock models, etc.)
COPY predictions/shared/ ./predictions/shared/

# Copy worker code and dependencies
COPY predictions/worker/ ./predictions/worker/

# Set working directory to worker for running the service
WORKDIR /app/predictions/worker

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

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
