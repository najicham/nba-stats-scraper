# File: docker/reference-service.Dockerfile
# Reference processor service (web server, not job)
FROM python:3.11-slim-bullseye

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy requirements files first (for better caching)
COPY shared/requirements.txt /app/shared/
COPY data_processors/reference/requirements.txt /app/data_processors/reference/

# Install Python packages
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r /app/shared/requirements.txt \
    && pip install --no-cache-dir -r /app/data_processors/reference/requirements.txt \
    && pip cache purge

# Copy source code
COPY shared/ /app/shared/
COPY scrapers/utils/ /app/scrapers/utils/
COPY data_processors/reference/ /app/data_processors/reference/

# Set Python path and environment
ENV PYTHONPATH=/app:$PYTHONPATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

# Run the reference service with gunicorn
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 data_processors.reference.main_reference_service:app