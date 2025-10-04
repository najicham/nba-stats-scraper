FROM python:3.11-slim-bullseye

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# COPY SHARED FIRST (needed by monitoring requirements)
COPY shared/requirements.txt /app/shared/

# Then copy monitoring requirements
COPY monitoring/processing_gap_detection/requirements.txt /app/monitoring/processing_gap_detection/

# Install dependencies (now -r ../../shared/requirements.txt works)
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r /app/monitoring/processing_gap_detection/requirements.txt \
    && pip cache purge

# Copy rest of the code
COPY shared/ /app/shared/
COPY monitoring/processing_gap_detection/ /app/monitoring/processing_gap_detection/

ENV PYTHONPATH=/app:$PYTHONPATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app/monitoring/processing_gap_detection

ENTRYPOINT ["python", "processing_gap_monitor_job.py"]