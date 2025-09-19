# FILE: docker/backfill.Dockerfile
#
# Single parameterized Dockerfile for all NBA backfill jobs
# Takes job script as build argument - matches processor.Dockerfile pattern
#
# IMPORTANT: Args Passing for Cloud Run Jobs
# ==========================================
# When executing jobs with gcloud, use custom delimiter syntax for comma-separated values:
#   gcloud run jobs execute JOB_NAME --args="^|^--seasons=2021,2022,2023|--limit=5"
#
# The ^|^ syntax tells gcloud to use | as delimiter instead of comma, preserving commas in values.
# Without this, gcloud splits on commas causing "unrecognized arguments" errors.
# See: https://discuss.google.dev/t/gcloud-run-jobs-args-with-comma-delim-values/176982/4

FROM python:3.11-slim

# Build argument for job script path
ARG JOB_SCRIPT
ARG JOB_NAME="backfill-job"

# Validate required build arg
RUN test -n "$JOB_SCRIPT" || (echo "ERROR: JOB_SCRIPT build arg required" && false)

# Set working directory
WORKDIR /app

# Install system dependencies (match processor pattern)
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Copy and install requirements (match processor pattern)
COPY shared/requirements.txt /app/shared/
RUN pip install --no-cache-dir -r /app/shared/requirements.txt

COPY scrapers/requirements.txt /app/scrapers/
RUN pip install --no-cache-dir -r /app/scrapers/requirements.txt

# Copy all necessary directories (match processor pattern)
COPY shared/ /app/shared/
COPY scrapers/ /app/scrapers/
COPY backfill/ /app/backfill/

# Copy the specific job script to fixed location
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
LABEL version="1.2.0"
