# MLB Grading Service Dockerfile
# Phase 6: Grade predictions against actual results
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy shared requirements
COPY shared/requirements.txt /app/shared/
RUN pip install --no-cache-dir -r /app/shared/requirements.txt || true

# Install additional requirements
RUN pip install --no-cache-dir flask gunicorn google-cloud-bigquery

# Copy necessary code
COPY shared/ /app/shared/
COPY data_processors/grading/ /app/data_processors/grading/

# Set Python path and environment
ENV PYTHONPATH=/app:$PYTHONPATH
ENV PORT=8080
ENV SPORT=mlb

# Run the MLB grading service
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 data_processors.grading.mlb.main_mlb_grading_service:app
