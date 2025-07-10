# scrapers/Dockerfile
# NBA Scrapers service - builds FROM base image
ARG PROJECT_ID
FROM nba-base

# Switch to root temporarily to install dependencies
USER root

# Copy scrapers-specific requirements and install
COPY scrapers/requirements.txt /app/scrapers/
RUN pip install --no-cache-dir -r scrapers/requirements.txt

# Copy the scrapers package and entry point
COPY scrapers/ /app/scrapers/
COPY scrapers/docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

# Note: .env files should be provided at runtime via docker-compose or deployment
# Don't copy .env files into the image for security

# Set ownership and switch back to non-root user
RUN chown -R appuser:appuser /app
USER appuser

# Expose port for scrapers service
EXPOSE 8080

# Health check for scrapers
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

# Use entrypoint script for flexibility
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Default to web service mode
CMD ["--serve"]