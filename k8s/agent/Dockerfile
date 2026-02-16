# Dockerfile cho Canary Agent
# NOTE: Bản chính là agent/Dockerfile (dùng bởi CI/CD).
# File này giữ lại cho local build / reference.
FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy controller code
COPY controller.py .

# Create models directory and copy model
RUN mkdir -p /app/models
COPY best_model.zip /app/models/ 
RUN apt-get update && apt-get install -y --no-install-recommends unzip && \
    cd /app/models && unzip -o best_model.zip && \
    rm -f best_model.zip && \
    apt-get remove -y unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Environment variables (must match agent/Dockerfile)
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

CMD ["python", "controller.py"]
