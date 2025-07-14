# scrapers/Dockerfile
# Simple self-contained version for Cloud Run deployment

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application code
COPY . .

# Set Python path for imports
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8080

# Run the Flask application directly
CMD exec python main_scraper_service.py --port ${PORT:-8080} --host 0.0.0.0
