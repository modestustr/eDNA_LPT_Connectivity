# Windows Deployment Guide for eDNA LPT Simulation API

This guide explains how to deploy the API server on Windows without Docker.

## Quick Start (60 seconds)

### 1. Install Dependencies

```powershell
pip install fastapi uvicorn pydantic pyinstaller
```

### 2. Build Executable

```powershell
pyinstaller api_server.spec
```

Result: `dist/api_server/api_server.exe` (standalone, ~100MB)

### 3. Start Server

**Option A: Double-click**
```
Start-APIServer.bat
```

**Option B: PowerShell (with options)**
```powershell
.\Start-APIServer.ps1 -Port 8000 -Host 0.0.0.0 -Workers 4
```

**Option C: Command line**
```cmd
dist\api_server\api_server.exe --host 0.0.0.0 --port 8000 --workers 4
```

---

## Setup Steps (Detailed)

### Step 1: Build the Executable

```powershell
# Navigate to project directory
cd d:\Python Edna\eDNA_LPT_Connectivity

# Install PyInstaller if not already installed
pip install pyinstaller

# Build executable from spec file
pyinstaller api_server.spec

# Verify build
dir dist\api_server\api_server.exe
```

**Output:**
```
dist/
  api_server/
    api_server.exe          (~100 MB, standalone)
    _internal/              (dependencies)
    API_ARCHITECTURE.md
```

The exe is completely standalone — no Python interpreter needed on the target machine!

### Step 2: Start the Server

#### Option A: Manual Start (Command Prompt)

```cmd
cd d:\Python Edna\eDNA_LPT_Connectivity
dist\api_server\api_server.exe --host 0.0.0.0 --port 8000
```

You'll see:
```
INFO: Uvicorn running on http://0.0.0.0:8000
INFO: Application startup
```

#### Option B: PowerShell Launcher (Recommended)

```powershell
cd d:\Python Edna\eDNA_LPT_Connectivity
.\Start-APIServer.ps1
```

**Commands:**
```powershell
# Start (default: localhost:8000)
.\Start-APIServer.ps1

# Start on different port
.\Start-APIServer.ps1 -Port 9000

# Start for network access
.\Start-APIServer.ps1 -Host 0.0.0.0 -Port 8000 -Workers 4

# Check status
.\Start-APIServer.ps1 -Status

# View logs
.\Start-APIServer.ps1 -ShowLogs

# Stop server
.\Start-APIServer.ps1 -Stop

# Restart
.\Start-APIServer.ps1 -Restart
```

#### Option C: Batch File (Double-click)

```
Start-APIServer.bat
```

Simply double-click and a window will open with the server running.

---

## Connecting from app.py

Once server is running, app.py will auto-detect it:

```python
from api_init import initialize_simulation_api
import simulation_service

# Server auto-detected at localhost:8000
api_client = initialize_simulation_api(
    simulation_service.run_simulation_with_result,
    http_server_url="http://localhost:8000"
)

# Now use app.py normally - it uses the remote server
streamlit run app.py
```

---

## Accessing API

Once running, access the API at:

- **Interactive Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

### Example: Test with curl

```powershell
# Health check
curl http://localhost:8000/health

# Validation request
$body = @{
    dataset_path = "C:/path/to/dataset.nc"
    config = @{mode="random"; days=2}
} | ConvertTo-Json

curl -Method POST `
     -Uri http://localhost:8000/validate/single `
     -Headers @{"Content-Type"="application/json"} `
     -Body $body
```

---

## Settings & Configuration

### Default Command

```powershell
.\Start-APIServer.ps1
```

- Host: `127.0.0.1` (localhost only)
- Port: `8000`
- Workers: `4`
- Log level: `info`

### Accessible to Network

```powershell
.\Start-APIServer.ps1 -Host 0.0.0.0 -Port 8000
```

Now accessible from: `http://<your-ip>:8000`

### Production Settings

```powershell
.\Start-APIServer.ps1 -Host 0.0.0.0 -Port 80 -Workers 8
```

**Note:** Port 80 requires admin rights. Use 8000+ for regular user.

### Multiple Instances

Run on different ports:

```powershell
# Terminal 1: Instance 1
.\Start-APIServer.ps1 -Port 8000

# Terminal 2: Instance 2
.\Start-APIServer.ps1 -Port 8001

# Terminal 3: Instance 3
.\Start-APIServer.ps1 -Port 8002
```

Then use a reverse proxy (nginx, IIS) to load-balance.

---

## Logs

Logs are saved to: `api_logs/api_server_YYYYMMDD.log`

```powershell
# View logs in PowerShell
.\Start-APIServer.ps1 -ShowLogs

# Or open directly
notepad api_logs\api_server_20260412.log

# Or tail in PowerShell (PowerShell 7.0+)
Get-Content api_logs\api_server_20260412.log -Wait
```

---

## Troubleshooting

### Issue: "api_server.exe not found"

**Solution:** Build the executable first
```powershell
pyinstaller api_server.spec
```

### Issue: "Port 8000 already in use"

**Solution:** Use different port
```powershell
.\Start-APIServer.ps1 -Port 9000
```

Or find process using port:
```powershell
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | 
  ForEach-Object {Get-Process -Id $_.OwningProcess}
```

### Issue: "Access Denied" on PowerShell script

**Solution:** Set execution policy
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Issue: Antivirus blocks exe

**Solution:** Add `dist/api_server/` to antivirus whitelist, or build directly in antivirus-safe location.

---

## File Structure

```
d:\Python Edna\eDNA_LPT_Connectivity\
├── api_server.spec                  ← PyInstaller config
├── Start-APIServer.ps1              ← Main launcher (PowerShell)
├── Start-APIServer.bat              ← Quick-start (batch)
├── dist/
│   └── api_server/
│       ├── api_server.exe           ← Standalone executable
│       ├── _internal/               ← Dependencies
│       └── API_ARCHITECTURE.md
├── api_logs/
│   └── api_server_20260412.log      ← Daily logs
├── [other source files]
```

---

## Performance Tips

1. **Use Workers appropriately**: `-Workers 4` for quad-core, `-Workers 8` for 8-core
2. **Monitor memory**: Each worker uses ~200MB
3. **Use Host 127.0.0.1 locally, 0.0.0.0 for network**
4. **Keep logs**: Rotate daily for debugging

---

## Next Steps

- [x] Build standalone exe
- [x] PowerShell launcher
- [x] Batch file quick-start
- [ ] Windows Service integration (optional: nssm)
- [ ] Firewall rules (if accessing from network)
- [ ] Load balancer setup (if multiple instances)

---

## Summary

| Task | Command |
|------|---------|
| Build exe | `pyinstaller api_server.spec` |
| Start (PowerShell) | `.\Start-APIServer.ps1` |
| Start (batch) | `Start-APIServer.bat` |
| Check status | `.\Start-APIServer.ps1 -Status` |
| Stop | `.\Start-APIServer.ps1 -Stop` |
| View logs | `.\Start-APIServer.ps1 -ShowLogs` |
| Connect from app | `http://localhost:8000` |
| View API docs | Open browser to `/docs` |
