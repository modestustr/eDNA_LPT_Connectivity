# eDNA LPT Simulation Service - Windows Service Manager
# PowerShell script for installing/managing the Windows Service
# 
# Usage:
#   .\service_manager.ps1 -Action Install -ServiceName eDNALPTSim -ExePath "C:\path\to\eDNA_LPT_SimService.exe" -Port 8000
#   .\service_manager.ps1 -Action Start -ServiceName eDNALPTSim
#   .\service_manager.ps1 -Action Stop -ServiceName eDNALPTSim
#   .\service_manager.ps1 -Action Remove -ServiceName eDNALPTSim
#   .\service_manager.ps1 -Action Status -ServiceName eDNALPTSim
#
# Requires admin privileges for Install/Remove/Start/Stop actions

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("Install", "Start", "Stop", "Remove", "Status", "LogPath")]
    [string]$Action,

    [Parameter(Mandatory=$true)]
    [string]$ServiceName = "eDNALPTSim",

    [Parameter(Mandatory=$false)]
    [string]$ExePath,

    [Parameter(Mandatory=$false)]
    [int]$Port = 8000,

    [Parameter(Mandatory=$false)]
    [string]$Host = "127.0.0.1",

    [Parameter(Mandatory=$false)]
    [int]$Workers = 4,

    [Parameter(Mandatory=$false)]
    [string]$LogLevel = "info"
)

# Helper: Check if running as admin
function Test-Admin {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Helper: Log message
function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $color = @{"INFO" = "Green"; "WARN" = "Yellow"; "ERROR" = "Red"}[$Level]
    Write-Host "[$timestamp] [$Level] $Message" -ForegroundColor $color
}

# Helper: Resolve exe path
function Resolve-ExePath {
    param([string]$Path)
    
    if (-not $Path) {
        # Try to find exe in common locations
        $possiblePaths = @(
            ".\dist\eDNA_LPT_SimService\eDNA_LPT_SimService.exe",
            "..\dist\eDNA_LPT_SimService\eDNA_LPT_SimService.exe",
            "C:\Program Files\eDNA_LPT_Connectivity\eDNA_LPT_SimService.exe",
            "C:\Program Files (x86)\eDNA_LPT_Connectivity\eDNA_LPT_SimService.exe"
        )
        
        foreach ($p in $possiblePaths) {
            if (Test-Path $p) {
                return (Resolve-Path $p).Path
            }
        }
        
        Write-Log "Could not find exe in standard locations. Please specify -ExePath" "ERROR"
        return $null
    }
    
    if (-not (Test-Path $Path)) {
        Write-Log "Exe file not found at: $Path" "ERROR"
        return $null
    }
    
    return (Resolve-Path $Path).Path
}

# ACTION: Install Service
function Install-Service {
    param(
        [string]$ServiceName,
        [string]$ExePath,
        [int]$Port,
        [string]$Host,
        [int]$Workers,
        [string]$LogLevel
    )
    
    if (-not (Test-Admin)) {
        Write-Log "This operation requires admin privileges" "ERROR"
        exit 1
    }
    
    $resolvedExe = Resolve-ExePath $ExePath
    if (-not $resolvedExe) {
        exit 1
    }
    
    # Check if service already exists
    $existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($existingService) {
        Write-Log "Service '$ServiceName' already exists. Remove it first with: -Action Remove" "WARN"
        exit 1
    }
    
    # Build service arguments
    $args = @(
        "--host", $Host,
        "--port", $Port,
        "--workers", $Workers,
        "--log-level", $LogLevel
    )
    
    # Create the service
    $displayName = "eDNA LPT Simulation Service (Port $Port)"
    $description = "Hydrodynamic particle tracking simulation service with REST API"
    
    try {
        New-Service `
            -Name $ServiceName `
            -BinaryPathName "$resolvedExe $($args -join ' ')" `
            -DisplayName $displayName `
            -Description $description `
            -StartupType Automatic `
            -ErrorAction Stop | Out-Null
        
        Write-Log "✓ Service installed successfully: $ServiceName" "INFO"
        Write-Log "  Display Name: $displayName" "INFO"
        Write-Log "  Exe Path: $resolvedExe" "INFO"
        Write-Log "  Host: $Host, Port: $Port" "INFO"
        Write-Log "  Workers: $Workers" "INFO"
        Write-Log "  Log Level: $LogLevel" "INFO"
        Write-Log "" "INFO"
        Write-Log "Next steps:" "INFO"
        Write-Log "  1. Start service: .\service_manager.ps1 -Action Start -ServiceName $ServiceName" "INFO"
        Write-Log "  2. Check status: .\service_manager.ps1 -Action Status -ServiceName $ServiceName" "INFO"
        Write-Log "  3. View logs: .\service_manager.ps1 -Action LogPath -ServiceName $ServiceName" "INFO"
    }
    catch {
        Write-Log "Failed to install service: $_" "ERROR"
        exit 1
    }
}

# ACTION: Start Service
function Start-ServiceByName {
    param([string]$ServiceName)
    
    if (-not (Test-Admin)) {
        Write-Log "This operation requires admin privileges" "ERROR"
        exit 1
    }
    
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $service) {
        Write-Log "Service '$ServiceName' not found" "ERROR"
        exit 1
    }
    
    if ($service.Status -eq "Running") {
        Write-Log "Service is already running" "WARN"
        exit 0
    }
    
    try {
        Start-Service -Name $ServiceName -ErrorAction Stop
        Write-Log "✓ Service started: $ServiceName" "INFO"
        
        # Wait for startup
        Start-Sleep -Seconds 2
        $service = Get-Service -Name $ServiceName
        Write-Log "  Status: $($service.Status)" "INFO"
    }
    catch {
        Write-Log "Failed to start service: $_" "ERROR"
        exit 1
    }
}

# ACTION: Stop Service
function Stop-ServiceByName {
    param([string]$ServiceName)
    
    if (-not (Test-Admin)) {
        Write-Log "This operation requires admin privileges" "ERROR"
        exit 1
    }
    
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $service) {
        Write-Log "Service '$ServiceName' not found" "ERROR"
        exit 1
    }
    
    if ($service.Status -eq "Stopped") {
        Write-Log "Service is already stopped" "WARN"
        exit 0
    }
    
    try {
        Stop-Service -Name $ServiceName -ErrorAction Stop
        Write-Log "✓ Service stopped: $ServiceName" "INFO"
        
        # Wait for shutdown
        Start-Sleep -Seconds 2
        $service = Get-Service -Name $ServiceName
        Write-Log "  Status: $($service.Status)" "INFO"
    }
    catch {
        Write-Log "Failed to stop service: $_" "ERROR"
        exit 1
    }
}

# ACTION: Remove Service
function Remove-ServiceByName {
    param([string]$ServiceName)
    
    if (-not (Test-Admin)) {
        Write-Log "This operation requires admin privileges" "ERROR"
        exit 1
    }
    
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $service) {
        Write-Log "Service '$ServiceName' not found" "ERROR"
        exit 1
    }
    
    if ($service.Status -eq "Running") {
        Write-Log "Stopping service first..." "INFO"
        Stop-ServiceByName $ServiceName
    }
    
    try {
        &sc.exe delete $ServiceName 2>&1 | Out-Null
        Write-Log "✓ Service removed: $ServiceName" "INFO"
    }
    catch {
        Write-Log "Failed to remove service: $_" "ERROR"
        exit 1
    }
}

# ACTION: Check Status
function Get-ServiceStatus {
    param([string]$ServiceName)
    
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $service) {
        Write-Log "Service '$ServiceName' not found" "ERROR"
        exit 1
    }
    
    Write-Log "Service Information:" "INFO"
    Write-Log "  Name: $($service.Name)" "INFO"
    Write-Log "  Display Name: $($service.DisplayName)" "INFO"
    Write-Log "  Status: $($service.Status)" "INFO"
    Write-Log "  Start Type: $($service.StartType)" "INFO"
    
    # Try to read binary path
    $regPath = "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName"
    $regItem = Get-ItemProperty -Path $regPath -ErrorAction SilentlyContinue
    if ($regItem) {
        Write-Log "  Image Path: $($regItem.ImagePath)" "INFO"
    }
}

# ACTION: Get Log Path
function Get-LogPath {
    param([string]$ServiceName)
    
    $appDataPath = $env:LOCALAPPDATA
    $logPath = Join-Path $appDataPath "eDNA_LPT_Connectivity" "logs" "service_$ServiceName.log"
    
    Write-Log "Service log location:" "INFO"
    Write-Log "  $logPath" "INFO"
    Write-Log "" "INFO"
    Write-Log "Tip: Configure logging in run_api_server.py to write to this location" "INFO"
}

# Main execution
try {
    switch ($Action) {
        "Install" {
            Install-Service -ServiceName $ServiceName -ExePath $ExePath -Port $Port `
                           -Host $Host -Workers $Workers -LogLevel $LogLevel
        }
        "Start" {
            Start-ServiceByName -ServiceName $ServiceName
        }
        "Stop" {
            Stop-ServiceByName -ServiceName $ServiceName
        }
        "Remove" {
            Remove-ServiceByName -ServiceName $ServiceName
        }
        "Status" {
            Get-ServiceStatus -ServiceName $ServiceName
        }
        "LogPath" {
            Get-LogPath -ServiceName $ServiceName
        }
        default {
            Write-Log "Unknown action: $Action" "ERROR"
            exit 1
        }
    }
}
catch {
    Write-Log "Unexpected error: $_" "ERROR"
    exit 1
}
