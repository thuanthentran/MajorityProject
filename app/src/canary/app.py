"""
Canary Version Service - Version 2.0
Service này mô phỏng phiên bản mới (canary) của ứng dụng.
Có thể có scenario: healthy, buggy, degrading, flaky.
"""

from flask import Flask, jsonify, request as flask_request, Response
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


def _wants_html():
        accept = flask_request.headers.get("Accept", "")
        return "text/html" in accept.lower()


def _render_html(payload, metrics):
        channel = "canary"
        color = "#ff9f1c" if channel == "canary" else "#2ec4b6"
        scenario = payload.get("scenario", "unknown")
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
                <p class=\"muted\">Scenario: <strong>{scenario}</strong> | Status: <strong>{payload.get("status", "unknown")}</strong></p>
                <div class=\"row\">
                    <span class=\"pill\">Service: {payload.get("service", "demo-app")}</span>
                    <span class=\"pill\">Port: {os.getenv("PORT", "8080")}</span>
                </div>
                <div class=\"grid\">
                    <div class=\"stat\"><h3>Total Requests</h3><p>{metrics.get("total_requests", 0)}</p></div>
                    <div class=\"stat\"><h3>Error Rate</h3><p>{metrics.get("error_rate", 0.0)}</p></div>
                    <div class=\"stat\"><h3>Avg Latency (ms)</h3><p>{metrics.get("avg_latency_ms", 0.0)}</p></div>
                    <div class=\"stat\"><h3>P95 Latency (ms)</h3><p>{metrics.get("latency_p95_ms", 0.0)}</p></div>
                    <div class=\"stat\"><h3>CPU Usage</h3><p>{metrics.get("cpu_usage", 0.0)}</p></div>
                    <div class=\"stat\"><h3>Memory Usage</h3><p>{metrics.get("memory_usage", 0.0)}</p></div>
                </div>
                <div class=\"footer\">Open /api/process for traffic, /metrics for Prometheus, /metrics/json for JSON, /ui for this page.</div>
            </div>
        </div>
    </body>
</html>"""


def _render_traffic_html():
        return """<!doctype html>
<html lang="en">
    <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Traffic Split Demo</title>
        <style>
            :root {
                --bg: #0f172a;
                --panel: #111827;
                --text: #e2e8f0;
                --muted: #94a3b8;
                --stable: #2ec4b6;
                --canary: #ff9f1c;
            }
            * { box-sizing: border-box; }
            body {
                margin: 0; font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
                background: radial-gradient(circle at top, #1f2937 0%, #0f172a 55%);
                color: var(--text);
            }
            .wrap { max-width: 920px; margin: 48px auto; padding: 0 20px; }
            .card {
                background: var(--panel); border: 1px solid #1f2937; border-radius: 16px;
                padding: 24px; box-shadow: 0 20px 40px rgba(0,0,0,0.35);
            }
            h1 { margin: 0 0 8px; font-size: 28px; }
            .muted { color: var(--muted); }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-top: 20px; }
            .stat { background: #0b1220; border: 1px solid #1f2937; border-radius: 12px; padding: 12px; }
            .stat h3 { margin: 0 0 6px; font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }
            .stat p { margin: 0; font-size: 20px; }
            .bar { height: 10px; border-radius: 999px; background: #0b1220; border: 1px solid #1f2937; overflow: hidden; }
            .bar > div { height: 100%; }
            .bar .stable { background: var(--stable); }
            .bar .canary { background: var(--canary); }
            .row { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 14px; }
            .pill { padding: 6px 12px; border-radius: 999px; background: rgba(255,255,255,0.06); font-size: 13px; }
        </style>
    </head>
    <body>
        <div class="wrap">
            <div class="card">
                <h1>Traffic Split Demo</h1>
                <p class="muted">This page sends requests to /api/process and counts which version handled them.</p>
                <div class="row">
                    <span class="pill">Endpoint: /api/process</span>
                    <span class="pill">Interval: 500ms</span>
                    <span class="pill">Host: same as this page</span>
                </div>
                <div class="grid">
                    <div class="stat"><h3>Stable</h3><p id="stableCount">0</p></div>
                    <div class="stat"><h3>Canary</h3><p id="canaryCount">0</p></div>
                    <div class="stat"><h3>Total</h3><p id="totalCount">0</p></div>
                    <div class="stat"><h3>Last Version</h3><p id="lastVersion">-</p></div>
                </div>
                <div style="margin-top:16px;">
                    <div class="bar">
                        <div class="stable" id="stableBar" style="width: 50%"></div>
                    </div>
                    <div class="bar" style="margin-top:8px;">
                        <div class="canary" id="canaryBar" style="width: 50%"></div>
                    </div>
                </div>
            </div>
        </div>
        <script>
            const stableCountEl = document.getElementById("stableCount");
            const canaryCountEl = document.getElementById("canaryCount");
            const totalCountEl = document.getElementById("totalCount");
            const lastVersionEl = document.getElementById("lastVersion");
            const stableBarEl = document.getElementById("stableBar");
            const canaryBarEl = document.getElementById("canaryBar");

            let stable = 0;
            let canary = 0;

            function updateBars() {
                const total = stable + canary;
                const stablePct = total ? (stable / total) * 100 : 50;
                const canaryPct = total ? (canary / total) * 100 : 50;
                stableBarEl.style.width = stablePct.toFixed(1) + "%";
                canaryBarEl.style.width = canaryPct.toFixed(1) + "%";
                stableCountEl.textContent = stable;
                canaryCountEl.textContent = canary;
                totalCountEl.textContent = total;
            }

            async function tick() {
                try {
                    const res = await fetch("/api/process", { cache: "no-store" });
                    const data = await res.json();
                    const version = (data.version || "").toLowerCase();
                    if (version.includes("stable")) {
                        stable += 1;
                        lastVersionEl.textContent = "stable";
                    } else if (version.includes("canary")) {
                        canary += 1;
                        lastVersionEl.textContent = "canary";
                    } else {
                        lastVersionEl.textContent = version || "unknown";
                    }
                    updateBars();
                } catch (err) {
                    lastVersionEl.textContent = "error";
                }
            }

            updateBars();
            setInterval(tick, 500);
        </script>
    </body>
</html>"""


def _compute_metrics():
        with lock:
                avg_latency = total_latency / request_count if request_count > 0 else 0
                current_error_rate = error_count / request_count if request_count > 0 else 0
                if latency_values:
                        sorted_lat = sorted(latency_values)
                        p95_idx = int(len(sorted_lat) * 0.95)
                        latency_p95 = sorted_lat[min(p95_idx, len(sorted_lat) - 1)]
                else:
                        latency_p95 = 0.0

        try:
                cpu_usage = _psutil_proc.cpu_percent(interval=None) / 100.0
                mem_info = _psutil_proc.memory_info()
                mem_limit = int(os.getenv("MEMORY_LIMIT_BYTES", str(256 * 1024 * 1024)))
                memory_usage = mem_info.rss / mem_limit
        except Exception:
                cpu_usage = 0.0
                memory_usage = 0.0

        return {
                "version": VERSION,
                "scenario": SCENARIO,
                "total_requests": request_count,
                "error_count": error_count,
                "error_rate": round(current_error_rate, 6),
                "avg_latency_ms": round(avg_latency, 2),
                "latency_p95_ms": round(latency_p95, 2),
                "cpu_usage": round(min(cpu_usage, 1.0), 4),
                "memory_usage": round(min(memory_usage, 1.0), 4)
        }


def _escape_label_value(value):
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace("\"", "\\\"")


def _format_prometheus_metrics(metrics):
    channel = "canary"
    version = _escape_label_value(metrics.get("version", "unknown"))
    scenario = _escape_label_value(metrics.get("scenario", "unknown"))
    labels = f'version="{version}",channel="{channel}",scenario="{scenario}"'
    lines = [
        "# HELP demo_app_info App metadata.",
        "# TYPE demo_app_info gauge",
        f"demo_app_info{{{labels}}} 1",
        "# HELP demo_requests_total Total number of requests.",
        "# TYPE demo_requests_total counter",
        f"demo_requests_total{{channel=\"{channel}\"}} {metrics.get('total_requests', 0)}",
        "# HELP demo_request_errors_total Total number of error responses.",
        "# TYPE demo_request_errors_total counter",
        f"demo_request_errors_total{{channel=\"{channel}\"}} {metrics.get('error_count', 0)}",
        "# HELP demo_request_error_rate Error rate for requests.",
        "# TYPE demo_request_error_rate gauge",
        f"demo_request_error_rate{{channel=\"{channel}\"}} {metrics.get('error_rate', 0.0)}",
        "# HELP demo_request_latency_avg_ms Average request latency in milliseconds.",
        "# TYPE demo_request_latency_avg_ms gauge",
        f"demo_request_latency_avg_ms{{channel=\"{channel}\"}} {metrics.get('avg_latency_ms', 0.0)}",
        "# HELP demo_request_latency_p95_ms P95 request latency in milliseconds.",
        "# TYPE demo_request_latency_p95_ms gauge",
        f"demo_request_latency_p95_ms{{channel=\"{channel}\"}} {metrics.get('latency_p95_ms', 0.0)}",
        "# HELP demo_request_latency_sum_ms Total accumulated latency in milliseconds.",
        "# TYPE demo_request_latency_sum_ms counter",
        f"demo_request_latency_sum_ms{{channel=\"{channel}\"}} {round(total_latency, 2)}",
        "# HELP demo_cpu_usage CPU usage ratio.",
        "# TYPE demo_cpu_usage gauge",
        f"demo_cpu_usage{{channel=\"{channel}\"}} {metrics.get('cpu_usage', 0.0)}",
        "# HELP demo_memory_usage Memory usage ratio.",
        "# TYPE demo_memory_usage gauge",
        f"demo_memory_usage{{channel=\"{channel}\"}} {metrics.get('memory_usage', 0.0)}",
    ]
    return "\n".join(lines) + "\n"

@app.route("/")
def home():
        payload = {
                "service": "demo-app",
                "version": VERSION,
                "scenario": SCENARIO,
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
                "scenario": SCENARIO,
                "status": "running"
        }
        metrics_payload = _compute_metrics()
        return _render_html(payload, metrics_payload)


@app.route("/traffic")
def traffic():
    return _render_traffic_html()


@app.route("/api/info")
def api_info():
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
    """Prometheus metrics endpoint."""
    payload = _format_prometheus_metrics(_compute_metrics())
    return Response(payload, status=200, mimetype="text/plain")


@app.route("/metrics/json")
def metrics_json():
    """JSON metrics endpoint for internal agents."""
    return jsonify(_compute_metrics())


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
