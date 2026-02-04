# Canary Release với RL Agent trên Kubernetes

## Tổng quan

Dự án này triển khai một agent DQN để tự động điều tiết canary release trong Kubernetes cluster. Agent sẽ học cách tăng/giảm traffic đến phiên bản mới (canary) dựa trên metrics thực tế.

## Cấu trúc thư mục

```
k8s/
├── agent/                      # Agent controller
│   ├── controller.py           # Main controller script
│   ├── requirements.txt
│   └── Dockerfile
├── services/
│   └── app/
│       ├── stable/app.py       # Stable version service
│       ├── canary/app.py       # Canary version service
│       ├── requirements.txt
│       ├── Dockerfile.stable
│       └── Dockerfile.canary
└── manifests/
    ├── 00-namespace.yaml
    ├── 01-stable-deployment.yaml
    ├── 02-canary-deployment.yaml
    ├── 03-ingress.yaml
    ├── 04-agent.yaml
    └── 05-load-generator.yaml
```

## Yêu cầu

- Docker Desktop
- Minikube
- kubectl
- PowerShell 5.1+

## Hướng dẫn sử dụng

### 1. Khởi động Minikube

```powershell
minikube start --driver=docker
```

### 2. Build và Deploy

```powershell
# Build và deploy tất cả (scenario mặc định: healthy)
.\deploy.ps1

# Hoặc với scenario cụ thể
.\deploy.ps1 -Action all -Scenario buggy
```

### 3. Các Actions có sẵn

```powershell
# Chỉ build images
.\deploy.ps1 -Action build

# Chỉ deploy
.\deploy.ps1 -Action deploy -Scenario healthy

# Kiểm tra status
.\deploy.ps1 -Action status

# Khởi động agent
.\deploy.ps1 -Action agent

# Xóa tất cả
.\deploy.ps1 -Action clean
```

### 4. Test và Monitor

```powershell
# Port-forward để test
.\test.ps1 -Action forward

# (Trong terminal khác) Gửi requests
.\test.ps1 -Action test -Count 100

# Xem metrics
.\test.ps1 -Action metrics

# Thay đổi scenario runtime
.\test.ps1 -Action scenario -Scenario buggy

# Xem logs của agent
.\test.ps1 -Action watch

# Kiểm tra canary weight hiện tại
.\test.ps1 -Action weight
```

## Các Scenario

| Scenario | Mô tả | Agent nên làm gì |
|----------|-------|------------------|
| `healthy` | Canary hoạt động tốt, error thấp | Rollout nhanh đến 100% |
| `buggy` | Canary có bug, error cao từ đầu | Rollback ngay lập tức |
| `degrading` | Canary tốt ban đầu, xấu dần | Nhận biết và rollback kịp thời |
| `flaky` | Random spikes không dự đoán | Xử lý uncertainty |

## Cách hoạt động

1. **Stable Service**: Phiên bản ổn định với error rate thấp (~0.2%)
2. **Canary Service**: Phiên bản mới với behavior theo scenario
3. **Ingress Controller**: NGINX điều tiết traffic qua canary weight
4. **Agent Controller**: DQN agent đọc metrics và quyết định:
   - `HOLD`: Giữ nguyên traffic
   - `UP`: Tăng 10% traffic đến canary
   - `DOWN`: Giảm 10% traffic (rollback)

## Kiến trúc

```
                    ┌─────────────────┐
                    │   Load Balancer │
                    │    (Ingress)    │
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              │                              │
              ▼                              ▼
     ┌─────────────────┐           ┌─────────────────┐
     │  Stable Service │           │  Canary Service │
     │    (v1.0)       │           │    (v2.0)       │
     │  weight: 100-x% │           │   weight: x%    │
     └────────┬────────┘           └────────┬────────┘
              │                              │
              └──────────────┬───────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  Canary Agent   │
                    │  (DQN Model)    │
                    │                 │
                    │ - Read metrics  │
                    │ - Decide action │
                    │ - Update weight │
                    └─────────────────┘
```

## Troubleshooting

### Images không load được
```powershell
# Đảm bảo đang dùng Minikube Docker
minikube docker-env --shell powershell | Invoke-Expression
docker images  # Kiểm tra images
```

### Pods không start
```powershell
kubectl describe pods -n canary-demo
kubectl logs <pod-name> -n canary-demo
```

### Ingress không hoạt động
```powershell
minikube addons enable ingress
kubectl get ingress -n canary-demo
```

## Tài liệu tham khảo

- [NGINX Ingress Canary](https://kubernetes.github.io/ingress-nginx/user-guide/nginx-configuration/annotations/#canary)
- [Stable Baselines3](https://stable-baselines3.readthedocs.io/)
- [Minikube Documentation](https://minikube.sigs.k8s.io/docs/)
