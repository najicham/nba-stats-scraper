# Shared Dockerfile for all processor jobs
FROM python:3.11-slim

# Build arguments
ARG JOB_TYPE=processor_backfill
ARG JOB_NAME=unknown_processor

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy shared requirements first (for better caching)
COPY shared/requirements.txt /app/shared/
RUN pip install --no-cache-dir -r /app/shared/requirements.txt

# Copy processor requirements
COPY processors/requirements_processors.txt /app/processors/
RUN pip install --no-cache-dir -r /app/processors/requirements_processors.txt

# Copy all code
COPY shared/ /app/shared/
COPY scrapers/utils/ /app/scrapers/utils/
COPY processors/ /app/processors/
COPY processor_backfill/ /app/processor_backfill/

# Set Python path
ENV PYTHONPATH=/app:$PYTHONPATH

# Set the job type and name
ENV JOB_TYPE=${JOB_TYPE}
ENV JOB_NAME=${JOB_NAME}

# Dynamic entrypoint based on job
ENTRYPOINT ["sh", "-c", "python /app/${JOB_TYPE}/${JOB_NAME}/${JOB_NAME}_backfill_job.py $@"]