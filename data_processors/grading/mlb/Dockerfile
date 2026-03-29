# data_processors/grading/mlb/Dockerfile
# MLB Grading Service - Cloud Run Deployment
#
# Builds from repository root to include shared dependencies

FROM python:3.11-slim

ARG BUILD_COMMIT=unknown
ARG BUILD_TIMESTAMP=unknown

ENV BUILD_COMMIT=${BUILD_COMMIT}
ENV BUILD_TIMESTAMP=${BUILD_TIMESTAMP}

LABEL build.commit="${BUILD_COMMIT}"
LABEL build.timestamp="${BUILD_TIMESTAMP}"

WORKDIR /app

# Install libgomp1 for CatBoost/LightGBM/XGBoost (OpenMP dependency)
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY shared/ ./shared/
COPY predictions/__init__.py ./predictions/__init__.py
COPY predictions/shared/ ./predictions/shared/
COPY data_processors/__init__.py ./data_processors/__init__.py
COPY data_processors/grading/ ./data_processors/grading/

WORKDIR /app/data_processors/grading/mlb

RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONPATH=/app:$PYTHONPATH

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=5)"

CMD exec gunicorn \
  --bind :${PORT:-8080} \
  --workers 1 \
  --threads 2 \
  --timeout 600 \
  --access-logfile - \
  --error-logfile - \
  --log-level info \
  main_mlb_grading_service:app
