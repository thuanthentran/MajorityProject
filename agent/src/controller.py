"""
Canary Agent Controller (Microservice Cluster – Context Window)

Chạy trong Kubernetes cluster để điều tiết traffic giữa stable và canary service.
Sử dụng trained DQN model (context-window) để quyết định điều tiết.

Metrics:
  Local (canary pod):  error_rate_v2, latency_p95_v2, cpu_usage_v2, memory_usage_v2
  Global (cluster):    total_error_rate, end_to_end_latency, request_rate, traffic_v2
"""

import os
import time
import requests
import numpy as np
from collections import deque
from stable_baselines3 import DQN
from kubernetes import client, config
import logging
import json

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ---- Constants from environment variables ----
MODEL_PATH = os.getenv("MODEL_PATH", "/app/models/best_model")
STABLE_SERVICE = os.getenv("STABLE_SERVICE", "http://demo-app-stable:8080")
CANARY_SERVICE = os.getenv("CANARY_SERVICE", "http://demo-app-canary:8080")
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
INGRESS_NAME = os.getenv("INGRESS_NAME", "demo-app-ingress")
NAMESPACE = os.getenv("NAMESPACE", "default")
STEP_INTERVAL = int(os.getenv("STEP_INTERVAL", "10"))
MAX_STEPS = int(os.getenv("MAX_STEPS", "100"))
SLO_LATENCY = float(os.getenv("SLO_LATENCY", "200.0"))
SLO_E2E_LATENCY = float(os.getenv("SLO_E2E_LATENCY", "500.0"))
WINDOW_SIZE = int(os.getenv("WINDOW_SIZE", "10"))
NUM_METRICS = 8  # phải trùng với CanaryEnv.NUM_METRICS

# Normalization constants (phải trùng với training env)
MAX_LOCAL_LATENCY = 500.0
MAX_E2E_LATENCY = 1000.0


class CanaryController:
    def __init__(self):
        self.model = None
        self.traffic_v2 = 0.0
        self.step_count = 0
        self.max_steps = MAX_STEPS
        self.slo_latency = SLO_LATENCY
        self.slo_e2e_latency = SLO_E2E_LATENCY

        # Context window buffer
        self.window_size = WINDOW_SIZE
        self._obs_buffer = deque(maxlen=self.window_size)

        # Kubernetes client
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()

        self.networking_v1 = client.NetworkingV1Api()
        self.core_v1 = client.CoreV1Api()

    def load_model(self):
        """Load trained DQN model."""
        logger.info(f"Loading model from {MODEL_PATH}")
        try:
            self.model = DQN.load(MODEL_PATH)
            logger.info("Model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise

    # ============================================================
    #                  METRIC COLLECTION
    # ============================================================

    def _query_prometheus(self, query):
        """Query Prometheus and return float value."""
        try:
            resp = requests.get(
                f"{PROMETHEUS_URL}/api/v1/query",
                params={"query": query},
                timeout=5,
            )
            data = resp.json()
            if data["status"] == "success" and data["data"]["result"]:
                return float(data["data"]["result"][0]["value"][1])
        except Exception as e:
            logger.warning(f"Prometheus query failed: {query!r} -> {e}")
        return None

    def get_canary_metrics(self):
        """Lấy metrics từ canary service (local metrics)."""
        try:
            response = requests.get(f"{CANARY_SERVICE}/metrics", timeout=5)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.warning(f"Failed to get canary metrics: {e}")
        return None

    def get_cluster_metrics(self):
        """
        Lấy global metrics từ Prometheus hoặc cluster monitoring.
        Trả về dict: total_error_rate, end_to_end_latency, request_rate.
        """
        metrics = {}

        # Total error rate (cluster-wide)
        val = self._query_prometheus(
            'sum(rate(http_requests_total{code=~"5.."}[1m])) / sum(rate(http_requests_total[1m]))'
        )
        metrics["total_error_rate"] = val if val is not None else 0.005

        # End-to-end latency (ms)
        val = self._query_prometheus(
            'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[1m])) by (le)) * 1000'
        )
        metrics["end_to_end_latency"] = val if val is not None else 250.0

        # Request rate (rps, normalized later)
        val = self._query_prometheus(
            'sum(rate(http_requests_total[1m]))'
        )
        metrics["request_rate"] = val if val is not None else 100.0

        return metrics

    # ============================================================
    #                  OBSERVATION
    # ============================================================

    def _build_single_obs(
        self,
        error_rate_v2=0.0,
        latency_p95_v2=100.0,
        cpu_usage_v2=0.05,
        memory_usage_v2=0.10,
        total_error_rate=0.005,
        end_to_end_latency=250.0,
        request_rate=0.5,
    ):
        """Build normalized 8-dim observation for 1 timestep."""
        return np.array([
            np.clip(error_rate_v2, 0.0, 1.0),
            np.clip(latency_p95_v2 / MAX_LOCAL_LATENCY, 0.0, 1.0),
            np.clip(cpu_usage_v2, 0.0, 1.0),
            np.clip(memory_usage_v2, 0.0, 1.0),
            np.clip(total_error_rate, 0.0, 1.0),
            np.clip(end_to_end_latency / MAX_E2E_LATENCY, 0.0, 1.0),
            np.clip(request_rate, 0.0, 1.0),  # đã normalized ở caller
            np.clip(self.traffic_v2, 0.0, 1.0),
        ], dtype=np.float32)

    def get_observation(self):
        """
        Thu thập metrics, build single obs, push vào buffer,
        trả về flattened context window.
        """
        # --- Local metrics (canary pod) ---
        canary = self.get_canary_metrics()
        if canary is None:
            error_rate_v2 = 0.0
            latency_p95_v2 = 100.0
            cpu_usage_v2 = 0.05
            memory_usage_v2 = 0.10
        else:
            error_rate_v2 = canary.get("error_rate", 0.0)
            latency_p95_v2 = canary.get("latency_p95_ms", canary.get("avg_latency_ms", 100.0))
            cpu_usage_v2 = canary.get("cpu_usage", 0.05)
            memory_usage_v2 = canary.get("memory_usage", 0.10)

        # --- Global metrics (cluster) ---
        cluster = self.get_cluster_metrics()
        total_error_rate = cluster["total_error_rate"]
        end_to_end_latency = cluster["end_to_end_latency"]
        # Normalize request_rate: giả sử max ~200 rps → [0,1]
        raw_rps = cluster["request_rate"]
        request_rate = min(raw_rps / 200.0, 1.0)

        single = self._build_single_obs(
            error_rate_v2, latency_p95_v2, cpu_usage_v2, memory_usage_v2,
            total_error_rate, end_to_end_latency, request_rate,
        )
        self._obs_buffer.append(single)

        # Flatten context window
        obs = np.concatenate(list(self._obs_buffer)).astype(np.float32)

        logger.info(
            f"Obs (latest): err={error_rate_v2:.4f} p95={latency_p95_v2:.1f}ms "
            f"cpu={cpu_usage_v2:.2f} mem={memory_usage_v2:.2f} | "
            f"gErr={total_error_rate:.4f} e2e={end_to_end_latency:.1f}ms "
            f"rr={request_rate:.2f} traf={self.traffic_v2:.2f}"
        )

        return obs, error_rate_v2, latency_p95_v2, total_error_rate, end_to_end_latency
    
    def apply_action(self, action):
        """
        Thực thi action từ agent.
        0: HOLD - giữ nguyên
        1: UP - tăng traffic canary
        2: DOWN - giảm traffic canary (rollback)
        """
        action_names = ["HOLD", "UP", "DOWN"]
        logger.info(f"Action: {action_names[action]}")

        if action == 1:  # UP
            self.traffic_v2 = min(1.0, self.traffic_v2 + 0.1)
        elif action == 2:  # DOWN
            self.traffic_v2 = max(0.0, self.traffic_v2 - 0.1)

        self._update_ingress_weights()
        return self.traffic_v2

    def _update_ingress_weights(self):
        """Cập nhật traffic weights trong Ingress annotations."""
        canary_weight = int(self.traffic_v2 * 100)

        logger.info(f"Updating ingress weights: stable={100-canary_weight}%, canary={canary_weight}%")

        try:
            body = {
                "metadata": {
                    "annotations": {
                        "nginx.ingress.kubernetes.io/canary-weight": str(canary_weight)
                    }
                }
            }

            self.networking_v1.patch_namespaced_ingress(
                name=f"{INGRESS_NAME}-canary",
                namespace=NAMESPACE,
                body=body
            )
            logger.info(f"Ingress updated: canary weight = {canary_weight}%")

        except Exception as e:
            logger.error(f"Failed to update ingress: {e}")

    def reset_canary_metrics(self):
        """Reset metrics của canary service."""
        try:
            requests.post(f"{CANARY_SERVICE}/metrics/reset", timeout=5)
            logger.info("Canary metrics reset")
        except Exception as e:
            logger.warning(f"Failed to reset canary metrics: {e}")

    def run(self):
        """Main control loop với context window."""
        logger.info("=" * 60)
        logger.info("Starting Canary Agent Controller (Context Window)")
        logger.info(f"  Window size    : {self.window_size}")
        logger.info(f"  Max steps      : {self.max_steps}")
        logger.info(f"  SLO latency    : {self.slo_latency}ms")
        logger.info(f"  SLO e2e latency: {self.slo_e2e_latency}ms")
        logger.info("=" * 60)

        self.load_model()
        self.reset_canary_metrics()

        # Khởi tạo buffer với zero-observations
        self._obs_buffer.clear()
        zero_obs = self._build_single_obs()
        for _ in range(self.window_size):
            self._obs_buffer.append(zero_obs)

        while self.step_count < self.max_steps:
            self.step_count += 1
            logger.info(f"\n--- Step {self.step_count}/{self.max_steps} ---")

            obs, error_rate_v2, latency_p95, total_error_rate, e2e_latency = self.get_observation()
            action, _ = self.model.predict(obs, deterministic=True)
            new_traffic = self.apply_action(action)

            # Check termination: canary error critical
            if error_rate_v2 > 0.04:
                logger.error(f"CRITICAL: Canary error {error_rate_v2:.2%} > 4% - Rolling back!")
                self.traffic_v2 = 0.0
                self._update_ingress_weights()
                break

            # Check termination: cluster cascade failure
            if total_error_rate > 0.06:
                logger.error(f"CRITICAL: Cluster error {total_error_rate:.2%} > 6% - Rolling back!")
                self.traffic_v2 = 0.0
                self._update_ingress_weights()
                break

            # Check success
            if (new_traffic >= 1.0
                    and error_rate_v2 < 0.02
                    and latency_p95 < self.slo_latency
                    and total_error_rate < 0.03):
                logger.info("SUCCESS: Canary rollout completed!")
                logger.info(
                    f"Final: traffic={new_traffic:.0%} err={error_rate_v2:.2%} "
                    f"p95={latency_p95:.1f}ms gErr={total_error_rate:.2%} "
                    f"e2e={e2e_latency:.1f}ms"
                )
                break

            time.sleep(STEP_INTERVAL)

        logger.info("=" * 60)
        logger.info("Canary Agent Controller finished")
        logger.info(f"Final state: traffic={self.traffic_v2:.0%}")
        logger.info("=" * 60)


if __name__ == "__main__":
    controller = CanaryController()
    controller.run()
