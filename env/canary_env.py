import gymnasium as gym
import numpy as np
from gymnasium import spaces
from collections import deque


class CanaryEnv(gym.Env):
    """
    Canary Release Environment cho kiến trúc Microservice.

    Mô phỏng việc canary release 1 microservice (1 pod) trong cluster
    với nhiều microservices phụ thuộc chồng chéo lẫn nhau.

    Observation: context window gồm `window_size` timesteps, mỗi timestep có 8 metrics:
        Local (canary pod):
            0. error_rate_v2       – tỉ lệ lỗi của canary pod
            1. latency_p95_v2      – p95 latency của canary pod (normalized)
            2. cpu_usage_v2        – CPU usage của canary pod (normalized)
            3. memory_usage_v2     – memory usage của canary pod (normalized)
        Global (cluster-level):
            4. total_error_rate    – tỉ lệ lỗi toàn cluster
            5. end_to_end_latency  – end-to-end latency qua chuỗi microservices (normalized)
            6. request_rate        – request rate toàn cluster (normalized)
            7. traffic_v2          – % traffic đang route sang canary (internal state)

    Action: 0 = HOLD, 1 = UP (+10% traffic), 2 = DOWN (-10% traffic)

    Flattened observation shape: (window_size * 8,)
    """

    # Metric indices (cho tiện tham chiếu)
    IDX_ERROR_RATE_V2 = 0
    IDX_LATENCY_P95_V2 = 1
    IDX_CPU_USAGE_V2 = 2
    IDX_MEMORY_USAGE_V2 = 3
    IDX_TOTAL_ERROR_RATE = 4
    IDX_END_TO_END_LATENCY = 5
    IDX_REQUEST_RATE = 6
    IDX_TRAFFIC_V2 = 7
    NUM_METRICS = 8

    def __init__(self, force_scenario=None, window_size=10):
        """
        Args:
            force_scenario: Nếu được set, sẽ luôn dùng scenario này thay vì random.
                           Options: "healthy", "buggy", "degrading", "flaky", None (random)
            window_size:   Kích thước context window (số timesteps agent nhìn lại).
        """
        super().__init__()

        # Context window
        self.window_size = window_size

        # Rollout params
        self.max_steps = 100
        self.step_count = 0

        # Internal state
        self.traffic_v2 = 0.0
        self.base_latency = 100.0       # base latency canary (ms)
        self.slo_latency = 200.0        # SLO p95 latency canary (ms)
        self.slo_e2e_latency = 500.0    # SLO end-to-end latency (ms)

        # Microservice cluster params
        self.num_services = 5           # tổng số microservice trong cluster (bao gồm canary)
        self.cascade_factor = 0.0       # mức độ lỗi lan truyền qua dependency graph
        self.base_cluster_error = 0.005 # baseline error toàn cluster
        self.base_cluster_latency = 250.0  # baseline e2e latency (ms)
        self.base_request_rate = 0.5    # baseline normalized request rate

        # Scenario
        self.force_scenario = force_scenario
        self.scenario = force_scenario if force_scenario else "healthy"

        # Context window buffer
        self._obs_buffer = deque(maxlen=self.window_size)

        # Action: hold / up / down
        self.action_space = spaces.Discrete(3)

        # Observation: flattened context window (window_size * 8 metrics)
        obs_dim = self.window_size * self.NUM_METRICS
        self.observation_space = spaces.Box(
            low=0.0, high=1.0, shape=(obs_dim,), dtype=np.float32
        )

    # ------------------------------------------------------------------ reset
    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.step_count = 0
        self.traffic_v2 = 0.0
        self.cascade_factor = 0.0

        # Chọn scenario
        if self.force_scenario:
            self.scenario = self.force_scenario
        else:
            self.scenario = np.random.choice(
                ["healthy", "buggy", "degrading", "flaky"],
                p=[0.60, 0.20, 0.15, 0.05]
            )

        # Randomize cluster params mỗi episode để tăng tính tổng quát
        self.base_cluster_error = np.random.uniform(0.003, 0.008)
        self.base_cluster_latency = np.random.uniform(200.0, 300.0)
        self.base_request_rate = np.random.uniform(0.4, 0.7)

        # Khởi tạo buffer với zero-observations
        self._obs_buffer.clear()
        zero_obs = self._build_single_obs()
        for _ in range(self.window_size):
            self._obs_buffer.append(zero_obs)

        obs = self._get_context_window()
        info = {"scenario": self.scenario}
        return obs, info

    # ------------------------------------------------------------------- step
    def step(self, action):
        self.step_count += 1

        # ----- apply action -----
        if action == 1:   # UP: tăng traffic canary
            self.traffic_v2 = min(1.0, self.traffic_v2 + 0.1)
        elif action == 2: # DOWN: giảm traffic (rollback)
            self.traffic_v2 = max(0.0, self.traffic_v2 - 0.1)

        # ----- simulate local metrics (canary pod) -----
        error_rate_v2 = self._simulate_canary_error()
        latency_p95_v2 = self._simulate_canary_latency()
        cpu_usage_v2 = self._simulate_canary_cpu(error_rate_v2)
        memory_usage_v2 = self._simulate_canary_memory()

        # ----- simulate global metrics (cluster) -----
        self._update_cascade(error_rate_v2)
        total_error_rate = self._simulate_cluster_error(error_rate_v2)
        end_to_end_latency = self._simulate_cluster_latency(latency_p95_v2)
        request_rate = self._simulate_request_rate()

        # ----- build observation & push vào buffer -----
        single_obs = self._build_single_obs(
            error_rate_v2, latency_p95_v2, cpu_usage_v2, memory_usage_v2,
            total_error_rate, end_to_end_latency, request_rate
        )
        self._obs_buffer.append(single_obs)

        # ----- reward -----
        reward = self._compute_reward(
            error_rate_v2, latency_p95_v2, cpu_usage_v2, memory_usage_v2,
            total_error_rate, end_to_end_latency, request_rate, action
        )

        terminated = False
        truncated = False

        # Early termination: canary error quá cao (critical)
        if error_rate_v2 > 0.04:
            reward -= 10.0
            terminated = True

        # Early termination: cluster error quá cao (cascade failure)
        if total_error_rate > 0.06:
            reward -= 15.0
            terminated = True

        if self.step_count >= self.max_steps:
            truncated = True

        # Rollout success: 100% traffic với metrics tốt
        if (self.traffic_v2 >= 1.0
                and error_rate_v2 < 0.02
                and latency_p95_v2 < self.slo_latency
                and total_error_rate < 0.03):
            reward += 50.0
            terminated = True

        obs = self._get_context_window()
        info = {
            "traffic_v2": self.traffic_v2,
            "error_rate_v2": error_rate_v2,
            "latency_p95_v2": latency_p95_v2,
            "cpu_usage_v2": cpu_usage_v2,
            "memory_usage_v2": memory_usage_v2,
            "total_error_rate": total_error_rate,
            "end_to_end_latency": end_to_end_latency,
            "request_rate": request_rate,
            "cascade_factor": self.cascade_factor,
            "scenario": self.scenario,
        }

        return obs, reward, terminated, truncated, info

    # ============================================================
    #                 CONTEXT WINDOW
    # ============================================================

    def _build_single_obs(
        self,
        error_rate_v2=0.0,
        latency_p95_v2=None,
        cpu_usage_v2=0.05,
        memory_usage_v2=0.10,
        total_error_rate=None,
        end_to_end_latency=None,
        request_rate=None,
    ):
        """Tạo vector 8-dim (đã normalize về [0,1]) cho 1 timestep."""
        if latency_p95_v2 is None:
            latency_p95_v2 = self.base_latency
        if total_error_rate is None:
            total_error_rate = self.base_cluster_error
        if end_to_end_latency is None:
            end_to_end_latency = self.base_cluster_latency
        if request_rate is None:
            request_rate = self.base_request_rate

        max_local_latency = 500.0   # dùng để normalize canary p95
        max_e2e_latency = 1000.0    # dùng để normalize e2e latency

        return np.array([
            np.clip(error_rate_v2, 0.0, 1.0),                               # 0
            np.clip(latency_p95_v2 / max_local_latency, 0.0, 1.0),          # 1
            np.clip(cpu_usage_v2, 0.0, 1.0),                                # 2
            np.clip(memory_usage_v2, 0.0, 1.0),                             # 3
            np.clip(total_error_rate, 0.0, 1.0),                            # 4
            np.clip(end_to_end_latency / max_e2e_latency, 0.0, 1.0),       # 5
            np.clip(request_rate, 0.0, 1.0),                                # 6
            np.clip(self.traffic_v2, 0.0, 1.0),                             # 7
        ], dtype=np.float32)

    def _get_context_window(self):
        """Flatten buffer thành vector (window_size * 8,)."""
        return np.concatenate(list(self._obs_buffer)).astype(np.float32)

    # ============================================================
    #        LOCAL METRIC SIMULATION (canary pod)
    # ============================================================

    def _simulate_canary_error(self):
        """Error rate của canary pod, phụ thuộc vào scenario."""
        if self.scenario == "healthy":
            base = 0.002 + self.traffic_v2 * 0.005
            noise = np.random.normal(0, 0.001)
        elif self.scenario == "buggy":
            base = 0.025 + self.traffic_v2 * 0.025
            noise = np.random.normal(0, 0.003)
        elif self.scenario == "degrading":
            time_factor = self.step_count / self.max_steps
            base = 0.003 + self.traffic_v2 * 0.015 * (1 + time_factor * 2)
            noise = np.random.normal(0, 0.002)
        else:  # flaky
            base = 0.002 + self.traffic_v2 * 0.02
            if self.traffic_v2 > 0.3 and np.random.rand() < 0.10:
                base += np.random.uniform(0.015, 0.035)
            noise = np.random.normal(0, 0.002)

        return float(np.clip(base + noise, 0.0, 1.0))

    def _simulate_canary_latency(self):
        """P95 latency (ms) của canary pod."""
        base = self.base_latency + self.traffic_v2 * 80
        # Scenario-dependent overhead
        if self.scenario == "buggy":
            base += 30 + self.traffic_v2 * 40
        elif self.scenario == "degrading":
            time_factor = self.step_count / self.max_steps
            base += time_factor * 60
        elif self.scenario == "flaky":
            if np.random.rand() < 0.08:
                base += np.random.uniform(50, 150)

        jitter = np.random.normal(0, 8)
        return float(max(0.0, base + jitter))

    def _simulate_canary_cpu(self, error_rate_v2):
        """CPU usage [0,1] của canary pod – tăng theo traffic và error (retry storms)."""
        base_cpu = 0.05 + self.traffic_v2 * 0.35
        # Error gây retry → CPU tăng
        error_overhead = error_rate_v2 * 5.0
        noise = np.random.normal(0, 0.02)
        return float(np.clip(base_cpu + error_overhead + noise, 0.0, 1.0))

    def _simulate_canary_memory(self):
        """Memory usage [0,1] của canary pod – tăng dần theo thời gian và traffic."""
        base_mem = 0.10 + self.traffic_v2 * 0.25
        # Memory leak nhẹ theo thời gian (degrading scenario nặng hơn)
        time_factor = self.step_count / self.max_steps
        if self.scenario == "degrading":
            base_mem += time_factor * 0.20
        else:
            base_mem += time_factor * 0.05
        noise = np.random.normal(0, 0.015)
        return float(np.clip(base_mem + noise, 0.0, 1.0))

    # ============================================================
    #        GLOBAL METRIC SIMULATION (cluster-level)
    # ============================================================

    def _update_cascade(self, error_rate_v2):
        """
        Cập nhật cascade_factor: mức độ lỗi lan truyền từ canary
        sang các microservices phụ thuộc trong cluster.
        Mô phỏng: khi canary lỗi nhiều, các service gọi nó sẽ bị ảnh hưởng
        (timeout, retry, circuit-breaker chưa kịp bật).
        cascade_factor tăng dần khi error cao, giảm dần khi ổn định (exponential smoothing).
        """
        # Phần traffic đi qua canary * error = "lỗi lan tỏa" potential
        error_pressure = self.traffic_v2 * error_rate_v2 * (self.num_services - 1)
        # Smoothing: cascade không nhảy đột ngột, mà tích lũy / phục hồi dần
        alpha = 0.3
        self.cascade_factor = np.clip(
            alpha * error_pressure + (1 - alpha) * self.cascade_factor,
            0.0, 1.0
        )

    def _simulate_cluster_error(self, error_rate_v2):
        """
        Total error rate toàn cluster.
        = baseline error các service khỏe mạnh
        + phần đóng góp từ canary (theo traffic)
        + phần cascade (lỗi lan truyền qua dependency).
        """
        # Weighted contribution: canary đóng góp error theo % traffic nó phục vụ
        canary_contribution = self.traffic_v2 * error_rate_v2 / self.num_services
        # Cascade gây error ở các downstream services
        cascade_error = self.cascade_factor * 0.02
        noise = np.random.normal(0, 0.001)
        total = self.base_cluster_error + canary_contribution + cascade_error + noise
        return float(np.clip(total, 0.0, 1.0))

    def _simulate_cluster_latency(self, latency_p95_v2):
        """
        End-to-end latency (ms) qua chuỗi microservices.
        Ảnh hưởng bởi canary latency (cộng dồn trong dependency chain)
        và cascade (retry/timeout ở downstream).
        """
        # Canary nằm trên critical path với xác suất ~ traffic_v2
        canary_impact = self.traffic_v2 * (latency_p95_v2 - self.base_latency) * 0.5
        cascade_latency = self.cascade_factor * 120  # cascade gây thêm delay
        noise = np.random.normal(0, 10)
        e2e = self.base_cluster_latency + canary_impact + cascade_latency + noise
        return float(max(0.0, e2e))

    def _simulate_request_rate(self):
        """
        Normalized request rate [0,1] toàn cluster.
        Giảm khi cascade cao (circuit-breaker, back-pressure).
        Tăng nhẹ khi canary healthy (dịch vụ mới có thể thu hút traffic).
        """
        rate = self.base_request_rate
        # Cascade gây back-pressure → giảm request rate
        rate -= self.cascade_factor * 0.15
        # Healthy canary có thể tăng nhẹ throughput
        if self.scenario == "healthy":
            rate += self.traffic_v2 * 0.05
        noise = np.random.normal(0, 0.02)
        return float(np.clip(rate + noise, 0.0, 1.0))

    # ============================================================
    #                        REWARD
    # ============================================================

    def _compute_reward(
        self,
        error_rate_v2, latency_p95_v2, cpu_usage_v2, memory_usage_v2,
        total_error_rate, end_to_end_latency, request_rate, action
    ):
        reward = 0.0

        # (1) Khuyến khích rollout – reward tăng theo traffic^1.5
        reward += (self.traffic_v2 ** 1.5) * 3.0

        # (2) Phạt canary error
        reward -= error_rate_v2 * 15.0

        # (3) Phạt cluster error (cascade awareness)
        reward -= total_error_rate * 10.0

        # (4) Phạt latency vượt SLO
        if latency_p95_v2 > self.slo_latency:
            reward -= (latency_p95_v2 - self.slo_latency) / 100.0 * 2.0

        # (5) Phạt e2e latency vượt SLO cluster
        if end_to_end_latency > self.slo_e2e_latency:
            reward -= (end_to_end_latency - self.slo_e2e_latency) / 200.0 * 2.0

        # (6) Phạt CPU quá cao (overload)
        if cpu_usage_v2 > 0.8:
            reward -= (cpu_usage_v2 - 0.8) * 5.0

        # (7) Phạt memory quá cao
        if memory_usage_v2 > 0.85:
            reward -= (memory_usage_v2 - 0.85) * 5.0

        # (8) PENALTY cho UP khi local error cao (> 2%)
        if action == 1 and error_rate_v2 > 0.02:
            reward -= 5.0

        # (9) PENALTY cho UP khi cluster error cao (> 2%)
        if action == 1 and total_error_rate > 0.02:
            reward -= 3.0

        # (10) REWARD rollback khi error cao (> 2.5%)
        if action == 2 and error_rate_v2 > 0.025 and self.traffic_v2 > 0.1:
            reward += 2.0

        # (11) REWARD rollback khi cascade_factor cao
        if action == 2 and self.cascade_factor > 0.1 and self.traffic_v2 > 0.1:
            reward += 1.5

        # (12) PENALTY rollback không cần thiết (error thấp)
        if action == 2 and error_rate_v2 < 0.015 and total_error_rate < 0.015:
            reward -= 1.5

        # (13) REWARD HOLD khi error rất cao
        if action == 0 and error_rate_v2 > 0.025 and self.traffic_v2 > 0.1:
            reward += 0.3

        # (14) PENALTY HOLD khi traffic thấp và mọi thứ ổn
        if action == 0 and self.traffic_v2 < 0.8:
            if error_rate_v2 < 0.015 and total_error_rate < 0.015:
                reward -= 0.5
            else:
                reward -= 0.1

        # (15) BONUS UP an toàn (error thấp cả local lẫn global)
        if action == 1 and error_rate_v2 < 0.015 and total_error_rate < 0.015:
            reward += 0.5

        # (16) Phạt đứng yên quá lâu (traffic = 0)
        if self.traffic_v2 == 0.0:
            reward -= 0.5

        # (17) BONUS traffic >= 80% ổn định
        if self.traffic_v2 >= 0.8 and error_rate_v2 < 0.02 and total_error_rate < 0.025:
            reward += 1.5

        # (18) BONUS gần 100%
        if self.traffic_v2 >= 0.9 and error_rate_v2 < 0.02 and total_error_rate < 0.025:
            reward += 2.0

        return reward
