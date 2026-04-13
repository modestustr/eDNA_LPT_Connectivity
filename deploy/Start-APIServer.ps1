# PowerShell launcher for eDNA LPT Simulation API Server
# Windows Service-like management without admin requirements
#
# Usage:
#   .\Start-APIServer.ps1                    # Start with defaults
#   .\Start-APIServer.ps1 -Port 9000 -Stop   # Stop running instance
#   .\Start-APIServer.ps1 -Status            # Check if running
#   .\Start-APIServer.ps1 -Restart           # Restart
#
# Requirements:
#   - Run from the project directory
#   - api_server.exe in dist/api_server/ (from PyInstaller build)
#   - Windows 7+ (PowerShell 2.0+)

param(
    [int]$Port = 8000,
    [string]$Host = "127.0.0.1",
    [switch]$Stop = $false,
    [switch]$Status = $false,
    [switch]$Restart = $false,
    [switch]$ShowLogs = $false,
    [int]$Workers = 4
)

# Configuration
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ExePath = Join-Path $ScriptDir "dist\api_server\api_server.exe"
$LogDir = Join-Path $ScriptDir "api_logs"
$LogFile = Join-Path $LogDir "api_server_$(Get-Date -Format 'yyyyMMdd').log"
$ProcessName = "api_server"
$Port = [int]$Port

# Colors for output
function Write-Header { Write-Host "═" * 60 -ForegroundColor Cyan; Write-Host $args[0] -ForegroundColor Cyan; Write-Host "═" * 60 -ForegroundColor Cyan }
function Write-Success { Write-Host $args[0] -ForegroundColor Green }
function Write-Error { Write-Host "ERROR: $($args[0])" -ForegroundColor Red }
function Write-Info { Write-Host $args[0] -ForegroundColor Yellow }

# Ensure log directory exists
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# Check if exe exists
function Test-ExecutableExists {
    if (-not (Test-Path $ExePath)) {
        Write-Error "api_server.exe not found at: $ExePath"
        Write-Info "Build it first with: pyinstaller api_server.spec"
        return $false
    }
    return $true
}

# Get process status
function Get-ServerStatus {
    $proc = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue
    if ($proc) {
        return @{ Running = $true; Process = $proc; Port = $Port }
    }
    return @{ Running = $false; Process = $null; Port = $Port }
}

# Start server
function Start-Server {
    $status = Get-ServerStatus
    
    if ($status.Running) {
        Write-Info "✓ API Server already running (PID: $($status.Process.Id))"
        Write-Info "  URL: http://$Host`:$Port"
        Write-Info "  Docs: http://$Host`:$Port/docs"
        return $true
    }
    
    if (-not (Test-ExecutableExists)) {
        return $false
    }
    
    Write-Header "Starting eDNA LPT Simulation API Server"
    Write-Info "Port: $Port"
    Write-Info "Host: $Host"
    Write-Info "Workers: $Workers"
    Write-Info "Log file: $LogFile"
    
    try {
        # Start exe in background with output redirection
        $proc = Start-Process -FilePath $ExePath `
                             -ArgumentList "--host $Host --port $Port --workers $Workers --reload" `
                             -NoNewWindow `
                             -PassThru `
                             -RedirectStandardOutput $LogFile `
                             -RedirectStandardError $LogFile
        
        # Wait a moment for startup
        Start-Sleep -Seconds 2
        
        $status = Get-ServerStatus
        if ($status.Running) {
            Write-Success "✓ Server started successfully (PID: $($proc.Id))"
            Write-Success "✓ API endpoint: http://$Host`:$Port"
            Write-Success "✓ API docs: http://$Host`:$Port/docs"
            Write-Info ""
            Write-Info "Common URLs:"
            Write-Info "  Health check: http://$Host`:$Port/health"
            Write-Info "  Interactive docs: http://$Host`:$Port/docs"
            Write-Info "  ReDoc: http://$Host`:$Port/redoc"
            Write-Info ""
            Write-Info "View logs with: .\Start-APIServer.ps1 -ShowLogs"
            Write-Info "Stop server with: .\Start-APIServer.ps1 -Stop"
            return $true
        }
        else {
            Write-Error "Process started but not detected. Check logs:"
            Get-Content $LogFile | Select-Object -Last 20
            return $false
        }
    }
    catch {
        Write-Error $_.Exception.Message
        return $false
    }
}

# Stop server
function Stop-Server {
    $status = Get-ServerStatus
    
    if (-not $status.Running) {
        Write-Info "✓ API Server is not running"
        return $true
    }
    
    Write-Header "Stopping eDNA LPT Simulation API Server"
    Write-Info "PID: $($status.Process.Id)"
    
    try {
        Stop-Process -InputObject $status.Process -Force -ErrorAction Stop
        Write-Success "✓ Server stopped"
        
        # Wait for port to be released
        Start-Sleep -Milliseconds 500
        return $true
    }
    catch {
        Write-Error $_.Exception.Message
        return $false
    }
}

# Show status
function Show-Status {
    $status = Get-ServerStatus
    
    Write-Header "eDNA LPT Simulation API Server Status"
    
    if ($status.Running) {
        Write-Success "Status: RUNNING ✓"
        Write-Info "  PID: $($status.Process.Id)"
        Write-Info "  Memory: $([math]::Round($status.Process.WorkingSet / 1MB, 2)) MB"
        Write-Info "  CPU: $($status.Process.CPU)%"
        Write-Info "  URL: http://$Host`:$Port"
        Write-Info "  Docs: http://$Host`:$Port/docs"
    }
    else {
        Write-Info "Status: STOPPED"
    }
    
    Write-Info ""
    Write-Info "Log file: $LogFile"
    Write-Info ""
    
    return $status.Running
}

# Show logs
function Show-Logs {
    if (Test-Path $LogFile) {
        Write-Header "Recent Logs (Last 100 lines)"
        Get-Content $LogFile | Select-Object -Last 100
    }
    else {
        Write-Info "No logs found yet. Start the server first."
    }
}

# Main logic
if ($Status) {
    Show-Status
}
elseif ($ShowLogs) {
    Show-Logs
}
elseif ($Stop) {
    Stop-Server | Out-Null
}
elseif ($Restart) {
    Write-Info "Restarting..."
    Stop-Server | Out-Null
    Start-Sleep -Seconds 1
    Start-Server | Out-Null
}
else {
    Start-Server | Out-Null
}

Write-Host ""
