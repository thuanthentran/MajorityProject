# K8s Rollout Agent - Canary Deployment with RL

## Tổng quan

Dự án sử dụng **Deep Q-Network (DQN)** agent để tự động điều tiết canary deployment trong Kubernetes cluster. Agent học cách tăng/giảm traffic đến phiên bản mới (canary) dựa trên metrics thực tế.

## Cấu trúc dự án

```
k8s-rollout-agent/
├── app/                          # Application services
│   ├── Dockerfile                # Multi-stage Dockerfile
│   └── src/
│       ├── requirements.txt
│       ├── stable/
│       │   └── app.py            # Stable version (v1.0)
│       └── canary/
│           └── app.py            # Canary version (v2.0)
│
├── agent/                        # RL Agent controller
│   ├── Dockerfile
│   └── src/
│       ├── requirements.txt
│       └── controller.py         # DQN-based controller
│
├── k8s/                          # Kubernetes manifests
│   ├── base/
│   │   └── namespace.yaml
│   ├── app/
│   │   ├── deployment-stable.yaml
│   │   ├── deployment-canary.yaml
│   │   ├── service.yaml
│   │   └── ingress.yaml
│   └── agent/
│       ├── configmap.yaml        # Agent config + RBAC
│       └── deployment.yaml       # Agent Job
│
├── .github/
│   └── workflows/
│       ├── build-app.yaml        # Build stable/canary images
│       ├── build-agent.yaml      # Build agent image
│       └── deploy.yaml           # Deploy to K8s cluster
│
├── env/                          # RL Environment (training)
├── best_model/                   # Trained DQN model
├── train.py                      # Training script
├── evaluate.py                   # Evaluation script
└── README.md
```

## GitHub Actions Workflows

### 1. Build App (`build-app.yaml`)
- **Trigger**: Push to `app/` directory
- **Actions**: 
  - Build stable và canary Docker images
  - Push to GitHub Container Registry (ghcr.io)
  - Auto-update K8s manifests với image tags mới

### 2. Build Agent (`build-agent.yaml`)
- **Trigger**: Push to `agent/` hoặc `best_model/`
- **Actions**:
  - Copy trained model vào agent image
  - Build và push agent Docker image
  - Auto-update K8s manifests

### 3. Deploy (`deploy.yaml`)
- **Trigger**: Manual (workflow_dispatch)
- **Options**:
  - Environment: staging / production
  - Deploy type: all / app-only / agent-only

## Cách sử dụng

### 1. Setup Repository Secrets

Trong GitHub repo settings, thêm secrets:
```
KUBECONFIG: (base64-encoded kubeconfig file)
```

Để encode kubeconfig:
```bash
cat ~/.kube/config | base64 -w 0
```

### 2. Local Development

```powershell
# Build images locally
docker build -t demo-app:stable --build-arg APP_TYPE=stable ./app
docker build -t demo-app:canary --build-arg APP_TYPE=canary ./app
docker build -t canary-agent:latest ./agent

# Deploy to Minikube
minikube start --driver=docker
minikube addons enable ingress

kubectl apply -f k8s/base/
kubectl apply -f k8s/app/
kubectl apply -f k8s/agent/configmap.yaml
kubectl apply -f k8s/agent/deployment.yaml
```

### 3. CI/CD Flow

```
Push code → GitHub Actions → Build Images → Update Manifests → Deploy
```

## Canary Scenarios

| Scenario   | Mô tả                                    | Agent Action |
|------------|------------------------------------------|--------------|
| `healthy`  | Error rate thấp, latency ổn định         | Tăng traffic |
| `buggy`    | Error rate cao ngay từ đầu               | Rollback     |
| `degrading`| Ban đầu tốt, xuống cấp theo thời gian    | Rollback khi phát hiện |
| `flaky`    | Random spikes không dự đoán được         | Thận trọng   |

## Agent Actions

- **HOLD (0)**: Giữ nguyên traffic weight
- **UP (1)**: Tăng traffic canary +10%
- **DOWN (2)**: Giảm traffic canary -10% (rollback)

## Metrics & Observability

Services expose metrics tại `/metrics`:
```json
{
  "version": "2.0-canary",
  "scenario": "healthy",
  "total_requests": 1000,
  "error_count": 5,
  "error_rate": 0.005,
  "avg_latency_ms": 75.5
}
```

## Configuration

Agent có thể cấu hình qua environment variables:

| Variable | Default | Mô tả |
|----------|---------|-------|
| `MODEL_PATH` | `/app/models/best_model` | Path to trained model |
| `STEP_INTERVAL` | `10` | Seconds between decisions |
| `MAX_STEPS` | `100` | Maximum rollout steps |
| `SLO_LATENCY` | `200.0` | SLO latency threshold (ms) |

## License

MIT
