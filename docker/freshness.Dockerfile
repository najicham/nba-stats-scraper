FROM python:3.11-slim-bullseye
WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# COPY SHARED FIRST (needed by monitoring requirements)
COPY shared/requirements.txt /app/shared/

# Then copy freshness monitoring requirements
COPY monitoring/scrapers/freshness/requirements.txt /app/monitoring/scrapers/freshness/

# Install dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r /app/monitoring/scrapers/freshness/requirements.txt \
    && pip cache purge

# Copy rest of the code
COPY shared/ /app/shared/
COPY monitoring/scrapers/freshness/ /app/monitoring/scrapers/freshness/

ENV PYTHONPATH=/app:$PYTHONPATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app/monitoring/scrapers/freshness

ENTRYPOINT ["python", "runners/scheduled_monitor.py"]
