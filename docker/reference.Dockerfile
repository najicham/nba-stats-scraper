# File: docker/reference.Dockerfile
# Optimized reference processors and backfill jobs
FROM python:3.11-slim-bullseye

# Build argument for job script path
ARG JOB_SCRIPT
ARG JOB_NAME="reference-backfill-job"

# Validate required build arg
RUN test -n "$JOB_SCRIPT" || (echo "ERROR: JOB_SCRIPT build arg required" && false)

# Set working directory
WORKDIR /app

# Install system dependencies in single layer with cleanup
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && apt-get autoremove -y

# Copy requirements files first (for better layer caching)
COPY shared/requirements.txt /app/shared/
COPY data_processors/raw/requirements_processors.txt /app/data_processors/raw/

# Install Python packages with optimizations (combined for fewer layers)
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r /app/shared/requirements.txt \
    && pip install --no-cache-dir -r /app/data_processors/raw/requirements_processors.txt \
    && pip cache purge

# Copy source code (this layer changes frequently, so keep it last)
COPY shared/ /app/shared/
COPY data_processors/raw/ /app/data_processors/raw/
COPY data_processors/reference/ /app/data_processors/reference/
COPY backfill_jobs/reference/ /app/backfill_jobs/reference/

# Copy the specific job script to fixed location
COPY ${JOB_SCRIPT} ./job_script.py

# Set Python path and environment
ENV PYTHONPATH=/app:$PYTHONPATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Set the entrypoint to run the job script
ENTRYPOINT ["python", "job_script.py"]

# Labels
LABEL job.name="${JOB_NAME}"