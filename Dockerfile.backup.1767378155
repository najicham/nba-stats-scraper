# data_processors/raw/Dockerfile
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

# Copy raw processor requirements
COPY data_processors/raw/requirements.txt /app/data_processors/raw/
RUN pip install --no-cache-dir -r /app/data_processors/raw/requirements.txt

# Copy all necessary code
COPY shared/ /app/shared/
COPY scrapers/utils/ /app/scrapers/utils/
COPY data_processors/raw/ /app/data_processors/raw/

# Set Python path
ENV PYTHONPATH=/app:$PYTHONPATH
ENV PORT=8080

# Run the Flask service with gunicorn
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 data_processors.raw.main_processor_service:app