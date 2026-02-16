"""
Rule-based baseline cho Canary Rollout (Microservice cluster, context-window).

So sánh với RL agent để đánh giá hiệu quả.
Rule-based policy chỉ dùng metrics mới nhất trong context window.
"""

from env.canary_env import CanaryEnv
import numpy as np


WINDOW_SIZE = 10  # phải trùng với training


def _latest_metrics(obs, window_size=WINDOW_SIZE, num_metrics=CanaryEnv.NUM_METRICS):
    """
    Trích xuất 8 metrics ở timestep mới nhất từ flattened context window.
    obs shape: (window_size * num_metrics,)
    Timestep cuối bắt đầu từ index (window_size - 1) * num_metrics
    """
    start = (window_size - 1) * num_metrics
    return obs[start: start + num_metrics]


def _trend(obs, metric_idx, window_size=WINDOW_SIZE, num_metrics=CanaryEnv.NUM_METRICS, look_back=5):
    """
    Tính trend (slope) của 1 metric qua `look_back` timesteps gần nhất.
    Dương = tăng, Âm = giảm.
    """
    values = []
    for t in range(max(0, window_size - look_back), window_size):
        idx = t * num_metrics + metric_idx
        values.append(obs[idx])
    if len(values) < 2:
        return 0.0
    # simple linear slope
    x = np.arange(len(values), dtype=np.float32)
    slope = np.polyfit(x, values, 1)[0]
    return float(slope)


def rule_based_policy(obs, config=None):
    """
    Rule-based policy dùng metrics mới nhất + trend analysis.

    Args:
        obs: flattened context window (window_size * 8,)
        config: dict các threshold

    Returns:
        action: 0=HOLD, 1=UP, 2=DOWN
    """
    if config is None:
        config = {
            "error_threshold": 0.02,        # 2% canary error → rollback
            "cluster_error_threshold": 0.025,# 2.5% cluster error → rollback
            "latency_slo_norm": 0.40,        # 200ms / 500ms = 0.40
            "e2e_latency_slo_norm": 0.50,    # 500ms / 1000ms = 0.50
            "cpu_threshold": 0.80,           # 80% CPU → hold
            "memory_threshold": 0.85,        # 85% memory → hold
            "safe_error_threshold": 0.01,    # 1% để tăng traffic an toàn
            "degrading_slope_threshold": 0.002,  # trend dương > này → coi là degrading
        }

    m = _latest_metrics(obs)

    error_rate_v2 = m[CanaryEnv.IDX_ERROR_RATE_V2]
    latency_p95_v2 = m[CanaryEnv.IDX_LATENCY_P95_V2]
    cpu_usage_v2 = m[CanaryEnv.IDX_CPU_USAGE_V2]
    memory_usage_v2 = m[CanaryEnv.IDX_MEMORY_USAGE_V2]
    total_error_rate = m[CanaryEnv.IDX_TOTAL_ERROR_RATE]
    e2e_latency = m[CanaryEnv.IDX_END_TO_END_LATENCY]
    traffic_v2 = m[CanaryEnv.IDX_TRAFFIC_V2]

    # Trend analysis
    error_trend = _trend(obs, CanaryEnv.IDX_ERROR_RATE_V2)
    cluster_error_trend = _trend(obs, CanaryEnv.IDX_TOTAL_ERROR_RATE)

    # Rule 1: Canary error quá cao → rollback
    if error_rate_v2 > config["error_threshold"]:
        return 2  # DOWN

    # Rule 2: Cluster error quá cao → rollback (cascade awareness)
    if total_error_rate > config["cluster_error_threshold"]:
        return 2  # DOWN

    # Rule 3: Error trend đang tăng nhanh → hold (đợi xem)
    if error_trend > config["degrading_slope_threshold"]:
        return 0  # HOLD

    # Rule 4: Cluster error trend tăng nhanh → hold
    if cluster_error_trend > config["degrading_slope_threshold"]:
        return 0  # HOLD

    # Rule 5: Latency vượt SLO → hold
    if latency_p95_v2 > config["latency_slo_norm"]:
        return 0  # HOLD

    # Rule 6: E2E latency vượt SLO → hold
    if e2e_latency > config["e2e_latency_slo_norm"]:
        return 0  # HOLD

    # Rule 7: CPU quá cao → hold
    if cpu_usage_v2 > config["cpu_threshold"]:
        return 0  # HOLD

    # Rule 8: Memory quá cao → hold
    if memory_usage_v2 > config["memory_threshold"]:
        return 0  # HOLD

    # Rule 9: Mọi thứ ổn, error thấp → tăng traffic
    if error_rate_v2 < config["safe_error_threshold"] and total_error_rate < config["safe_error_threshold"]:
        return 1  # UP

    # Default: hold
    return 0  # HOLD


def evaluate_rule_based(num_episodes=10, verbose=True):
    """Evaluate rule-based policy."""
    env = CanaryEnv(window_size=WINDOW_SIZE)

    total_rewards = []
    success_count = 0

    for episode in range(num_episodes):
        obs, _ = env.reset()
        episode_reward = 0
        terminated = False
        truncated = False

        if verbose:
            print(f"\n=== Episode {episode + 1} [Scenario: {env.scenario.upper()}] ===")

        while not (terminated or truncated):
            action = rule_based_policy(obs)
            obs, reward, terminated, truncated, info = env.step(action)
            episode_reward += reward

            if verbose:
                action_names = ["HOLD", "UP  ", "DOWN"]
                print(
                    f"  {action_names[action]} | "
                    f"Traf:{info['traffic_v2']:.2f} "
                    f"ErrL:{info['error_rate_v2']:.4f} "
                    f"P95:{info['latency_p95_v2']:.0f}ms "
                    f"CPU:{info['cpu_usage_v2']:.2f} "
                    f"Mem:{info['memory_usage_v2']:.2f} | "
                    f"ErrG:{info['total_error_rate']:.4f} "
                    f"E2E:{info['end_to_end_latency']:.0f}ms "
                    f"RR:{info['request_rate']:.2f} "
                    f"Cas:{info['cascade_factor']:.3f} | "
                    f"R:{reward:.2f}"
                )

        total_rewards.append(episode_reward)

        if info["traffic_v2"] >= 1.0 and terminated:
            success_count += 1
            if verbose:
                print(">>> SUCCESS! Rollout completed.")
        else:
            if verbose:
                print(">>> TIMEOUT or FAILED")

    # Statistics
    avg_reward = sum(total_rewards) / len(total_rewards)
    success_rate = success_count / num_episodes * 100

    print("\n" + "=" * 55)
    print("RULE-BASED BASELINE RESULTS (Microservice + Context Window)")
    print("=" * 55)
    print(f"  Episodes       : {num_episodes}")
    print(f"  Window size    : {WINDOW_SIZE}")
    print(f"  Average Reward : {avg_reward:.2f}")
    print(f"  Success Rate   : {success_rate:.1f}%")
    print(f"  Min Reward     : {min(total_rewards):.2f}")
    print(f"  Max Reward     : {max(total_rewards):.2f}")

    return {
        "avg_reward": avg_reward,
        "success_rate": success_rate,
        "rewards": total_rewards,
    }


def compare_with_rl(rl_model_path="canary_dqn_agent", num_episodes=20):
    """So sánh Rule-based vs RL agent."""
    from stable_baselines3 import DQN

    env = CanaryEnv(window_size=WINDOW_SIZE)

    try:
        rl_model = DQN.load(rl_model_path)
    except FileNotFoundError:
        print(f"Model not found: {rl_model_path}")
        print("Train the model first using train.py")
        return

    results = {"rule_based": [], "rl_agent": []}
    rb_success = 0
    rl_success = 0

    for episode in range(num_episodes):
        # Rule-based
        obs, _ = env.reset()
        rb_reward = 0
        terminated = truncated = False
        while not (terminated or truncated):
            action = rule_based_policy(obs)
            obs, reward, terminated, truncated, info = env.step(action)
            rb_reward += reward
        results["rule_based"].append(rb_reward)
        if info["traffic_v2"] >= 1.0 and terminated:
            rb_success += 1

        # RL Agent (dùng cùng seed/scenario bằng cách reset ngay sau)
        obs, _ = env.reset()
        rl_reward = 0
        terminated = truncated = False
        while not (terminated or truncated):
            action, _ = rl_model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            rl_reward += reward
        results["rl_agent"].append(rl_reward)
        if info["traffic_v2"] >= 1.0 and terminated:
            rl_success += 1

    rb_avg = np.mean(results["rule_based"])
    rl_avg = np.mean(results["rl_agent"])

    print("\n" + "=" * 60)
    print("COMPARISON: Rule-Based vs RL Agent (Microservice Cluster)")
    print("=" * 60)
    print(f"  {'Method':<15} {'Avg Reward':>12} {'Success%':>10} {'Min':>10} {'Max':>10}")
    print("-" * 60)
    print(
        f"  {'Rule-Based':<15} {rb_avg:>12.2f} {rb_success / num_episodes * 100:>9.1f}% "
        f"{min(results['rule_based']):>10.2f} {max(results['rule_based']):>10.2f}"
    )
    print(
        f"  {'RL Agent':<15} {rl_avg:>12.2f} {rl_success / num_episodes * 100:>9.1f}% "
        f"{min(results['rl_agent']):>10.2f} {max(results['rl_agent']):>10.2f}"
    )
    print("-" * 60)

    improvement = ((rl_avg - rb_avg) / abs(rb_avg)) * 100 if rb_avg != 0 else 0
    print(f"  RL Improvement: {improvement:+.1f}%")

    return results


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "compare":
        compare_with_rl()
    else:
        evaluate_rule_based(num_episodes=10, verbose=True)
