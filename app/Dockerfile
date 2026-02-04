# Multi-stage Dockerfile for App Service
# Supports both stable and canary versions via build args

FROM python:3.10-slim

# Build arguments
ARG APP_TYPE=stable
ARG APP_VERSION=1.0

WORKDIR /app

# Install dependencies
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the appropriate app version
COPY src/${APP_TYPE}/app.py .

# Environment variables
ENV PORT=8080
ENV APP_VERSION=${APP_VERSION}
ENV ERROR_RATE=0.002
ENV BASE_LATENCY=50
ENV SCENARIO=healthy

EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8080/health || exit 1

# Run with gunicorn for production
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", "--access-logfile", "-", "app:app"]
