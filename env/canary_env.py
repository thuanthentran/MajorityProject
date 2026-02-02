import gymnasium as gym
import numpy as np
from gymnasium import spaces

class CanaryEnv(gym.Env):
    def __init__(self, force_scenario=None):
        """
        Args:
            force_scenario: Nếu được set, sẽ luôn dùng scenario này thay vì random.
                           Options: "healthy", "buggy", "degrading", "flaky", None (random)
        """
        super().__init__()

        # rollout params
        self.max_steps = 100  # Tăng từ 30 lên 100
        self.step_count = 0

        self.traffic_v2 = 0.0
        self.base_latency = 100.0
        self.slo_latency = 200.0
        
        # Scenario type cho mỗi episode
        # Giúp agent học các pattern khác nhau thay vì chỉ random
        self.force_scenario = force_scenario
        self.scenario = force_scenario if force_scenario else "healthy"

        # action: hold / up / down
        self.action_space = spaces.Discrete(3)

        # state (tất cả đã normalize về [0, 1])
        self.observation_space = spaces.Box(
            low=np.array([0.0, 0.0, 0.0, 0.0]),
            high=np.array([1.0, 1.0, 1.0, 1.0]),
            dtype=np.float32
        )

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.step_count = 0
        self.traffic_v2 = 0.0
        
        # Nếu force_scenario được set, dùng nó; ngược lại random
        if self.force_scenario:
            self.scenario = self.force_scenario
        else:
            # Random scenario cho mỗi episode
            # - healthy (60%): canary tốt, error thấp ổn định
            # - buggy (20%): có bug, error cao từ đầu
            # - degrading (15%): tốt ban đầu, xấu dần theo thời gian
            # - flaky (5%): random spike không dự đoán được
            self.scenario = np.random.choice(
                ["healthy", "buggy", "degrading", "flaky"],
                p=[0.60, 0.20, 0.15, 0.05]
            )
        
        obs = self._get_obs()
        info = {"scenario": self.scenario}
        return obs, info

    def step(self, action):
        self.step_count += 1

        # ----- apply action -----
        if action == 1:  # UP: tăng traffic
            self.traffic_v2 = min(1.0, self.traffic_v2 + 0.1)
        elif action == 2:  # DOWN: giảm traffic (rollback)
            self.traffic_v2 = max(0.0, self.traffic_v2 - 0.1)

        # ----- simulate system -----
        error_rate = self._simulate_error()
        latency = self._simulate_latency()

        reward = self._compute_reward(error_rate, latency, action)

        terminated = False
        truncated = False
        
        # Early termination: nếu error quá cao (4% critical)
        if error_rate > 0.04:
            reward -= 10.0  # phạt rất nặng
            terminated = True
        
        if self.step_count >= self.max_steps:
            truncated = True

        # rollout success: traffic đạt 100% với error thấp
        if self.traffic_v2 >= 1.0 and error_rate < 0.02 and latency < self.slo_latency:
            reward += 50.0  # Tăng từ 30.0 lên 50.0 để agent dám full rollout
            terminated = True

        obs = self._get_obs(error_rate, latency)
        info = {
            "traffic_v2": self.traffic_v2,
            "error_rate": error_rate,
            "latency": latency
        }

        return obs, reward, terminated, truncated, info

    # -----------------------------

    def _get_obs(self, error_rate=0.0, latency=None):
        if latency is None:
            latency = self.base_latency
        # Normalize latency về [0, 1] bằng cách chia cho max expected latency
        max_latency = 500.0  # max expected latency for normalization
        normalized_latency = min(latency / max_latency, 1.0)
        return np.array([
            self.traffic_v2,
            error_rate,
            normalized_latency,
            self.step_count / self.max_steps
        ], dtype=np.float32)

    def _simulate_error(self):
        """
        Simulate error rate theo scenario:
        - healthy: error thấp, ổn định → agent nên rollout nhanh
        - buggy: error cao từ đầu → agent nên rollback sớm
        - degrading: error tăng dần → agent cần nhận biết và dừng kịp thời
        - flaky: random spike → agent cần xử lý uncertainty
        """
        if self.scenario == "healthy":
            # Canary tốt: error rất thấp, ổn định
            base_error = 0.002 + self.traffic_v2 * 0.005
            noise = np.random.normal(0, 0.001)
            return max(0.0, min(base_error + noise, 1.0))
        
        elif self.scenario == "buggy":
            # Canary có bug: error cao ngay từ đầu, tỉ lệ với traffic
            base_error = 0.025 + self.traffic_v2 * 0.025
            noise = np.random.normal(0, 0.003)
            return max(0.0, min(base_error + noise, 1.0))
        
        elif self.scenario == "degrading":
            # Canary xuống cấp: ban đầu tốt, error tăng dần theo thời gian
            time_factor = self.step_count / self.max_steps
            base_error = 0.003 + self.traffic_v2 * 0.015 * (1 + time_factor * 2)
            noise = np.random.normal(0, 0.002)
            return max(0.0, min(base_error + noise, 1.0))
        
        else:  # flaky
            # Random spike không dự đoán được (giữ logic cũ)
            base_error = 0.002 + self.traffic_v2 * 0.02
            
            # Random spike: 10% chance khi traffic > 0.3
            if self.traffic_v2 > 0.3 and np.random.rand() < 0.10:
                base_error += np.random.uniform(0.015, 0.035)
            
            noise = np.random.normal(0, 0.002)
            return max(0.0, min(base_error + noise, 1.0))

    def _simulate_latency(self):
        latency = self.base_latency + self.traffic_v2 * 80
        jitter = np.random.normal(0, 5)
        return max(0.0, latency + jitter)

    # -----------------------------

    def _compute_reward(self, error_rate, latency, action):
        reward = 0.0

        # (1) Khuyến khích rollout mạnh hơn - reward tăng theo traffic^2
        # Để agent có động lực tiến lên 100% thay vì dừng ở 50%
        reward += (self.traffic_v2 ** 1.5) * 3.0

        # (2) Phạt error
        reward -= error_rate * 15.0

        # (3) PENALTY cho UP khi error cao (> 2%)
        if action == 1 and error_rate > 0.02:
            reward -= 5.0
        
        # (4) REWARD cho rollback khi error CAO (> 2.5%)
        if action == 2 and error_rate > 0.025 and self.traffic_v2 > 0.1:
            reward += 2.0
        
        # (5) PENALTY cho rollback KHÔNG CẦN THIẾT (error thấp < 1.5%)
        # Đây là fix cho oscillation problem
        if action == 2 and error_rate < 0.015:
            reward -= 1.5  # Phạt nặng rollback khi không cần

        # (6) REWARD cho HOLD chỉ khi error RẤT cao (> 2.5%)
        if action == 0 and error_rate > 0.025 and self.traffic_v2 > 0.1:
            reward += 0.3

        # (7) Phạt latency vượt SLO
        if latency > self.slo_latency:
            reward -= (latency - self.slo_latency) * 0.05

        # (8) PENALTY cho HOLD khi traffic thấp và error thấp
        if action == 0 and self.traffic_v2 < 0.8:
            if error_rate < 0.015:
                reward -= 0.5
            else:
                reward -= 0.1

        # (9) BONUS cho UP khi error thấp (< 1.5%)
        if action == 1 and error_rate < 0.015:
            reward += 0.5  # Tăng bonus cho UP an toàn

        # (10) Phạt đứng yên quá lâu (traffic = 0)
        if self.traffic_v2 == 0.0:
            reward -= 0.5

        # (11) BONUS lớn khi traffic >= 80% và error thấp
        if self.traffic_v2 >= 0.8 and error_rate < 0.02:
            reward += 1.5

        # (12) BONUS cực lớn khi gần 100%
        if self.traffic_v2 >= 0.9 and error_rate < 0.02:
            reward += 2.0

        return reward
