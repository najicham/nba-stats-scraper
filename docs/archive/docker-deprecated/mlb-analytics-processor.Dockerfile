# MLB Analytics Processors Dockerfile
# Phase 3: Rolling K stats for pitchers and batters
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy shared requirements first (for better caching)
COPY shared/requirements.txt /app/shared/
RUN pip install --no-cache-dir -r /app/shared/requirements.txt || true

# Copy analytics processor requirements
COPY data_processors/analytics/requirements.txt /app/data_processors/analytics/
RUN pip install --no-cache-dir -r /app/data_processors/analytics/requirements.txt

# Copy all necessary code
COPY shared/ /app/shared/
COPY scrapers/utils/ /app/scrapers/utils/
COPY data_processors/analytics/ /app/data_processors/analytics/

# Set Python path and environment
ENV PYTHONPATH=/app:$PYTHONPATH
ENV PORT=8080
ENV SPORT=mlb

# Run the MLB Flask service with gunicorn
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 data_processors.analytics.mlb.main_mlb_analytics_service:app
