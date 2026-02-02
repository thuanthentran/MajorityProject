from stable_baselines3 import DQN
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.callbacks import EvalCallback, StopTrainingOnNoModelImprovement
from env.canary_env import CanaryEnv
import os
import numpy as np
import torch

# Set seed cho reproducibility
SEED = 42
np.random.seed(SEED)
torch.manual_seed(SEED)

def main():
    # Tạo environment
    env = make_vec_env(CanaryEnv, n_envs=1)
    eval_env = make_vec_env(CanaryEnv, n_envs=1)

    # Tạo thư mục logs
    log_dir = "./logs/"
    os.makedirs(log_dir, exist_ok=True)

    # Callback: Early stopping nếu không cải thiện sau 5 evaluations
    stop_callback = StopTrainingOnNoModelImprovement(
        max_no_improvement_evals=5,
        verbose=1
    )

    # Callback: Evaluate và save best model
    eval_callback = EvalCallback(
        eval_env,
        best_model_save_path="./best_model/",
        log_path=log_dir,
        eval_freq=2000,
        n_eval_episodes=10,
        deterministic=True,
        callback_after_eval=stop_callback,
        verbose=1
    )

    # DQN model với TensorBoard logging
    model = DQN(
        policy="MlpPolicy",
        device="cuda",
        env=env,
        learning_rate=5e-4,       # Giảm từ 1e-3 để training ổn định hơn
        buffer_size=50000,        # Tăng từ 10000 để có đa dạng experience
        learning_starts=500,      # Tăng để có đủ experience trước khi học
        batch_size=64,            # Tăng batch size
        gamma=0.99,
        exploration_fraction=0.3, # Tăng exploration
        exploration_final_eps=0.05,
        tensorboard_log=log_dir,
        seed=SEED,                # Thêm seed
        verbose=1
    )

    # Train với callbacks
    model.learn(
        total_timesteps=300000,
        callback=eval_callback,
        tb_log_name="canary_dqn"
    )

    # Save final model
    model.save("canary_dqn_agent")
    print("Training completed!")
    print("Best model saved in ./best_model/")
    print("TensorBoard logs saved in ./logs/")
    print("Run 'tensorboard --logdir=./logs/' to view training progress")

if __name__ == "__main__":
    main()
