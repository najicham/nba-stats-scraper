# predictions/coordinator/Dockerfile
# Prediction Coordinator - Cloud Run Deployment
#
# Builds from repository root to include shared dependencies

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

WORKDIR /app

# Copy shared modules from repository root
COPY shared/ ./shared/

# Copy predictions package structure
COPY predictions/__init__.py ./predictions/__init__.py

# Copy predictions/shared module (contains batch_staging_writer, etc.)
COPY predictions/shared/ ./predictions/shared/

# Copy predictions/worker module (coordinator imports data_loaders for batch historical game loading)
COPY predictions/worker/ ./predictions/worker/

# Copy coordinator code
COPY predictions/coordinator/ ./predictions/coordinator/

# Set working directory to coordinator
WORKDIR /app/predictions/coordinator

# Install shared requirements first (includes boto3 for AWS SES)
RUN pip install --no-cache-dir -r ../../shared/requirements.txt

# Install service-specific requirements (using lock file for deterministic builds)
RUN pip install --no-cache-dir -r requirements-lock.txt

# Set Python path to include /app for shared module imports
ENV PYTHONPATH=/app:$PYTHONPATH

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=5)"

# Run with gunicorn using config file for proper logging
# The gunicorn_config.py contains logconfig_dict that forwards Python logger output
# to stdout/stderr so Cloud Run can capture application-level logs
CMD exec gunicorn --config gunicorn_config.py coordinator:app
