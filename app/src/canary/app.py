"""
Canary Version Service - Version 2.0
Service này mô phỏng phiên bản mới (canary) của ứng dụng.
Có thể có scenario: healthy, buggy, degrading, flaky.
"""

from flask import Flask, jsonify, request as flask_request
import random
import time
import os
import threading

app = Flask(__name__)

VERSION = os.getenv("APP_VERSION", "2.0-canary")

# Scenario có thể thay đổi runtime qua API
SCENARIO = os.getenv("SCENARIO", "healthy")

# Metrics tracking  
request_count = 0
error_count = 0
total_latency = 0
start_time = time.time()
lock = threading.Lock()


def get_error_rate():
    """Tính error rate dựa trên scenario và traffic load."""
    global SCENARIO
    
    elapsed = time.time() - start_time
    time_factor = min(elapsed / 300, 1.0)
    
    if SCENARIO == "healthy":
        return 0.002 + random.uniform(0, 0.005)
    elif SCENARIO == "buggy":
        return 0.025 + random.uniform(0, 0.025)
    elif SCENARIO == "degrading":
        base = 0.003 + time_factor * 0.04
        return base + random.uniform(0, 0.01)
    else:  # flaky
        base = 0.002 + random.uniform(0, 0.02)
        if random.random() < 0.10:
            base += random.uniform(0.015, 0.035)
        return base


def get_latency():
    """Tính latency dựa trên scenario."""
    global SCENARIO
    
    if SCENARIO == "healthy":
        return 60 + random.uniform(0, 30)
    elif SCENARIO == "buggy":
        return 100 + random.uniform(0, 80)
    elif SCENARIO == "degrading":
        elapsed = time.time() - start_time
        time_factor = min(elapsed / 300, 1.0)
        return 60 + time_factor * 100 + random.uniform(0, 40)
    else:  # flaky
        base = 70 + random.uniform(0, 50)
        if random.random() < 0.05:
            base += random.uniform(100, 200)
        return base


@app.route("/")
def home():
    return jsonify({
        "service": "demo-app",
        "version": VERSION,
        "scenario": SCENARIO,
        "status": "running"
    })


@app.route("/api/process")
def process():
    """Endpoint chính để xử lý request."""
    global request_count, error_count, total_latency
    
    with lock:
        request_count += 1
    
    latency = get_latency()
    time.sleep(latency / 1000)
    
    with lock:
        total_latency += latency
    
    error_rate = get_error_rate()
    if random.random() < error_rate:
        with lock:
            error_count += 1
        return jsonify({
            "error": "Internal Server Error",
            "version": VERSION,
            "scenario": SCENARIO
        }), 500
    
    return jsonify({
        "message": "Request processed successfully",
        "version": VERSION,
        "scenario": SCENARIO,
        "latency_ms": round(latency, 2)
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "version": VERSION,
        "scenario": SCENARIO
    })


@app.route("/ready")
def ready():
    return jsonify({
        "ready": True,
        "version": VERSION,
        "scenario": SCENARIO
    })


@app.route("/metrics")
def metrics():
    with lock:
        avg_latency = total_latency / request_count if request_count > 0 else 0
        current_error_rate = error_count / request_count if request_count > 0 else 0
    
    return jsonify({
        "version": VERSION,
        "scenario": SCENARIO,
        "total_requests": request_count,
        "error_count": error_count,
        "error_rate": round(current_error_rate, 6),
        "avg_latency_ms": round(avg_latency, 2)
    })


@app.route("/metrics/reset", methods=["POST"])
def reset_metrics():
    global request_count, error_count, total_latency, start_time
    with lock:
        request_count = 0
        error_count = 0
        total_latency = 0
        start_time = time.time()
    return jsonify({"message": "Metrics reset successfully"})


@app.route("/scenario", methods=["GET"])
def get_scenario():
    return jsonify({"scenario": SCENARIO})


@app.route("/scenario", methods=["POST"])
def set_scenario():
    global SCENARIO, start_time
    data = flask_request.get_json() or {}
    new_scenario = data.get("scenario", "healthy")
    
    if new_scenario not in ["healthy", "buggy", "degrading", "flaky"]:
        return jsonify({
            "error": "Invalid scenario",
            "valid_scenarios": ["healthy", "buggy", "degrading", "flaky"]
        }), 400
    
    SCENARIO = new_scenario
    start_time = time.time()
    
    return jsonify({
        "message": f"Scenario changed to {SCENARIO}",
        "scenario": SCENARIO
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    print(f"Starting {VERSION} ({SCENARIO}) on port {port}")
    app.run(host="0.0.0.0", port=port)
