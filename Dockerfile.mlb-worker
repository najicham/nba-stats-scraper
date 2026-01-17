# docker/mlb-prediction-worker.Dockerfile
#
# MLB Pitcher Strikeouts Prediction Worker
# XGBoost-based prediction service for MLB pitcher strikeout totals.

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install shared requirements
COPY shared/requirements.txt /app/shared/requirements.txt
RUN pip install --no-cache-dir -r /app/shared/requirements.txt

# Install MLB-specific dependencies
RUN pip install --no-cache-dir \
    xgboost>=1.7.0 \
    flask>=2.3.0 \
    gunicorn>=21.0.0

# Copy shared utilities
COPY shared/ /app/shared/

# Copy MLB prediction module
COPY predictions/__init__.py /app/predictions/__init__.py
COPY predictions/mlb/ /app/predictions/mlb/

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV GCP_PROJECT_ID=nba-props-platform
ENV MLB_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_20260107.json
ENV MLB_PREDICTIONS_TABLE=mlb_predictions.pitcher_strikeouts

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run with gunicorn
CMD exec gunicorn --bind :$PORT --workers 1 --threads 4 --timeout 300 predictions.mlb.worker:app
