"""
Canary Agent Controller
Chạy trong Kubernetes cluster để điều tiết traffic giữa stable và canary service.
Sử dụng trained DQN model để quyết định điều tiết.
"""

import os
import time
import requests
import numpy as np
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

# Constants from environment
MODEL_PATH = os.getenv("MODEL_PATH", "/app/models/best_model")
STABLE_SERVICE = os.getenv("STABLE_SERVICE", "http://demo-app-stable:8080")
CANARY_SERVICE = os.getenv("CANARY_SERVICE", "http://demo-app-canary:8080")
INGRESS_NAME = os.getenv("INGRESS_NAME", "demo-app-ingress")
NAMESPACE = os.getenv("NAMESPACE", "default")
STEP_INTERVAL = int(os.getenv("STEP_INTERVAL", "10"))
MAX_STEPS = int(os.getenv("MAX_STEPS", "100"))
SLO_LATENCY = float(os.getenv("SLO_LATENCY", "200.0"))


class CanaryController:
    def __init__(self):
        self.model = None
        self.traffic_v2 = 0.0
        self.step_count = 0
        self.max_steps = MAX_STEPS
        self.slo_latency = SLO_LATENCY
        
        # Kubernetes client
        try:
            config.load_incluster_config()
        except:
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
    
    def get_metrics(self, service_url):
        """Lấy metrics từ service."""
        try:
            response = requests.get(f"{service_url}/metrics", timeout=5)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.warning(f"Failed to get metrics from {service_url}: {e}")
        return None
    
    def get_observation(self):
        """
        Tạo observation vector cho agent.
        Format: [traffic_v2, error_rate, normalized_latency, time_progress]
        """
        canary_metrics = self.get_metrics(CANARY_SERVICE)
        
        if canary_metrics is None:
            error_rate = 0.0
            latency = 100.0
        else:
            error_rate = canary_metrics.get("error_rate", 0.0)
            latency = canary_metrics.get("avg_latency_ms", 100.0)
        
        max_latency = 500.0
        normalized_latency = min(latency / max_latency, 1.0)
        time_progress = self.step_count / self.max_steps
        
        obs = np.array([
            self.traffic_v2,
            error_rate,
            normalized_latency,
            time_progress
        ], dtype=np.float32)
        
        logger.info(f"Observation: traffic={self.traffic_v2:.2f}, error={error_rate:.4f}, "
                   f"latency={latency:.1f}ms, progress={time_progress:.2f}")
        
        return obs, error_rate, latency
    
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
        """Main control loop."""
        logger.info("=" * 50)
        logger.info("Starting Canary Agent Controller")
        logger.info("=" * 50)
        
        self.load_model()
        self.reset_canary_metrics()
        
        while self.step_count < self.max_steps:
            self.step_count += 1
            logger.info(f"\n--- Step {self.step_count}/{self.max_steps} ---")
            
            obs, error_rate, latency = self.get_observation()
            action, _ = self.model.predict(obs, deterministic=True)
            new_traffic = self.apply_action(action)
            
            # Check termination conditions
            if error_rate > 0.04:
                logger.error(f"CRITICAL: Error rate {error_rate:.2%} > 4% - Rolling back!")
                self.traffic_v2 = 0.0
                self._update_ingress_weights()
                break
            
            if new_traffic >= 1.0 and error_rate < 0.02 and latency < self.slo_latency:
                logger.info("SUCCESS: Canary rollout completed!")
                logger.info(f"Final traffic: {new_traffic:.0%}, Error: {error_rate:.2%}, Latency: {latency:.1f}ms")
                break
            
            time.sleep(STEP_INTERVAL)
        
        logger.info("=" * 50)
        logger.info("Canary Agent Controller finished")
        logger.info(f"Final state: traffic={self.traffic_v2:.0%}")
        logger.info("=" * 50)


if __name__ == "__main__":
    controller = CanaryController()
    controller.run()
