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
import psutil

app = Flask(__name__)

VERSION = os.getenv("APP_VERSION", "2.0-canary")

# Scenario có thể thay đổi runtime qua API
SCENARIO = os.getenv("SCENARIO", "healthy")

# Metrics tracking  
request_count = 0
error_count = 0
total_latency = 0
latency_values = []  # sliding window cho p95 calculation
MAX_LATENCY_WINDOW = 500  # giữ 500 latency gần nhất
start_time = time.time()
lock = threading.Lock()
_psutil_proc = psutil.Process(os.getpid())


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
        latency_values.append(latency)
        if len(latency_values) > MAX_LATENCY_WINDOW:
            latency_values.pop(0)
    
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
        # P95 latency từ sliding window
        if latency_values:
            sorted_lat = sorted(latency_values)
            p95_idx = int(len(sorted_lat) * 0.95)
            latency_p95 = sorted_lat[min(p95_idx, len(sorted_lat) - 1)]
        else:
            latency_p95 = 0.0

    # CPU & Memory usage của process hiện tại
    try:
        cpu_usage = _psutil_proc.cpu_percent(interval=None) / 100.0  # normalize [0,1]
        mem_info = _psutil_proc.memory_info()
        # Normalize memory: RSS / container limit (default 256Mi)
        mem_limit = int(os.getenv("MEMORY_LIMIT_BYTES", str(256 * 1024 * 1024)))
        memory_usage = mem_info.rss / mem_limit
    except Exception:
        cpu_usage = 0.0
        memory_usage = 0.0

    return jsonify({
        "version": VERSION,
        "scenario": SCENARIO,
        "total_requests": request_count,
        "error_count": error_count,
        "error_rate": round(current_error_rate, 6),
        "avg_latency_ms": round(avg_latency, 2),
        "latency_p95_ms": round(latency_p95, 2),
        "cpu_usage": round(min(cpu_usage, 1.0), 4),
        "memory_usage": round(min(memory_usage, 1.0), 4)
    })


@app.route("/metrics/reset", methods=["POST"])
def reset_metrics():
    global request_count, error_count, total_latency, start_time
    with lock:
        request_count = 0
        error_count = 0
        total_latency = 0
        latency_values.clear()
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
