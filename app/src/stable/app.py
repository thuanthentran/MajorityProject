"""
Stable Version Service - Version 1.0
Service này mô phỏng phiên bản ổn định (stable) của ứng dụng.
Có error rate thấp và latency ổn định.
"""

from flask import Flask, jsonify, request as flask_request
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


def _wants_html():
        accept = flask_request.headers.get("Accept", "")
        return "text/html" in accept.lower()


def _render_html(payload, metrics):
        channel = "stable"
        color = "#2ec4b6" if channel == "stable" else "#ff9f1c"
        return f"""<!doctype html>
<html lang=\"en\">
    <head>
        <meta charset=\"utf-8\" />
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
        <title>Demo App - {channel.title()}</title>
        <style>
            :root {{
                --bg: #0f172a;
                --panel: #111827;
                --text: #e2e8f0;
                --muted: #94a3b8;
                --accent: {color};
            }}
            * {{ box-sizing: border-box; }}
            body {{
                margin: 0; font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
                background: radial-gradient(circle at top, #1f2937 0%, #0f172a 55%);
                color: var(--text);
            }}
            .wrap {{ max-width: 920px; margin: 48px auto; padding: 0 20px; }}
            .card {{
                background: var(--panel); border: 1px solid #1f2937; border-radius: 16px;
                padding: 24px; box-shadow: 0 20px 40px rgba(0,0,0,0.35);
            }}
            .badge {{
                display: inline-flex; align-items: center; gap: 8px; padding: 6px 12px;
                border-radius: 999px; background: rgba(255,255,255,0.08);
                font-size: 14px; color: var(--text);
            }}
            .dot {{ width: 10px; height: 10px; border-radius: 50%; background: var(--accent); }}
            h1 {{ margin: 12px 0 6px; font-size: 28px; }}
            .muted {{ color: var(--muted); }}
            .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-top: 20px; }}
            .stat {{ background: #0b1220; border: 1px solid #1f2937; border-radius: 12px; padding: 12px; }}
            .stat h3 {{ margin: 0 0 6px; font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }}
            .stat p {{ margin: 0; font-size: 20px; }}
            .footer {{ margin-top: 18px; font-size: 13px; color: var(--muted); }}
            .row {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 16px; }}
            .pill {{ padding: 6px 12px; border-radius: 999px; background: rgba(255,255,255,0.06); font-size: 13px; }}
        </style>
    </head>
    <body>
        <div class=\"wrap\">
            <div class=\"card\">
                <span class=\"badge\"><span class=\"dot\"></span>{channel.upper()} CHANNEL</span>
                <h1>Demo App - {payload.get("version", "unknown")}</h1>
                <p class=\"muted\">Status: <strong>{payload.get("status", "unknown")}</strong></p>
                <div class=\"row\">
                    <span class=\"pill\">Service: {payload.get("service", "demo-app")}</span>
                    <span class=\"pill\">Port: {os.getenv("PORT", "8080")}</span>
                </div>
                <div class=\"grid\">
                    <div class=\"stat\"><h3>Total Requests</h3><p>{metrics.get("total_requests", 0)}</p></div>
                    <div class=\"stat\"><h3>Error Rate</h3><p>{metrics.get("error_rate", 0.0)}</p></div>
                    <div class=\"stat\"><h3>Avg Latency (ms)</h3><p>{metrics.get("avg_latency_ms", 0.0)}</p></div>
                    <div class=\"stat\"><h3>Base Latency (ms)</h3><p>{BASE_LATENCY}</p></div>
                    <div class=\"stat\"><h3>Configured Error Rate</h3><p>{ERROR_RATE}</p></div>
                    <div class=\"stat\"><h3>Version</h3><p>{payload.get("version", "unknown")}</p></div>
                </div>
                <div class=\"footer\">Open /api/process for traffic, /metrics for JSON, /ui for this page.</div>
            </div>
        </div>
    </body>
</html>"""


def _compute_metrics():
        with lock:
                avg_latency = total_latency / request_count if request_count > 0 else 0
                current_error_rate = error_count / request_count if request_count > 0 else 0
        return {
                "version": VERSION,
                "total_requests": request_count,
                "error_count": error_count,
                "error_rate": round(current_error_rate, 6),
                "avg_latency_ms": round(avg_latency, 2)
        }


@app.route("/")
def home():
        payload = {
                "service": "demo-app",
                "version": VERSION,
                "status": "running"
        }
        if _wants_html():
                metrics_payload = _compute_metrics()
                return _render_html(payload, metrics_payload)
        return jsonify(payload)


@app.route("/ui")
def ui():
        payload = {
                "service": "demo-app",
                "version": VERSION,
                "status": "running"
        }
        metrics_payload = _compute_metrics()
        return _render_html(payload, metrics_payload)


@app.route("/api/info")
def api_info():
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
    return jsonify(_compute_metrics())


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
