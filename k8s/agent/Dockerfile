# Dockerfile cho Canary Agent
FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy controller code
COPY controller.py .

# Create models directory and copy model
RUN mkdir -p /app/models
COPY canary_dqn_agent.zip /app/models/

# Unzip model
RUN apt-get update && apt-get install -y unzip && \
    cd /app/models && unzip -o canary_dqn_agent.zip && \
    rm canary_dqn_agent.zip && \
    apt-get remove -y unzip && apt-get autoremove -y

# Environment variables
ENV MODEL_PATH=/app/models/best_model
ENV STABLE_SERVICE=http://demo-app-stable:8080
ENV CANARY_SERVICE=http://demo-app-canary:8080
ENV INGRESS_NAME=demo-app-ingress
ENV NAMESPACE=canary-demo
ENV STEP_INTERVAL=10
ENV MAX_STEPS=100
ENV SLO_LATENCY=200.0

CMD ["python", "controller.py"]
