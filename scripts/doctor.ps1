# NexAgent local environment doctor.
# PowerShell 5.1 compatible. This script is read-only: it does not install,
# start, stop, delete, or modify project files.

param(
    [switch]$Json
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Results = New-Object System.Collections.Generic.List[object]

function Add-Result {
    param(
        [string]$Name,
        [string]$Status,
        [string]$Message,
        [string]$Fix = ""
    )

    $Results.Add([pscustomobject]@{
        name = $Name
        status = $Status
        message = $Message
        fix = $Fix
    }) | Out-Null
}

function Get-CommandVersion {
    param([string]$Command, [string[]]$VersionArgs)

    $cmd = Get-Command $Command -ErrorAction SilentlyContinue
    if (-not $cmd) {
        return $null
    }

    try {
        $output = & $Command @VersionArgs 2>&1 | Select-Object -First 1
        if ($LASTEXITCODE -ne 0 -and -not $output) {
            return "installed"
        }
        return ($output | Out-String).Trim()
    } catch {
        return "installed"
    }
}

function Test-CommandAvailable {
    param(
        [string]$Name,
        [string]$Command,
        [string[]]$VersionArgs,
        [string]$Fix
    )

    $version = Get-CommandVersion -Command $Command -VersionArgs $VersionArgs
    if ($null -eq $version) {
        Add-Result $Name "warn" "$Command was not found on PATH." $Fix
    } else {
        Add-Result $Name "ok" "$Command detected: $version"
    }
}

function Read-DotEnv {
    param([string]$Path)

    $values = @{}
    if (-not (Test-Path $Path)) {
        return $values
    }

    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line -ne "" -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $idx = $line.IndexOf("=")
            $key = $line.Substring(0, $idx).Trim()
            $value = $line.Substring($idx + 1).Trim().Trim('"').Trim("'")
            $values[$key] = $value
        }
    }
    return $values
}

function Test-Port {
    param([int]$Port)

    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $success = $iar.AsyncWaitHandle.WaitOne(250, $false)
        if ($success) {
            $client.EndConnect($iar)
        }
        $client.Close()
        return $success
    } catch {
        return $false
    }
}

function Test-HttpJson {
    param([string]$Name, [string]$Url, [string]$Fix)

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        Add-Result $Name "ok" "$Url returned HTTP $($response.StatusCode)."
    } catch {
        Add-Result $Name "warn" "$Url is not ready: $($_.Exception.Message)" $Fix
    }
}

function Test-SystemDiagnostics {
    $url = "http://localhost:8001/api/system/diagnostics"
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        $data = $response.Content | ConvertFrom-Json
        $status = [string]$data.config.status
        if ($status -eq "ok") {
            Add-Result "Config diagnostics" "ok" "Backend reports config status ok."
            return
        }
        $issues = @($data.config.issues)
        $summary = ($issues | Select-Object -First 3 | ForEach-Object { "$($_.code): $($_.message)" }) -join " | "
        if (-not $summary) {
            $summary = "Backend reported config status '$status'."
        }
        $level = if ($status -eq "error") { "error" } else { "warn" }
        Add-Result "Config diagnostics" $level $summary "Open $url for the full non-secret diagnostics payload."
    } catch {
        Add-Result "Config diagnostics" "warn" "Backend diagnostics endpoint is not available." "Start the backend, then rerun doctor."
    }
}

Push-Location $Root

Test-CommandAvailable "Python" "python" @("--version") "Install Python 3.12+ and reopen the terminal."
Test-CommandAvailable "uv" "uv" @("--version") "Install uv, or use the fallback startup script dependencies path."
Test-CommandAvailable "Node.js" "node" @("--version") "Install Node.js 22+ for the Next.js frontend."
Test-CommandAvailable "npm" "npm" @("--version") "Install npm with Node.js."
Test-CommandAvailable "Docker" "docker" @("--version") "Install/start Docker Desktop if you want Docker or knowledge services."

$envPath = Join-Path $Root ".env"
$envExamplePath = Join-Path $Root ".env.example"
$configPath = Join-Path $Root "config.yaml"
$configExamplePath = Join-Path $Root "config.example.yaml"

if (Test-Path $envPath) {
    Add-Result ".env" "ok" ".env exists."
} elseif (Test-Path $envExamplePath) {
    Add-Result ".env" "warn" ".env is missing." "Run .\scripts\setup.ps1 or copy .env.example to .env."
} else {
    Add-Result ".env" "error" "Both .env and .env.example are missing."
}

if (Test-Path $configPath) {
    Add-Result "config.yaml" "ok" "config.yaml exists."
} elseif (Test-Path $configExamplePath) {
    Add-Result "config.yaml" "warn" "config.yaml is missing." "Run .\scripts\setup.ps1 or copy config.example.yaml to config.yaml."
} else {
    Add-Result "config.yaml" "error" "Both config.yaml and config.example.yaml are missing."
}

$envValues = Read-DotEnv $envPath
$modelKeys = @("SILICONFLOW_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")
$configuredKeys = @()
foreach ($key in $modelKeys) {
    if ($envValues.ContainsKey($key) -and $envValues[$key]) {
        $configuredKeys += $key
    } elseif ([System.Environment]::GetEnvironmentVariable($key, "Process")) {
        $configuredKeys += $key
    }
}

if ($configuredKeys.Count -gt 0) {
    Add-Result "Model API key" "ok" "Configured provider key(s): $($configuredKeys -join ', '). Values are not printed."
} else {
    Add-Result "Model API key" "warn" "No model provider key detected in .env or current process." "Set SILICONFLOW_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, or GOOGLE_API_KEY."
}

$backendPyproject = Join-Path $Root "backend\pyproject.toml"
$frontendPackage = Join-Path $Root "frontend\package.json"
if (Test-Path $backendPyproject) {
    Add-Result "Backend project" "ok" "backend\pyproject.toml exists."
} else {
    Add-Result "Backend project" "error" "backend\pyproject.toml is missing."
}

if (Test-Path $frontendPackage) {
    Add-Result "Frontend project" "ok" "frontend\package.json exists."
} else {
    Add-Result "Frontend project" "error" "frontend\package.json is missing."
}

if (Test-Port 3000) {
    Add-Result "Port 3000" "warn" "Port 3000 is already accepting connections." "If Next.js fails to start, stop the existing process or use another port."
} else {
    Add-Result "Port 3000" "ok" "Port 3000 appears free."
}

if (Test-Port 8001) {
    Add-Result "Port 8001" "warn" "Port 8001 is already accepting connections." "If the backend fails to start, stop the existing process or change the backend port."
} else {
    Add-Result "Port 8001" "ok" "Port 8001 appears free."
}

Test-HttpJson "Backend health" "http://localhost:8001/health" "Start the backend with .\start.ps1 or uvicorn."
Test-HttpJson "Backend readiness" "http://localhost:8001/health/ready" "Readiness may fail until config, database, and data directory are available."
Test-SystemDiagnostics

try {
    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -eq 0) {
        Add-Result "Docker daemon" "ok" "Docker daemon is reachable."
    } else {
        Add-Result "Docker daemon" "warn" "Docker command exists, but the daemon is not reachable." "Start Docker Desktop before using docker compose or .\start.ps1 -kb."
    }
} catch {
    Add-Result "Docker daemon" "warn" "Docker daemon check failed." "Start Docker Desktop if you need Docker-backed services."
}

Pop-Location

if ($Json) {
    $Results | ConvertTo-Json -Depth 4
    exit 0
}

$hasError = $false
$hasWarn = $false
Write-Host ""
Write-Host "NexAgent Doctor" -ForegroundColor Cyan
Write-Host "Root: $Root" -ForegroundColor DarkGray
Write-Host ""

foreach ($item in $Results) {
    $color = "Green"
    $label = "OK"
    if ($item.status -eq "warn") {
        $color = "Yellow"
        $label = "WARN"
        $hasWarn = $true
    } elseif ($item.status -eq "error") {
        $color = "Red"
        $label = "ERROR"
        $hasError = $true
    }

    Write-Host ("[{0}] {1}: {2}" -f $label, $item.name, $item.message) -ForegroundColor $color
    if ($item.fix) {
        Write-Host ("      Fix: {0}" -f $item.fix) -ForegroundColor DarkGray
    }
}

Write-Host ""
if ($hasError) {
    Write-Host "Doctor finished with errors. Fix ERROR items first, then run this script again." -ForegroundColor Red
    exit 2
}
if ($hasWarn) {
    Write-Host "Doctor finished with warnings. You can still develop, but startup may need the fixes above." -ForegroundColor Yellow
    exit 1
}

Write-Host "Doctor finished cleanly. You can start NexAgent with .\start.ps1." -ForegroundColor Green
exit 0
