# File: data_processors/analytics/Dockerfile
# Analytics processors Dockerfile
FROM python:3.11-slim

# Build-time arguments for tracking what code is in this image
ARG BUILD_COMMIT=unknown
ARG BUILD_TIMESTAMP=unknown
ARG BUILD_REF=unknown

# Store build info as environment variables (queryable at runtime)
ENV BUILD_COMMIT=${BUILD_COMMIT}
ENV BUILD_TIMESTAMP=${BUILD_TIMESTAMP}
ENV BUILD_REF=${BUILD_REF}

# Add labels for image inspection
LABEL build.commit="${BUILD_COMMIT}"
LABEL build.timestamp="${BUILD_TIMESTAMP}"
LABEL build.ref="${BUILD_REF}"

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy shared requirements first (for better caching)
COPY shared/requirements.txt /app/shared/
RUN pip install --no-cache-dir -r /app/shared/requirements.txt || true

# Copy analytics processor requirements
COPY data_processors/analytics/requirements.txt /app/data_processors/analytics/
RUN pip install --no-cache-dir -r /app/data_processors/analytics/requirements.txt

# Copy raw processor requirements (Phase 2)
COPY data_processors/raw/requirements.txt /app/data_processors/raw/
RUN pip install --no-cache-dir -r /app/data_processors/raw/requirements.txt

# Copy all necessary code
COPY shared/ /app/shared/
COPY scrapers/utils/ /app/scrapers/utils/
COPY data_processors/analytics/ /app/data_processors/analytics/
COPY data_processors/raw/ /app/data_processors/raw/

# Set Python path
ENV PYTHONPATH=/app:$PYTHONPATH
ENV PORT=8080

# Run the appropriate service based on SERVICE env var
# IMPORTANT: Explicit SERVICE env var required - no silent defaults
# This prevents wrong-code deployment (see: docs/09-handoff/2026-01-29-POSTMORTEM-SCRAPER-WRONG-DEPLOYMENT.md)
CMD if [ "$SERVICE" = "phase2" ]; then \
      exec gunicorn --bind :$PORT --workers 1 --threads 5 --timeout 600 data_processors.raw.main_processor_service:app; \
    elif [ "$SERVICE" = "analytics" ]; then \
      exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 data_processors.analytics.main_analytics_service:app; \
    else \
      echo "ERROR: SERVICE environment variable must be set to 'phase2' or 'analytics'" >&2; \
      echo "This Dockerfile should not be used directly for most services." >&2; \
      echo "Use the service-specific Dockerfile instead:" >&2; \
      echo "  - scrapers/Dockerfile for nba-scrapers" >&2; \
      echo "  - predictions/coordinator/Dockerfile for prediction-coordinator" >&2; \
      echo "  - predictions/worker/Dockerfile for prediction-worker" >&2; \
      exit 1; \
    fi