# scrapers/Dockerfile
# NBA Scrapers Service - Cloud Run Deployment
#
# Build from repository root to include shared/ module:
#   docker build -f scrapers/Dockerfile -t nba-scrapers .
#
# Or use the deployment script:
#   ./bin/deploy-service.sh nba-scrapers

FROM python:3.11-slim

# Build-time arguments for tracking what code is in this image
ARG BUILD_COMMIT=unknown
ARG BUILD_TIMESTAMP=unknown

# Store build info as environment variables (queryable at runtime)
ENV BUILD_COMMIT=${BUILD_COMMIT}
ENV BUILD_TIMESTAMP=${BUILD_TIMESTAMP}

# Add labels for image inspection
LABEL build.commit="${BUILD_COMMIT}"
LABEL build.timestamp="${BUILD_TIMESTAMP}"

# Set working directory
WORKDIR /app

# Install system dependencies needed for scrapers + Playwright Chromium
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    libpq-dev \
    # Playwright Chromium dependencies (Trixie-compatible, no ttf-unifont/ttf-ubuntu-font-family)
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libgomp1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    fonts-liberation \
    fonts-unifont \
    && rm -rf /var/lib/apt/lists/*

# Copy ONLY requirements first (cached layer - deps rarely change)
COPY shared/requirements.txt ./shared/requirements.txt
COPY scrapers/requirements-lock.txt ./scrapers/requirements-lock.txt

# Install dependencies before copying code (code changes don't bust pip cache)
RUN pip install --no-cache-dir -r shared/requirements.txt
RUN pip install --no-cache-dir -r scrapers/requirements-lock.txt

# Install Playwright Chromium binary (system deps installed above)
RUN python -m playwright install chromium

# Now copy all source code
COPY shared/ ./shared/

# Copy orchestration module (needed for config_loader import in health.py)
COPY orchestration/ ./orchestration/

# Copy config directory (needed for workflows.yaml)
COPY config/ ./config/

# Copy scrapers code
COPY scrapers/ ./scrapers/

# Set Python path to find modules
ENV PYTHONPATH=/app:$PYTHONPATH
ENV PORT=8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:${PORT}/health || exit 1

# Run the scraper service
CMD exec gunicorn \
  --bind :${PORT} \
  --workers 1 \
  --threads 8 \
  --timeout 300 \
  --access-logfile - \
  --error-logfile - \
  --log-level info \
  scrapers.main_scraper_service:app
