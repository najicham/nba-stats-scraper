# File: docker/processor.Dockerfile
# Matches the scraper backfill.Dockerfile pattern

FROM python:3.11-slim

# Build argument for job script path
ARG JOB_SCRIPT
ARG JOB_NAME="processor-backfill-job"

# Validate required build arg
RUN test -n "$JOB_SCRIPT" || (echo "ERROR: JOB_SCRIPT build arg required" && false)

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY shared/requirements.txt /app/shared/
RUN pip install --no-cache-dir -r /app/shared/requirements.txt

COPY data_processors/raw/requirements.txt /app/data_processors/raw/
RUN pip install --no-cache-dir -r /app/data_processors/raw/requirements.txt

# Copy all code
COPY shared/ /app/shared/
COPY data_processors/raw/ /app/data_processors/raw/
COPY backfill_jobs/raw/ /app/backfill_jobs/raw/

# Copy the specific job script to fixed location
COPY ${JOB_SCRIPT} ./job_script.py

# Set Python path
ENV PYTHONPATH=/app:$PYTHONPATH
ENV PYTHONUNBUFFERED=1

# Set the entrypoint to run the job script
ENTRYPOINT ["python", "job_script.py"]

# Labels
LABEL job.name="${JOB_NAME}"