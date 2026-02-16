"""
Evaluate trained Canary DQN Agent (context-window, microservice cluster).

Hiển thị đầy đủ 8 metrics mỗi step:
  Local:  error_rate_v2, latency_p95_v2, cpu_usage_v2, memory_usage_v2
  Global: total_error_rate, end_to_end_latency, request_rate, traffic_v2
"""

from stable_baselines3 import DQN
from env.canary_env import CanaryEnv
import os
import argparse
import numpy as np

# ---- CLI ----
parser = argparse.ArgumentParser(description="Evaluate Canary DQN Agent")
parser.add_argument(
    "--scenario",
    type=str,
    choices=["healthy", "buggy", "degrading", "flaky", "random"],
    default="random",
    help="Scenario to test (default: random)"
)
parser.add_argument("--window-size", type=int, default=10, help="Context window size (must match training)")
parser.add_argument("--episodes", type=int, default=1, help="Number of episodes to run")
args = parser.parse_args()

WINDOW_SIZE = args.window_size

# Tạo env
force_scenario = None if args.scenario == "random" else args.scenario
env = CanaryEnv(force_scenario=force_scenario, window_size=WINDOW_SIZE)

# Load model
best_model_path = "./best_model/best_model.zip"
final_model_path = "canary_dqn_agent.zip"

if os.path.exists(best_model_path):
    print("Loading best model...")
    model = DQN.load("./best_model/best_model")
elif os.path.exists(final_model_path):
    print("Loading final model...")
    model = DQN.load("canary_dqn_agent")
else:
    raise FileNotFoundError("No trained model found! Please run train.py first.")

action_names = ["HOLD", "UP  ", "DOWN"]

for ep in range(args.episodes):
    obs, info = env.reset()
    terminated = False
    truncated = False
    total_reward = 0.0

    print(f"\n{'=' * 80}")
    print(f"Episode {ep + 1} | Scenario: {env.scenario.upper()} | Window: {WINDOW_SIZE}")
    print(f"{'=' * 80}")
    header = (
        f"{'Step':>4} {'Action':>6} | "
        f"{'Traf%':>5} {'ErrL%':>6} {'P95ms':>6} {'CPU%':>5} {'Mem%':>5} | "
        f"{'ErrG%':>6} {'E2Ems':>6} {'RRate':>5} {'Casc':>5} | {'Rew':>7}"
    )
    print(header)
    print("-" * len(header))

    while not (terminated or truncated):
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        total_reward += reward

        step = env.step_count
        t = info["traffic_v2"] * 100
        er = info["error_rate_v2"] * 100
        l95 = info["latency_p95_v2"]
        cpu = info["cpu_usage_v2"] * 100
        mem = info["memory_usage_v2"] * 100
        ger = info["total_error_rate"] * 100
        e2e = info["end_to_end_latency"]
        rr = info["request_rate"]
        cas = info["cascade_factor"]

        print(
            f"{step:4d} {action_names[action]:>6} | "
            f"{t:5.0f} {er:6.2f} {l95:6.1f} {cpu:5.1f} {mem:5.1f} | "
            f"{ger:6.2f} {e2e:6.1f} {rr:5.2f} {cas:5.3f} | {reward:7.2f}"
        )

    status = "SUCCESS" if info["traffic_v2"] >= 1.0 else "FAIL/TIMEOUT"
    print(f"\n>>> {status} | Total Reward: {total_reward:.2f}")

print(f"\n{'=' * 80}")
print("Evaluation finished.")
