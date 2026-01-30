# reportgen/Dockerfile
# NBA Report Generator service - builds FROM base image
ARG PROJECT_ID
FROM nba-base

# Switch to root temporarily to install dependencies
USER root

# Copy reportgen-specific requirements and install
COPY reportgen/requirements.txt /app/reportgen/
RUN pip install --no-cache-dir -r reportgen/requirements.txt

# Copy the reportgen package and entry point
COPY reportgen/ /app/reportgen/
COPY reportgen/docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

# Set ownership and switch back to non-root user
RUN chown -R appuser:appuser /app
USER appuser

# Expose port for reportgen service
EXPOSE 8082

# Health check for reportgen
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8082/health || exit 1

# Use entrypoint script for flexibility
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Default to web service mode
CMD ["--serve"]