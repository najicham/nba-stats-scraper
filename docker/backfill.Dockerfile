# FILE: docker/backfill.Dockerfile
# 
# Single parameterized Dockerfile for all NBA backfill jobs
# Takes job script as build argument - simpler than two-stage approach

FROM python:3.11-slim

# Build argument for job script path
ARG JOB_SCRIPT
ARG JOB_NAME="backfill-job"

# Validate required build arg
RUN test -n "$JOB_SCRIPT" || (echo "ERROR: JOB_SCRIPT build arg required" && false)

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (comprehensive set for all backfills)
RUN pip install --no-cache-dir \
    requests==2.31.0 \
    google-cloud-storage==2.10.0 \
    google-cloud-logging==3.8.0 \
    python-dotenv==1.0.0

# Copy common utilities (needed by some backfills)
COPY scrapers/__init__.py ./scrapers/
COPY scrapers/utils/ ./scrapers/utils/

# Copy the specific job script
COPY ${JOB_SCRIPT} ./job_script.py

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Add health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser
RUN chown -R appuser:appuser /app
USER appuser

# Set the entrypoint to run the job script
ENTRYPOINT ["python", "job_script.py"]

# Labels for organization
LABEL maintainer="NBA Props Platform"
LABEL description="Parameterized backfill job container"
LABEL job.name="${JOB_NAME}"
LABEL version="1.0.0"