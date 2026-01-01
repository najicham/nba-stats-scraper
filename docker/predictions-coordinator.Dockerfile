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
COPY predictions/coordinator/gunicorn_config.py /app/gunicorn_config.py

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
# - config gunicorn_config.py - Use configuration file with proper logging setup
# - Logging configuration ensures Python logger.info() appears in Cloud Run logs
# - Configuration includes: workers, threads, timeout, log formatting
CMD exec gunicorn --config gunicorn_config.py coordinator:app
