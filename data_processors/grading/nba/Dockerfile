# data_processors/grading/nba/Dockerfile
# NBA Grading Service - Cloud Run Deployment
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

# Copy predictions shared module (needed for distributed_lock)
COPY predictions/__init__.py ./predictions/__init__.py
COPY predictions/shared/ ./predictions/shared/

# Copy data_processors package structure
COPY data_processors/__init__.py ./data_processors/__init__.py

# Copy grading modules
COPY data_processors/grading/ ./data_processors/grading/

# Set working directory to NBA grading service
WORKDIR /app/data_processors/grading/nba

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Set Python path to include /app for shared module imports
ENV PYTHONPATH=/app:$PYTHONPATH

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=5)"

# Run with gunicorn for production
CMD exec gunicorn \
  --bind :${PORT:-8080} \
  --workers 1 \
  --threads 2 \
  --timeout 600 \
  --access-logfile - \
  --error-logfile - \
  --log-level info \
  main_nba_grading_service:app
