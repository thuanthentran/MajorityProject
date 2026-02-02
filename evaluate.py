from stable_baselines3 import DQN
from env.canary_env import CanaryEnv
import os
import argparse

# Parse arguments
parser = argparse.ArgumentParser(description="Evaluate Canary DQN Agent")
parser.add_argument(
    "--scenario", 
    type=str, 
    choices=["healthy", "buggy", "degrading", "flaky", "random"],
    default="random",
    help="Scenario to test: healthy, buggy, degrading, flaky, or random"
)
args = parser.parse_args()

# Tạo env với scenario được chọn
force_scenario = None if args.scenario == "random" else args.scenario
env = CanaryEnv(force_scenario=force_scenario)

# Load best model nếu tồn tại, nếu không thì load final model
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

obs, info = env.reset()
terminated = False
truncated = False

print(f"=== Rollout start [Scenario: {env.scenario.upper()}] ===")
action_names = ["HOLD", "UP", "DOWN"]
while not (terminated or truncated):
    action, _ = model.predict(obs, deterministic=True)
    obs, reward, terminated, truncated, info = env.step(action)
    
    # Lấy giá trị thực từ info thay vì obs (đã normalized)
    real_latency = info.get("latency", obs[2] * 500)
    real_error = info.get("error_rate", obs[1])

    print(f"""
Step: {int(obs[3] * 100)}
Action: {action_names[action]}
Traffic v2: {obs[0]*100:.0f}%
Error rate: {real_error*100:.2f}%
Latency: {real_latency:.1f}ms
Reward: {reward:.2f}
""")

print("=== Rollout finished ===")
