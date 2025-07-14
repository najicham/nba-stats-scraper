FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl gcc g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY scrapers/requirements.txt ./scrapers/
RUN pip install --no-cache-dir -r scrapers/requirements.txt

# Copy scrapers module (preserves import structure)
COPY scrapers/ ./scrapers/

# Set Python path
ENV PYTHONPATH=/app

EXPOSE 8080

# Run script - now scrapers.scraper_base imports will work!
CMD exec python scrapers/main_scraper_service.py --port ${PORT:-8080} --host 0.0.0.0
