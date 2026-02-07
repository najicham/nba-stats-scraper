# data_processors/raw/Dockerfile
# Raw Processor (Phase 2) - Cloud Run Deployment
#
# Build from repository root to include shared/ module:
#   docker build -f data_processors/raw/Dockerfile -t raw-processor .
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

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy ONLY requirements first (cached layer - deps rarely change)
COPY shared/requirements.txt ./shared/requirements.txt
COPY data_processors/raw/requirements-lock.txt ./data_processors/raw/requirements-lock.txt

# Install dependencies before copying code (code changes don't bust pip cache)
RUN pip install --no-cache-dir -r shared/requirements.txt
RUN pip install --no-cache-dir -r data_processors/raw/requirements-lock.txt

# Now copy all source code
COPY shared/ ./shared/

# Copy scrapers utils (needed for team mappings and utilities)
COPY scrapers/__init__.py ./scrapers/__init__.py
COPY scrapers/utils/ ./scrapers/utils/

# Copy raw processor code
COPY data_processors/raw/ ./data_processors/raw/

# Set working directory to raw for running the service
WORKDIR /app/data_processors/raw

# Set Python path to include /app for shared module imports
ENV PYTHONPATH=/app:$PYTHONPATH

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=5)"

# Run service with gunicorn
# - Single worker process (Cloud Run handles scaling)
# - 5 threads for concurrent processing
# - 600s timeout for long-running raw data processing
# - Bind to PORT env var (Cloud Run default: 8080)
CMD exec gunicorn \
  --bind :${PORT:-8080} \
  --workers 1 \
  --threads 5 \
  --timeout 600 \
  --access-logfile - \
  --error-logfile - \
  --log-level info \
  main_processor_service:app
