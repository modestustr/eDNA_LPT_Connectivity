# Windows API Server — Quick Reference

## One-Time Setup

```powershell
# 1. Install dependencies
pip install -r requirements.txt

# 2. Build exe (optional but recommended)
pyinstaller api_server.spec
```

## Running the Server

### Method 1: Double-click (Easiest)
```
Start-APIServer.bat
```
Window opens, server runs. Close window to stop.

### Method 2: PowerShell (Recommended for production)
```powershell
# Start
.\Start-APIServer.ps1

# Start with custom port
.\Start-APIServer.ps1 -Port 9000

# Start for network access
.\Start-APIServer.ps1 -Host 0.0.0.0

# Check status
.\Start-APIServer.ps1 -Status

# Stop
.\Start-APIServer.ps1 -Stop
```

### Method 3: Direct command
```cmd
dist\api_server\api_server.exe --host 0.0.0.0 --port 8000 --workers 4
```

---

## Connecting from app.py

```python
# In app.py (auto-connects if server running)
from api_init import initialize_simulation_api
api_client = initialize_simulation_api(
    simulation_service.run_simulation_with_result,
    http_server_url="http://localhost:8000"
)
streamlit run app.py
```

---

## Access Points

Once running:

- **Interactive API docs**: http://localhost:8000/docs
- **ReDoc UI**: http://localhost:8000/redoc
- **Health check**: http://localhost:8000/health

---

## File Locations

| File | Purpose |
|------|---------|
| `Start-APIServer.ps1` | Main launcher (PowerShell) |
| `Start-APIServer.bat` | Quick start (batch) |
| `api_server.spec` | PyInstaller config |
| `dist/api_server/api_server.exe` | Standalone executable |
| `api_logs/` | Daily log files |

---

## Common Tasks

```powershell
# Monitor logs in real-time (PowerShell 7+)
Get-Content api_logs\* -Wait -Tail 50

# Find what's using port 8000
Get-NetTCPConnection -LocalPort 8000 | Get-Process

# Kill process on port 8000
Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess | Stop-Process -Force
```

---

## Modes

| Mode | Command | Use Case |
|------|---------|----------|
| **Local** | `streamlit run app.py` | Development, single user |
| **Network** | `.\Start-APIServer.ps1 -Host 0.0.0.0` + `streamlit run app.py` | Team, multiple app.py instances |
| **Standalone** | `dist\api_server\api_server.exe` | No Python needed, production |

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Port 8000 in use" | Use `-Port 9000` or check running processes |
| "api_server.exe not found" | Run `pyinstaller api_server.spec` first |
| "PowerShell script won't run" | Run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` |
| "Connection refused" | Check if server is running: `.\Start-APIServer.ps1 -Status` |

---

## Next: Testing

```powershell
# Test endpoint with curl (PowerShell 7+)
curl http://localhost:8000/health

# Or with Invoke-WebRequest (all Windows)
Invoke-WebRequest http://localhost:8000/health
```

Should return:
```json
{"status":"healthy","version":"1.0.0"}
```

---

See `WINDOWS_DEPLOYMENT.md` for full documentation.
