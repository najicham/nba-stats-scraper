# predictions/coordinator/Dockerfile
# Prediction Coordinator - Cloud Run Deployment
#
# Builds from repository root to include shared dependencies

FROM python:3.11-slim

WORKDIR /app

# Copy shared modules from repository root
COPY shared/ ./shared/

# Copy predictions package structure
COPY predictions/__init__.py ./predictions/__init__.py

# Copy coordinator code
COPY predictions/coordinator/ ./predictions/coordinator/

# Set working directory to coordinator
WORKDIR /app/predictions/coordinator

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Set Python path to include /app for shared module imports
ENV PYTHONPATH=/app:$PYTHONPATH

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=5)"

# Run with gunicorn
CMD exec gunicorn \
  --bind :${PORT:-8080} \
  --workers 1 \
  --threads 8 \
  --timeout 300 \
  --access-logfile - \
  --error-logfile - \
  --log-level info \
  coordinator:app
