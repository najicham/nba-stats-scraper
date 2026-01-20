# data_processors/analytics/Dockerfile
# Analytics Processor - Cloud Run Deployment
#
# Build from repository root to include shared/ module:
#   docker build -f data_processors/analytics/Dockerfile -t analytics-processor .
#
# Or use gcloud run deploy with --source from repo root

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy shared module from repository root (relative to build context)
COPY shared/ ./shared/

# Copy analytics processor code and dependencies
COPY data_processors/analytics/ ./data_processors/analytics/

# Set working directory to analytics for running the service
WORKDIR /app/data_processors/analytics

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Set Python path to include /app for shared module imports
ENV PYTHONPATH=/app:$PYTHONPATH

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=5)"

# Run service with gunicorn
# - Single worker process (Cloud Run handles scaling)
# - 4 threads for concurrent processing
# - 300s timeout for long-running analytics
# - Bind to PORT env var (Cloud Run default: 8080)
CMD exec gunicorn \
  --bind :${PORT:-8080} \
  --workers 1 \
  --threads 4 \
  --timeout 300 \
  --access-logfile - \
  --error-logfile - \
  --log-level info \
  main_analytics_service:app
