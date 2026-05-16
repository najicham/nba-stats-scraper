# NBA Admin Dashboard - Dockerfile
# Flask-based admin dashboard for pipeline monitoring

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy shared requirements first (layer caching)
COPY shared/requirements.txt /app/shared/
RUN pip install --no-cache-dir -r /app/shared/requirements.txt

# Install additional dashboard requirements
RUN pip install --no-cache-dir \
    flask>=2.3.0 \
    gunicorn>=21.0.0 \
    google-cloud-bigquery>=3.0.0 \
    google-cloud-firestore>=2.0.0 \
    google-cloud-logging>=3.0.0 \
    requests>=2.28.0

# Copy shared modules
COPY shared/ /app/shared/

# Copy dashboard service
COPY services/admin_dashboard/ /app/services/admin_dashboard/

# Run from repo root so `services` resolves to the top-level namespace package.
# Setting WORKDIR to /app/services/admin_dashboard previously caused Python to
# import the sibling /app/services/admin_dashboard/services/ subdir as the
# `services` package, shadowing the namespace package and breaking
# `from services.admin_dashboard...` imports in main.py.
WORKDIR /app

# Set Python path
ENV PYTHONPATH=/app:$PYTHONPATH
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run with gunicorn — qualify the module path now that WORKDIR is /app.
CMD exec gunicorn --bind :$PORT --workers 1 --threads 4 --timeout 120 services.admin_dashboard.main:app
