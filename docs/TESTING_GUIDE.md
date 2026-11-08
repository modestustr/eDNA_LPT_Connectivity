# Manual API Testing Guide

**Purpose:** Comprehensive testing of all API endpoints and modes.
**Updated:** April 12, 2026  
**Phase:** 5B - Testing & Validation

---

## Test Plan Overview

### Scope

- ✅ **Local Mode:** Direct Python function calls
- ✅ **HTTP Mode:** Remote FastAPI server
- ✅ **API Endpoints:** All 9 endpoints
- ✅ **Error Scenarios:** Invalid inputs, timeouts, server down
- ✅ **Integration:** app.py ↔ API Server

### Test Environments

1. **Local Dev** - Direct Python execution
2. **Single Server** - API server + app.py on same machine
3. **HTTP Remote** - API server + HTTP calls

---

## Pre-Testing Setup

### Step 1: Verify Dependencies

```powershell
.\.venv\Scripts\python.exe -c "import fastapi, uvicorn, pytest; print('✓ All packages ready')"
```

### Step 2: Prepare Test Dataset

```powershell
# Check if test data exists
ls dataset.nc

# If not available, tests will use mock data
```

### Step 3: Install Pytest

```powershell
.\.venv\Scripts\pip.exe install pytest pytest-asyncio
```

---

## Test Execution

### Option 1: Run All Tests

```powershell
cd d:\Python Edna\eDNA_LPT_Connectivity

# Run entire test suite
.\.venv\Scripts\pytest.exe tests/ -v

# Run with coverage
.\.venv\Scripts\pytest.exe tests/ -v --cov=. --cov-report=html
```

### Option 2: Run Specific Test Files

```powershell
# Service layer tests only
.\.venv\Scripts\pytest.exe tests/test_api_service.py -v

# Client layer tests only
.\.venv\Scripts\pytest.exe tests/test_api_client.py -v

# API endpoint tests only
.\.venv\Scripts\pytest.exe tests/test_api_server.py -v
```

### Option 3: Run Specific Test Class

```powershell
# Run only validation tests
.\.venv\Scripts\pytest.exe tests/test_api_service.py::TestSimulationServicePreflight -v

# Run only endpoint tests
.\.venv\Scripts\pytest.exe tests/test_api_server.py::TestHealthEndpoints -v
```

---

## Manual HTTP Testing (with Curl)

### Step 1: Start API Server

**Terminal 1:**
```powershell
cd d:\Python Edna\eDNA_LPT_Connectivity

# Development (1 worker, debug logging)
.\.venv\Scripts\python.exe run_api_server.py --log-level debug

# Or Production (4 workers)
.\.venv\Scripts\python.exe run_api_server.py --workers 4
```

**Output should show:**
```
INFO:     Application startup complete
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

### Step 2: Test Health Endpoint

**Terminal 2:**
```powershell
# Health check
curl http://127.0.0.1:8000/health

# Expected response:
# {"status":"healthy",...}
```

### Step 3: Access API Documentation

**Browser:**
```
http://127.0.0.1:8000/docs
```

Or via Swagger UI:
```
http://127.0.0.1:8000/redoc
```

### Step 4: Manual Test Cases

#### Test 1: Health Check

```powershell
# Should return 200 with health status
curl -X GET http://127.0.0.1:8000/health -v
```

#### Test 2: Version Info

```powershell
# Should return version
curl -X GET http://127.0.0.1:8000/version -v
```

#### Test 3: Validate Single Run

```powershell
$config = @{
    "dataset_path" = "dataset.nc"
    "config" = @{
        "u_var" = "uo"
        "v_var" = "vo"
        "lon_coord" = "longitude"
        "lat_coord" = "latitude"
        "time_coord" = "time"
        "depth_coord" = "depth"
        "particle_mode" = "random"
        "particle_backend" = "scipy"
        "particle_count_override" = 100
        "random_seed" = 42
        "dt_minutes" = 10
        "output_hours" = 1
        "release_mode" = "instant"
        "days" = 1
        "mesh_adapter" = "none"
    }
}

curl -X POST http://127.0.0.1:8000/validate/single `
  -H "Content-Type: application/json" `
  -d ($config | ConvertTo-Json -Depth 10)
```

#### Test 4: List All Runs

```powershell
curl -X GET "http://127.0.0.1:8000/runs" -v
```

#### Test 5: Get Run Status

```powershell
# Get runs first to get an ID
$runs = curl -X GET http://127.0.0.1:8000/runs | ConvertFrom-Json

# Then get specific run
if ($runs.Count -gt 0) {
    $runId = $runs[0].id
    curl -X GET "http://127.0.0.1:8000/runs/$runId"
}
```

---

## Integration Testing: app.py ↔ Server

### Setup

**Terminal 1 - Start API Server:**
```powershell
.\.venv\Scripts\python.exe run_api_server.py --port 8000
```

**Terminal 2 - Run Streamlit app:**
```powershell
.\.venv\Scripts\streamlit.exe run app.py
```

### Test Workflow

1. **Upload Dataset**
   - Open app at http://127.0.0.1:8501
   - Upload a NetCDF file

2. **Configure Simulation**
   - Select particle mode
   - Set parameters

3. **Run Simulation**
   - Click "Run Simulation"
   - Watch for HTTP mode auto-detection
   - Verify progress appears

4. **Verify Results**
   - Check output files created
   - View visualization

5. **Monitor HTTP Traffic**
   - Open browser console (F12)
   - Check Network tab
   - Verify requests to http://127.0.0.1:8000
   - Confirm progress SSE stream

---

## Test Scenarios Matrix

| Scenario | Test | Pass/Fail |
|----------|------|-----------|
| **Local Mode** | | |
| Single run execution | Run without server | ✓/✗ |
| Batch execution | Run 3 configs | ✓/✗ |
| Progress callback | Verify updates | ✓/✗ |
| **HTTP Mode** | | |
| Server health | GET /health | ✓/✗ |
| Single run POST | Validate + Execute | ✓/✗ |
| Batch run POST | Multiple configs | ✓/✗ |
| SSE streaming | Progress updates | ✓/✗ |
| **Error Handling** | | |
| Invalid config | Should reject | ✓/✗ |
| Missing dataset | Should error | ✓/✗ |
| Server down | Should fallback | ✓/✗ |
| Timeout handling | Should timeout | ✓/✗ |
| **app.py Integration** | | |
| Auto-detection | Find HTTP server | ✓/✗ |
| Dataset upload | Works with UI | ✓/✗ |
| Parameter entry | Config validation | ✓/✗ |
| Simulation run | Executes via API | ✓/✗ |
| Results display | Shows output | ✓/✗ |

---

## Expected Results

### Successful Test Indicators

✅ **Health Endpoint:**
- Status code: 200
- Response: JSON with status

✅ **Validation Endpoint:**
- Status code: 200 or 422 (validation error)
- Response: Validation result

✅ **Execution Endpoint:**
- Status code: 200 (or queued)
- Response: Run ID or result

✅ **Integration:**
- app.py connects to server
- Progress updates appear
- Results saved to disk

### Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| Connection refused | Check if server is running on port 8000 |
| 404 Not Found | Check endpoint URL spelling |
| 422 Validation Error | Check JSON payload format |
| Timeout | Increase timeout or reduce simulation size |
| CORS error | May need server CORS config |

---

## Performance Testing

### Load Test: Multiple Concurrent Requests

```powershell
# Using ApacheBench (if installed)
ab -n 100 -c 10 http://127.0.0.1:8000/health

# Or using Wrk (if installed)
wrk -t4 -c100 -d30s http://127.0.0.1:8000/health
```

### Memory Usage Monitoring

```powershell
# Monitor server process memory
$proc = Get-Process | Where-Object { $_.Name -like "*python*" }
while ($true) {
    $mem = [math]::Round($proc.WorkingSet64 / 1MB)
    Write-Host "$(Get-Date): Memory: $mem MB"
    Start-Sleep -Seconds 5
}
```

### Response Time Measurement

```powershell
# Measure endpoint response time
Measure-Command {
    curl http://127.0.0.1:8000/health
}
```

---

## Debugging & Troubleshooting

### Enable Debug Logging

```powershell
# Start server with debug logging
.\.venv\Scripts\python.exe run_api_server.py --log-level debug
```

### Check Server Logs

```powershell
# View recent event log entries
Get-EventLog -LogName Application -Source "*eDNA*" -Newest 10

# Or tail Python STDOUT (if running in terminal)
```

### Test Individual Modules

```powershell
# Test API service directly
.\.venv\Scripts\python.exe -c "
from api_service import SimulationService
print('✓ api_service imported successfully')
"

# Test API client
.\.venv\Scripts\python.exe -c "
from api_client import SimulationAPIClient
print('✓ api_client imported successfully')
"

# Test API server
.\.venv\Scripts\python.exe -c "
from api_server import app
print('✓ api_server imported successfully')
"
```

### Validate Configuration

```powershell
# Check if all required modules are available
.\.venv\Scripts\python.exe -c "
import sys
packages = ['fastapi', 'uvicorn', 'pydantic', 'xarray', 'netCDF4', 'zarr']
missing = []
for pkg in packages:
    try:
        __import__(pkg)
        print(f'✓ {pkg}')
    except ImportError:
        print(f'✗ {pkg} MISSING')
        missing.append(pkg)
if missing:
    print(f'ERROR: Missing packages: {missing}')
else:
    print('✓ All packages available')
"
```

---

## Test Results Recording

Create a test report:

```powershell
# Run tests with output file
.\.venv\Scripts\pytest.exe tests/ -v --tb=short > test_results.txt 2>&1

# View results
Get-Content test_results.txt

# Or generate HTML report
.\.venv\Scripts\pytest.exe tests/ -v --html=report.html --self-contained-html
```

---

## Continuous Testing (Optional)

### Automated Test Runner

```powershell
# Run tests every 5 minutes
while ($true) {
    Write-Host "$(Get-Date) - Running tests..."
    .\.venv\Scripts\pytest.exe tests/ -v --tb=short
    Start-Sleep -Seconds 300
}
```

### Watch Mode (requires pytest-watch)

```powershell
.\.venv\Scripts\pip.exe install pytest-watch

# Auto-run tests when files change
.\.venv\Scripts\ptw.exe tests/ -- -v
```

---

## Sign-Off

When all tests pass:

- [ ] Unit tests (test_api_service.py) - PASS
- [ ] Client tests (test_api_client.py) - PASS
- [ ] Endpoint tests (test_api_server.py) - PASS
- [ ] Manual HTTP tests - PASS
- [ ] Integration tests (app.py ↔ Server) - PASS
- [ ] Performance tests - PASS
- [ ] Error handling - PASS

**Phase 5B Status: ✅ COMPLETE**

---

**Next Steps:**
- Phase 5C: Monitoring & Logging
- Production deployment
- Documentation updates
