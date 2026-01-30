# docker/base.Dockerfile
# Base image with common dependencies for all NBA services
FROM python:3.11-slim AS base

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create app user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Set working directory
WORKDIR /app

# Copy shared requirements and install
COPY shared/requirements.txt /app/shared/
RUN pip install --no-cache-dir -r shared/requirements.txt

# Copy shared utilities (includes config)
COPY shared/ /app/shared/

# Set Python path to include shared modules
ENV PYTHONPATH=/app:/app/shared

# Security: switch to non-root user  
USER appuser

# Health check base (PORT will be set by each service)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:${PORT:-8080}/health || exit 1