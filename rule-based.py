"""
Rule-based baseline cho Canary Rollout
So sánh với RL agent để đánh giá hiệu quả
"""

from env.canary_env import CanaryEnv


def rule_based_policy(obs, config=None):
    """
    Rule-based policy cho canary rollout
    
    Rules:
    - Nếu error_rate > threshold -> giảm traffic (action=2)
    - Nếu latency > SLO -> giữ nguyên (action=0)
    - Nếu mọi thứ ổn -> tăng traffic (action=1)
    
    Args:
        obs: [traffic_v2, error_rate, latency, time_progress]
        config: dict với các threshold
    
    Returns:
        action: 0=hold, 1=up, 2=down
    """
    if config is None:
        config = {
            "error_threshold": 0.02,      # 2% error rate
            "latency_slo": 200.0,         # 200ms SLO
            "safe_error_threshold": 0.01  # 1% để tăng traffic
        }
    
    traffic_v2 = obs[0]
    error_rate = obs[1]
    latency = obs[2]
    
    # Rule 1: Error quá cao -> rollback
    if error_rate > config["error_threshold"]:
        return 2  # DOWN
    
    # Rule 2: Latency vượt SLO -> giữ nguyên, chờ ổn định
    if latency > config["latency_slo"]:
        return 0  # HOLD
    
    # Rule 3: Mọi thứ ổn định và error thấp -> tăng traffic
    if error_rate < config["safe_error_threshold"]:
        return 1  # UP
    
    # Default: giữ nguyên
    return 0  # HOLD


def evaluate_rule_based(num_episodes=10, verbose=True):
    """
    Evaluate rule-based policy
    """
    env = CanaryEnv()
    
    total_rewards = []
    success_count = 0
    
    for episode in range(num_episodes):
        obs, _ = env.reset()
        episode_reward = 0
        terminated = False
        truncated = False
        
        if verbose:
            print(f"\n=== Episode {episode + 1} ===")
        
        while not (terminated or truncated):
            action = rule_based_policy(obs)
            obs, reward, terminated, truncated, info = env.step(action)
            episode_reward += reward
            
            if verbose:
                action_names = ["HOLD", "UP", "DOWN"]
                print(f"Action: {action_names[action]:5} | "
                      f"Traffic: {obs[0]:.2f} | "
                      f"Error: {obs[1]:.4f} | "
                      f"Latency: {obs[2]:.1f} | "
                      f"Reward: {reward:.2f}")
        
        total_rewards.append(episode_reward)
        
        # Check success (traffic đạt 100% với error thấp)
        if obs[0] >= 1.0 and terminated:
            success_count += 1
            if verbose:
                print(">>> SUCCESS! Rollout completed.")
        else:
            if verbose:
                print(">>> TIMEOUT or FAILED")
    
    # Statistics
    avg_reward = sum(total_rewards) / len(total_rewards)
    success_rate = success_count / num_episodes * 100
    
    print("\n" + "=" * 50)
    print("RULE-BASED BASELINE RESULTS")
    print("=" * 50)
    print(f"Episodes: {num_episodes}")
    print(f"Average Reward: {avg_reward:.2f}")
    print(f"Success Rate: {success_rate:.1f}%")
    print(f"Min Reward: {min(total_rewards):.2f}")
    print(f"Max Reward: {max(total_rewards):.2f}")
    
    return {
        "avg_reward": avg_reward,
        "success_rate": success_rate,
        "rewards": total_rewards
    }


def compare_with_rl(rl_model_path="canary_dqn_agent", num_episodes=10):
    """
    So sánh Rule-based vs RL agent
    """
    from stable_baselines3 import DQN
    
    env = CanaryEnv()
    
    # Load RL model
    try:
        rl_model = DQN.load(rl_model_path)
    except FileNotFoundError:
        print(f"Model not found: {rl_model_path}")
        print("Train the model first using train.py")
        return
    
    results = {"rule_based": [], "rl_agent": []}
    
    for episode in range(num_episodes):
        # Rule-based
        obs, _ = env.reset()
        rb_reward = 0
        terminated = truncated = False
        while not (terminated or truncated):
            action = rule_based_policy(obs)
            obs, reward, terminated, truncated, _ = env.step(action)
            rb_reward += reward
        results["rule_based"].append(rb_reward)
        
        # RL Agent
        obs, _ = env.reset()
        rl_reward = 0
        terminated = truncated = False
        while not (terminated or truncated):
            action, _ = rl_model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, _ = env.step(action)
            rl_reward += reward
        results["rl_agent"].append(rl_reward)
    
    # Print comparison
    rb_avg = sum(results["rule_based"]) / len(results["rule_based"])
    rl_avg = sum(results["rl_agent"]) / len(results["rl_agent"])
    
    print("\n" + "=" * 50)
    print("COMPARISON: Rule-Based vs RL Agent")
    print("=" * 50)
    print(f"{'Method':<15} {'Avg Reward':>12} {'Min':>10} {'Max':>10}")
    print("-" * 50)
    print(f"{'Rule-Based':<15} {rb_avg:>12.2f} {min(results['rule_based']):>10.2f} {max(results['rule_based']):>10.2f}")
    print(f"{'RL Agent':<15} {rl_avg:>12.2f} {min(results['rl_agent']):>10.2f} {max(results['rl_agent']):>10.2f}")
    print("-" * 50)
    
    improvement = ((rl_avg - rb_avg) / abs(rb_avg)) * 100 if rb_avg != 0 else 0
    print(f"RL Improvement: {improvement:+.1f}%")
    
    return results


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "compare":
        compare_with_rl()
    else:
        evaluate_rule_based(num_episodes=10, verbose=True)
