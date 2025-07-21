# scrapers/Dockerfile - Clean Production Version
# NBA Analytics Scrapers Service
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy and install shared dependencies first (changes less frequently)
COPY shared/requirements.txt ./shared/
RUN pip install --no-cache-dir -r shared/requirements.txt

# Copy and install scraper-specific dependencies
COPY scrapers/requirements.txt ./scrapers/
RUN pip install --no-cache-dir -r scrapers/requirements.txt

# Copy shared utilities (needed for imports)
COPY shared/ ./shared/

# Copy scrapers module (preserves clean import structure)
COPY scrapers/ ./scrapers/

# Set Python path for proper imports
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

# Run the main scraper service
CMD exec python scrapers/main_scraper_service.py --port ${PORT:-8080} --host 0.0.0.0
