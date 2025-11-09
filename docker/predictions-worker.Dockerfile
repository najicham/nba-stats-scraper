# docker/predictions-worker.Dockerfile

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for layer caching)
COPY predictions/worker/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy prediction systems
COPY predictions/worker/prediction_systems/ /app/prediction_systems/

# Copy worker code
COPY predictions/worker/data_loaders.py /app/data_loaders.py
COPY predictions/worker/worker.py /app/worker.py

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run the worker
CMD exec gunicorn --bind :$PORT --workers 1 --threads 5 --timeout 300 worker:app
