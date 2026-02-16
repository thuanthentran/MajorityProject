# Dockerfile for Canary RL Agent
FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy controller code
COPY src/controller.py .

# Create models directory
RUN mkdir -p /app/models

# Copy trained model (will be added during CI/CD or mounted as volume)
# The model should be copied here during build or mounted at runtime
COPY models/ /app/models/

# Environment variables
ENV MODEL_PATH=/app/models/best_model
ENV STABLE_SERVICE=http://demo-app-stable:8080
ENV CANARY_SERVICE=http://demo-app-canary:8080
ENV PROMETHEUS_URL=http://prometheus:9090
ENV INGRESS_NAME=demo-app-ingress
ENV NAMESPACE=canary-demo
ENV STEP_INTERVAL=10
ENV MAX_STEPS=100
ENV SLO_LATENCY=200.0
ENV SLO_E2E_LATENCY=500.0
ENV WINDOW_SIZE=10

# Labels for versioning
ARG BUILD_DATE
ARG GIT_SHA
LABEL org.opencontainers.image.created="${BUILD_DATE}"
LABEL org.opencontainers.image.revision="${GIT_SHA}"
LABEL org.opencontainers.image.title="Canary RL Agent"
LABEL org.opencontainers.image.description="DQN-based agent for automated canary deployment"

CMD ["python", "controller.py"]
