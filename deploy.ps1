<# 
    Build Script for Canary Release Demo
    Script này build tất cả Docker images và deploy lên Minikube
#>

param(
    [string]$Action = "all",  # all, build, deploy, clean
    [string]$Scenario = "healthy"  # healthy, buggy, degrading, flaky
)

$ErrorActionPreference = "Stop"

# Colors for output
function Write-Step { param($msg) Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-Success { param($msg) Write-Host "[SUCCESS] $msg" -ForegroundColor Green }
function Write-Info { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Yellow }
function Write-Err { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red }

# Paths
$ROOT_DIR = $PSScriptRoot
$K8S_DIR = Join-Path $ROOT_DIR "k8s"
$SERVICES_DIR = Join-Path $K8S_DIR "services\app"
$AGENT_DIR = Join-Path $K8S_DIR "agent"
$MANIFESTS_DIR = Join-Path $K8S_DIR "manifests"
$MODEL_DIR = Join-Path $ROOT_DIR "best_model"

function Test-Minikube {
    Write-Step "Checking Minikube status"
    
    $status = minikube status --format='{{.Host}}' 2>&1
    if ($status -ne "Running") {
        Write-Info "Starting Minikube..."
        minikube start --driver=docker
    }
    Write-Success "Minikube is running"
    
    # Enable ingress addon
    Write-Info "Enabling NGINX Ingress Controller..."
    minikube addons enable ingress
    Write-Success "Ingress addon enabled"
}

function Set-MinikubeDockerEnv {
    Write-Step "Setting Minikube Docker environment"
    
    # Get docker env from minikube
    $env_output = minikube docker-env --shell powershell | Out-String
    Invoke-Expression $env_output
    
    Write-Success "Docker environment configured for Minikube"
}

function Build-Images {
    Write-Step "Building Docker images"
    
    # Build stable service
    Write-Info "Building stable service image..."
    Push-Location $SERVICES_DIR
    docker build -f Dockerfile.stable -t demo-app-stable:latest .
    Pop-Location
    Write-Success "Stable service image built"
    
    # Build canary service
    Write-Info "Building canary service image..."
    Push-Location $SERVICES_DIR
    docker build -f Dockerfile.canary -t demo-app-canary:latest .
    Pop-Location
    Write-Success "Canary service image built"
    
    # Build agent
    Write-Info "Building agent image..."
    
    # Copy model to agent directory
    if (Test-Path $MODEL_DIR) {
        Copy-Item -Path (Join-Path $MODEL_DIR "best_model.zip") -Destination $AGENT_DIR -Force
        Write-Info "Model copied to agent directory"
    } else {
        Write-Err "Model not found at $MODEL_DIR"
        Write-Info "Please run train.py first to generate the model"
        exit 1
    }
    
    Push-Location $AGENT_DIR
    docker build -t canary-agent:latest .
    Pop-Location
    Write-Success "Agent image built"
    
    Write-Success "All images built successfully"
}

function Deploy-Manifests {
    param([string]$ScenarioName = "healthy")
    
    Write-Step "Deploying to Kubernetes"
    
    # Apply namespace first
    Write-Info "Creating namespace..."
    kubectl apply -f (Join-Path $MANIFESTS_DIR "00-namespace.yaml")
    
    # Apply stable deployment
    Write-Info "Deploying stable service..."
    kubectl apply -f (Join-Path $MANIFESTS_DIR "01-stable-deployment.yaml")
    
    # Update canary scenario if needed
    $canaryManifest = Join-Path $MANIFESTS_DIR "02-canary-deployment.yaml"
    $content = Get-Content $canaryManifest -Raw
    $content = $content -replace 'value: "(healthy|buggy|degrading|flaky)"', "value: `"$ScenarioName`""
    Set-Content $canaryManifest $content
    
    Write-Info "Deploying canary service (scenario: $ScenarioName)..."
    kubectl apply -f $canaryManifest
    
    # Apply ingress
    Write-Info "Creating ingress..."
    kubectl apply -f (Join-Path $MANIFESTS_DIR "03-ingress.yaml")
    
    # Create ConfigMap from model file
    Write-Info "Creating model ConfigMap..."
    $modelPath = Join-Path $MODEL_DIR "best_model.zip"
    if (Test-Path $modelPath) {
        # Delete existing configmap if exists
        kubectl delete configmap canary-agent-model -n canary-demo --ignore-not-found
        kubectl create configmap canary-agent-model -n canary-demo --from-file=best_model.zip=$modelPath
    }
    
    # Apply agent (but don't start job yet)
    Write-Info "Creating agent resources..."
    # Only apply RBAC and ConfigMap, not the Job
    $agentManifest = Get-Content (Join-Path $MANIFESTS_DIR "04-agent.yaml") -Raw
    $agentParts = $agentManifest -split "---"
    
    # Apply all except Job (last part)
    for ($i = 0; $i -lt $agentParts.Length - 1; $i++) {
        $agentParts[$i] | kubectl apply -f -
    }
    
    # Apply load generator
    Write-Info "Deploying load generator..."
    kubectl apply -f (Join-Path $MANIFESTS_DIR "05-load-generator.yaml")
    
    Write-Success "All manifests deployed"
    
    # Wait for pods
    Write-Info "Waiting for pods to be ready..."
    kubectl wait --for=condition=ready pod -l app=demo-app -n canary-demo --timeout=120s
    
    Write-Success "All pods are ready"
}

function Start-Agent {
    Write-Step "Starting Canary Agent"
    
    # Delete existing job if any
    kubectl delete job canary-agent -n canary-demo --ignore-not-found
    
    # Apply the full agent manifest including Job
    kubectl apply -f (Join-Path $MANIFESTS_DIR "04-agent.yaml")
    
    Write-Success "Agent started"
    Write-Info "Monitor with: kubectl logs -f job/canary-agent -n canary-demo"
}

function Get-Status {
    Write-Step "Cluster Status"
    
    Write-Info "Pods:"
    kubectl get pods -n canary-demo -o wide
    
    Write-Info "`nServices:"
    kubectl get svc -n canary-demo
    
    Write-Info "`nIngress:"
    kubectl get ingress -n canary-demo
    
    Write-Info "`nCanary weight:"
    kubectl get ingress demo-app-ingress-canary -n canary-demo -o jsonpath='{.metadata.annotations.nginx\.ingress\.kubernetes\.io/canary-weight}'
    Write-Host "%"
}

function Remove-All {
    Write-Step "Cleaning up"
    
    kubectl delete namespace canary-demo --ignore-not-found
    
    Write-Success "Cleanup completed"
}

function Get-MinikubeIP {
    Write-Step "Getting access URL"
    
    $ip = minikube ip
    Write-Info "Add this to your hosts file:"
    Write-Host "$ip demo-app.local" -ForegroundColor White
    
    Write-Info "`nOr use port-forward:"
    Write-Host "kubectl port-forward svc/demo-app-stable 8080:8080 -n canary-demo" -ForegroundColor White
}

# Main
switch ($Action) {
    "build" {
        Test-Minikube
        Set-MinikubeDockerEnv
        Build-Images
    }
    "deploy" {
        Deploy-Manifests -ScenarioName $Scenario
        Get-Status
        Get-MinikubeIP
    }
    "agent" {
        Start-Agent
    }
    "status" {
        Get-Status
    }
    "clean" {
        Remove-All
    }
    "url" {
        Get-MinikubeIP
    }
    "all" {
        Test-Minikube
        Set-MinikubeDockerEnv
        Build-Images
        Deploy-Manifests -ScenarioName $Scenario
        Get-Status
        Get-MinikubeIP
        
        Write-Host "`n"
        Write-Success "Setup completed!"
        Write-Info "To start the canary agent, run: .\deploy.ps1 -Action agent"
        Write-Info "To monitor: kubectl logs -f job/canary-agent -n canary-demo"
    }
    default {
        Write-Host "Usage: .\deploy.ps1 -Action <action> [-Scenario <scenario>]"
        Write-Host ""
        Write-Host "Actions:"
        Write-Host "  all     - Build and deploy everything (default)"
        Write-Host "  build   - Only build Docker images"
        Write-Host "  deploy  - Only deploy to Kubernetes"
        Write-Host "  agent   - Start the canary agent"
        Write-Host "  status  - Show cluster status"
        Write-Host "  clean   - Remove all resources"
        Write-Host "  url     - Show access URL"
        Write-Host ""
        Write-Host "Scenarios:"
        Write-Host "  healthy   - Canary hoạt động tốt (default)"
        Write-Host "  buggy     - Canary có bug, error cao"
        Write-Host "  degrading - Canary xuống cấp theo thời gian"
        Write-Host "  flaky     - Canary không ổn định, random spikes"
    }
}
