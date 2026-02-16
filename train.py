"""
Train DQN Agent cho Canary Release trong kiến trúc Microservice.

Observation: context window (window_size=10) x 8 metrics
  Local (canary pod):  error_rate_v2, latency_p95_v2, cpu_usage_v2, memory_usage_v2
  Global (cluster):    total_error_rate, end_to_end_latency, request_rate, traffic_v2
Action: 0=HOLD, 1=UP, 2=DOWN
"""

from stable_baselines3 import DQN
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.callbacks import EvalCallback, StopTrainingOnNoModelImprovement
from env.canary_env import CanaryEnv
import os
import argparse
import numpy as np
import torch

# --------------- CLI args ---------------
parser = argparse.ArgumentParser(description="Train Canary DQN Agent (context-window)")
parser.add_argument("--window-size", type=int, default=10, help="Context window size (default: 10)")
parser.add_argument("--timesteps", type=int, default=500_000, help="Total training timesteps")
parser.add_argument("--seed", type=int, default=42, help="Random seed")
parser.add_argument("--device", type=str, default="auto", help="Device: auto / cuda / cpu")
parser.add_argument("--n-envs", type=int, default=4, help="Number of parallel envs")
args = parser.parse_args()

SEED = args.seed
WINDOW_SIZE = args.window_size
np.random.seed(SEED)
torch.manual_seed(SEED)


def make_env(**kwargs):
    """Factory cho CanaryEnv với window_size."""
    def _init():
        return CanaryEnv(window_size=WINDOW_SIZE, **kwargs)
    return _init


def main():
    print(f"=== Training Config ===")
    print(f"  Window size   : {WINDOW_SIZE}")
    print(f"  Obs dimension : {WINDOW_SIZE * CanaryEnv.NUM_METRICS}")
    print(f"  Timesteps     : {args.timesteps:,}")
    print(f"  Parallel envs : {args.n_envs}")
    print(f"  Seed          : {SEED}")
    print(f"  Device        : {args.device}")
    print()

    # Tạo environments
    env = make_vec_env(make_env(), n_envs=args.n_envs)
    eval_env = make_vec_env(make_env(), n_envs=1)

    # Tạo thư mục logs
    log_dir = "./logs/"
    os.makedirs(log_dir, exist_ok=True)

    # Callback: Early stopping nếu không cải thiện sau 8 evaluations
    stop_callback = StopTrainingOnNoModelImprovement(
        max_no_improvement_evals=8,
        verbose=1
    )

    # Callback: Evaluate và save best model
    eval_callback = EvalCallback(
        eval_env,
        best_model_save_path="./best_model/",
        log_path=log_dir,
        eval_freq=max(2500 // args.n_envs, 1),  # điều chỉnh theo n_envs
        n_eval_episodes=20,
        deterministic=True,
        callback_after_eval=stop_callback,
        verbose=1
    )

    # DQN model – MlpPolicy tự động nhận input (window_size * 8,)
    # Dùng network lớn hơn vì observation space bây giờ là 80-dim
    policy_kwargs = dict(
        net_arch=[256, 256],  # 2 hidden layers, mỗi layer 256 units
    )

    model = DQN(
        policy="MlpPolicy",
        device=args.device,
        env=env,
        learning_rate=3e-4,
        buffer_size=100_000,
        learning_starts=1000,
        batch_size=128,
        gamma=0.99,
        tau=0.005,                 # soft update target network
        exploration_fraction=0.35,
        exploration_final_eps=0.05,
        target_update_interval=500,
        train_freq=(4, "step"),
        policy_kwargs=policy_kwargs,
        tensorboard_log=log_dir,
        seed=SEED,
        verbose=1
    )

    print(f"Model policy network:\n{model.policy}\n")

    # Train với callbacks
    model.learn(
        total_timesteps=args.timesteps,
        callback=eval_callback,
        tb_log_name="canary_dqn"
    )

    # Save final model
    model.save("canary_dqn_agent")
    print("\n" + "=" * 55)
    print("Training completed!")
    print(f"  Observation : context window {WINDOW_SIZE} x {CanaryEnv.NUM_METRICS} metrics = {WINDOW_SIZE * CanaryEnv.NUM_METRICS}-dim")
    print(f"  Best model  : ./best_model/best_model.zip")
    print(f"  Final model : canary_dqn_agent.zip")
    print(f"  Logs        : {log_dir}")
    print("Run 'tensorboard --logdir=./logs/' to view training progress")
    print("=" * 55)


if __name__ == "__main__":
    main()
