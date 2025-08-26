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

COPY processors/requirements_processors.txt /app/processors/
RUN pip install --no-cache-dir -r /app/processors/requirements_processors.txt

# Copy all code
COPY shared/ /app/shared/
COPY processors/ /app/processors/
COPY processor_backfill/ /app/processor_backfill/

# Copy the specific job script to fixed location
COPY ${JOB_SCRIPT} ./job_script.py

# Set Python path
ENV PYTHONPATH=/app:$PYTHONPATH
ENV PYTHONUNBUFFERED=1

# Set the entrypoint to run the job script
ENTRYPOINT ["python", "job_script.py"]

# Labels
LABEL job.name="${JOB_NAME}"
