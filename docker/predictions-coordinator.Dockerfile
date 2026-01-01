# docker/predictions-coordinator.Dockerfile
#
# Phase 5 Prediction Coordinator - Cloud Run Container
#
# Purpose: Orchestrates daily prediction batch by fanning out work to workers
#
# Container Architecture:
# - Base: Python 3.11 slim (lightweight)
# - Web server: Gunicorn with Flask
# - Concurrency: 1 worker, 8 threads (handles multiple /complete events)
# - Endpoints: /start (batch initiation), /status, /complete (worker events)
#
# Build from project root:
#   docker build -f docker/predictions-coordinator.Dockerfile -t coordinator:latest .
#
# Run locally:
#   docker run -p 8080:8080 \
#     -e GCP_PROJECT_ID=nba-props-platform-dev \
#     coordinator:latest

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
# - curl: Health check endpoint testing
# - gcc: Required for some Python package compilations
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (Docker layer caching optimization)
# If requirements.txt doesn't change, this layer is cached
COPY predictions/coordinator/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared utilities (needed for UnifiedPubSubPublisher imports)
COPY shared/ /app/shared/

# Copy coordinator code (flat structure for simple imports)
COPY predictions/coordinator/coordinator.py /app/coordinator.py
COPY predictions/coordinator/player_loader.py /app/player_loader.py
COPY predictions/coordinator/progress_tracker.py /app/progress_tracker.py
COPY predictions/coordinator/run_history.py /app/run_history.py
COPY predictions/coordinator/coverage_monitor.py /app/coverage_monitor.py
COPY predictions/coordinator/batch_state_manager.py /app/batch_state_manager.py

# Copy batch staging writer (needed for BatchConsolidator)
COPY predictions/worker/batch_staging_writer.py /app/batch_staging_writer.py

# Copy data loaders (needed for batch historical games optimization)
COPY predictions/worker/data_loaders.py /app/data_loaders.py

# Environment variables
# PYTHONPATH: Ensures imports work correctly
# PYTHONUNBUFFERED: Ensures logs appear immediately (not buffered)
# PORT: Default port for Cloud Run (overridden by Cloud Run at runtime)
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Health check
# Runs every 30 seconds to verify container is healthy
# - interval: How often to check
# - timeout: Max time for check to complete
# - start-period: Grace period after container starts
# - retries: How many failures before marking unhealthy
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run coordinator with Gunicorn
# - bind :$PORT - Listen on Cloud Run assigned port
# - workers 1 - Single process (threading locks work within single process)
# - threads 8 - Handle 8 concurrent completion events
# - timeout 300 - 5 minute request timeout (batch initiation can be slow)
# - worker-class sync - Default synchronous workers with threading
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 300 coordinator:app
