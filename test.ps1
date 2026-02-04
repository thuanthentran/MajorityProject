<#
    Test Script - Gửi requests và kiểm tra canary deployment
#>

param(
    [string]$Action = "test",
    [int]$Count = 100,
    [string]$Scenario = ""
)

$NAMESPACE = "canary-demo"

function Send-Requests {
    param([int]$NumRequests = 100)
    
    Write-Host "`n=== Sending $NumRequests requests ===" -ForegroundColor Cyan
    
    $stableCount = 0
    $canaryCount = 0
    $errorCount = 0
    
    for ($i = 1; $i -le $NumRequests; $i++) {
        try {
            # Port forward to stable service
            $response = Invoke-RestMethod -Uri "http://localhost:8080/api/process" -Method Get -TimeoutSec 5
            
            if ($response.version -like "*stable*") {
                $stableCount++
            } elseif ($response.version -like "*canary*") {
                $canaryCount++
            }
        } catch {
            $errorCount++
        }
        
        if ($i % 10 -eq 0) {
            Write-Host "Progress: $i/$NumRequests" -ForegroundColor Gray
        }
        
        Start-Sleep -Milliseconds 100
    }
    
    Write-Host "`n=== Results ===" -ForegroundColor Green
    Write-Host "Stable: $stableCount ($([math]::Round($stableCount/$NumRequests*100, 1))%)"
    Write-Host "Canary: $canaryCount ($([math]::Round($canaryCount/$NumRequests*100, 1))%)"
    Write-Host "Errors: $errorCount ($([math]::Round($errorCount/$NumRequests*100, 1))%)"
}

function Get-Metrics {
    Write-Host "`n=== Service Metrics ===" -ForegroundColor Cyan
    
    # Get stable metrics
    Write-Host "`nStable Service:" -ForegroundColor Yellow
    kubectl exec -n $NAMESPACE deployment/demo-app-stable -- wget -qO- http://localhost:8080/metrics 2>$null | ConvertFrom-Json | Format-List
    
    # Get canary metrics
    Write-Host "`nCanary Service:" -ForegroundColor Yellow
    kubectl exec -n $NAMESPACE deployment/demo-app-canary -- wget -qO- http://localhost:8080/metrics 2>$null | ConvertFrom-Json | Format-List
}

function Set-Scenario {
    param([string]$NewScenario)
    
    if ($NewScenario -notin @("healthy", "buggy", "degrading", "flaky")) {
        Write-Host "Invalid scenario. Valid options: healthy, buggy, degrading, flaky" -ForegroundColor Red
        return
    }
    
    Write-Host "`n=== Setting canary scenario to: $NewScenario ===" -ForegroundColor Cyan
    
    # Update via API
    $body = @{ scenario = $NewScenario } | ConvertTo-Json
    kubectl exec -n $NAMESPACE deployment/demo-app-canary -- `
        wget -qO- --post-data="$body" --header="Content-Type: application/json" http://localhost:8080/scenario
    
    Write-Host "Scenario updated to $NewScenario" -ForegroundColor Green
}

function Watch-Agent {
    Write-Host "`n=== Watching Agent Logs ===" -ForegroundColor Cyan
    kubectl logs -f job/canary-agent -n $NAMESPACE
}

function Get-CanaryWeight {
    $weight = kubectl get ingress demo-app-ingress-canary -n $NAMESPACE -o jsonpath='{.metadata.annotations.nginx\.ingress\.kubernetes\.io/canary-weight}'
    Write-Host "Current canary weight: $weight%" -ForegroundColor Yellow
}

function Start-PortForward {
    Write-Host "Starting port-forward to stable service on localhost:8080..." -ForegroundColor Cyan
    kubectl port-forward svc/demo-app-stable 8080:8080 -n $NAMESPACE
}

# Main
switch ($Action) {
    "test" {
        Send-Requests -NumRequests $Count
    }
    "metrics" {
        Get-Metrics
    }
    "scenario" {
        if ($Scenario) {
            Set-Scenario -NewScenario $Scenario
        } else {
            Write-Host "Please specify scenario with -Scenario parameter" -ForegroundColor Red
        }
    }
    "watch" {
        Watch-Agent
    }
    "weight" {
        Get-CanaryWeight
    }
    "forward" {
        Start-PortForward
    }
    default {
        Write-Host "Usage: .\test.ps1 -Action <action> [options]"
        Write-Host ""
        Write-Host "Actions:"
        Write-Host "  test      - Send requests and check distribution (use -Count N)"
        Write-Host "  metrics   - Get metrics from services"
        Write-Host "  scenario  - Change canary scenario (use -Scenario <name>)"
        Write-Host "  watch     - Watch agent logs"
        Write-Host "  weight    - Get current canary weight"
        Write-Host "  forward   - Start port-forward"
    }
}
