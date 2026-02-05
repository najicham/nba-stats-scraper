# data_processors/precompute/Dockerfile
# Precompute Processor - Cloud Run Deployment
#
# Build from repository root to include shared/ module:
#   docker build -f data_processors/precompute/Dockerfile -t precompute-processor .
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

# Copy data_processors modules (precompute depends on raw and analytics)
COPY data_processors/raw/ ./data_processors/raw/
COPY data_processors/analytics/ ./data_processors/analytics/
COPY data_processors/precompute/ ./data_processors/precompute/

# Copy analytics requirements (precompute uses same dependencies)
COPY data_processors/analytics/requirements.txt /tmp/requirements.txt

# Set working directory to precompute for running the service
WORKDIR /app/data_processors/precompute

# Install shared requirements first (includes boto3 for AWS SES)
RUN pip install --no-cache-dir -r ../../shared/requirements.txt

# Install service-specific requirements (from analytics)
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Set Python path to include /app for shared module imports
ENV PYTHONPATH=/app:$PYTHONPATH

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=5)"

# Run service with gunicorn
# - Single worker process (Cloud Run handles scaling)
# - 4 threads for concurrent processing
# - 300s timeout for long-running precompute operations
# - Bind to PORT env var (Cloud Run default: 8080)
CMD exec gunicorn \
  --bind :${PORT:-8080} \
  --workers 1 \
  --threads 4 \
  --timeout 300 \
  --access-logfile - \
  --error-logfile - \
  --log-level info \
  main_precompute_service:app
