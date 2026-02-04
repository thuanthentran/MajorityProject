"""
Stable Version Service - Version 1.0
Service này mô phỏng phiên bản ổn định (stable) của ứng dụng.
Có error rate thấp và latency ổn định.
"""

from flask import Flask, jsonify
import random
import time
import os
import threading

app = Flask(__name__)

VERSION = os.getenv("APP_VERSION", "1.0-stable")
# Error rate thấp cho stable version (0.1% - 0.5%)
ERROR_RATE = float(os.getenv("ERROR_RATE", "0.002"))
# Base latency thấp (50-100ms)
BASE_LATENCY = float(os.getenv("BASE_LATENCY", "50"))

# Metrics tracking
request_count = 0
error_count = 0
total_latency = 0
lock = threading.Lock()


@app.route("/")
def home():
    return jsonify({
        "service": "demo-app",
        "version": VERSION,
        "status": "running"
    })


@app.route("/api/process")
def process():
    """
    Endpoint chính để xử lý request.
    Mô phỏng latency và error rate.
    """
    global request_count, error_count, total_latency
    
    with lock:
        request_count += 1
    
    # Simulate latency
    latency = BASE_LATENCY + random.uniform(0, 30)
    time.sleep(latency / 1000)  # Convert to seconds
    
    with lock:
        total_latency += latency
    
    # Simulate error
    if random.random() < ERROR_RATE:
        with lock:
            error_count += 1
        return jsonify({
            "error": "Internal Server Error",
            "version": VERSION
        }), 500
    
    return jsonify({
        "message": "Request processed successfully",
        "version": VERSION,
        "latency_ms": round(latency, 2)
    })


@app.route("/health")
def health():
    """Health check endpoint cho Kubernetes."""
    return jsonify({
        "status": "healthy",
        "version": VERSION
    })


@app.route("/ready")
def ready():
    """Readiness check endpoint cho Kubernetes."""
    return jsonify({
        "ready": True,
        "version": VERSION
    })


@app.route("/metrics")
def metrics():
    """
    Endpoint cung cấp metrics cho agent.
    Agent sẽ đọc metrics này để quyết định điều tiết traffic.
    """
    with lock:
        avg_latency = total_latency / request_count if request_count > 0 else 0
        current_error_rate = error_count / request_count if request_count > 0 else 0
    
    return jsonify({
        "version": VERSION,
        "total_requests": request_count,
        "error_count": error_count,
        "error_rate": round(current_error_rate, 6),
        "avg_latency_ms": round(avg_latency, 2)
    })


@app.route("/metrics/reset", methods=["POST"])
def reset_metrics():
    """Reset metrics về 0."""
    global request_count, error_count, total_latency
    with lock:
        request_count = 0
        error_count = 0
        total_latency = 0
    return jsonify({"message": "Metrics reset successfully"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    print(f"Starting {VERSION} on port {port}")
    app.run(host="0.0.0.0", port=port)
