# FILE: docker/analytics.Dockerfile
#
# Analytics Dockerfile for NBA analytics processor backfill jobs
# Includes data_processors/analytics module and all required dependencies
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
ARG JOB_NAME="analytics-backfill-job"

# Validate required build arg
RUN test -n "$JOB_SCRIPT" || (echo "ERROR: JOB_SCRIPT build arg required" && false)

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

# CRITICAL FIX: Copy and install BOTH shared and analytics requirements
# Shared requirements include google-cloud-pubsub and other core dependencies
COPY shared/requirements.txt /app/shared_requirements.txt
COPY data_processors/analytics/requirements.txt /app/analytics_requirements.txt

# Install shared requirements first, then analytics-specific ones
RUN pip install --no-cache-dir -r /app/shared_requirements.txt \
    && pip install --no-cache-dir -r /app/analytics_requirements.txt

# Install additional backfill-specific dependencies
RUN pip install --no-cache-dir \
    requests==2.31.0 \
    google-cloud-logging==3.8.0 \
    python-dotenv==1.0.0 \
    db-dtypes

# Copy shared utilities (needed by analytics processors)
COPY shared/ ./shared/

# Copy scrapers utilities (needed by some analytics processors)
COPY scrapers/__init__.py ./scrapers/
COPY scrapers/utils/ ./scrapers/utils/

# Copy analytics processors module (CRITICAL - this was missing initially)
COPY data_processors/analytics/ ./data_processors/analytics/

# Copy analytics backfill directory
COPY backfill_jobs/analytics/ ./backfill_jobs/analytics/

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
LABEL description="Analytics processor backfill job container"
LABEL job.name="${JOB_NAME}"
LABEL version="1.2.0"
