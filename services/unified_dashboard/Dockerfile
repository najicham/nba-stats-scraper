# Unified Dashboard Dockerfile
# Builds both backend and frontend for Cloud Run deployment

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install Node.js for frontend build
RUN apt-get update && apt-get install -y \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements and install
COPY services/unified_dashboard/backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend code
COPY services/unified_dashboard/backend /app/backend

# Copy frontend code and build
COPY services/unified_dashboard/frontend /app/frontend
WORKDIR /app/frontend
RUN if [ -f package.json ]; then npm install && npm run build; fi

# Set working directory back to backend
WORKDIR /app/backend

# Environment variables
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8080

# Run FastAPI with uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
