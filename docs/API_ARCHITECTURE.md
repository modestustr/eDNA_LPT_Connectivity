# Simulation API Architecture

This document describes the multi-layered simulation API architecture that enables flexible deployment and extensibility.

## Overview

The application uses a **3-layer API architecture**:

```
┌─────────────────────────────────────────────────────────────┐
│                    UI Layers                                 │
│  app.py (Streamlit) | Web UI | CLI Clients | Batch Scripts │
└────────────┬────────────────────────────────────────────────┘
             │
             ▼ (uses)
┌─────────────────────────────────────────────────────────────┐
│                  API Client Layer                            │
│          api_client.py (SimulationAPIClient)                │
│  - Abstracts local vs HTTP mode                             │
│  - Single interface for all clients                          │
│  - Auto-detects server availability                         │
└────────────┬─────────────────────┬──────────────────────────┘
             │                     │
      ┌──────▼─────────┐    ┌──────▼─────────────┐
      │                │    │                    │
      ▼                ▼    ▼                    │
┌──────────────┐  ┌──────────────────────────┐  │
│  LOCAL MODE  │  │   HTTP MODE              │  │
│   (direct    │  │  (remote server)         │  │
│   process)   │  │                          │  │
└──────────────┘  └──────────────────────────┘  │
      │                    │                    │
      ▼                    ▼                    │
┌──────────────────────────────────────────────┘
│
│  api_service.py (SimulationService)
│  - Core orchestration logic
│  - Validation (preflight_*)
│  - Execution (execute_*)
│  - Error handling
│
└──────────────────────────────────────────────
       │
       ▼
   simulation_service (OceanParcels)
   - Actual particle tracking engine
```

## Components

### 1. api_service.py — Simulation Service Layer

**Core business logic**, independent of HTTP/UI frameworks.

**Classes:**
- `SimulationService`: Main orchestrator
  - `preflight_single_run(dataset_path, config)` → (valid, issues)
  - `preflight_batch_run(dataset_path, configs)` → (valid, invalid)
  - `execute_single_run(dataset_path, output_path, config, progress_cb)` → RunResult
  - `execute_batch_runs(dataset_path, output_base, configs, progress_cb)` → Dict

**Features:**
- Validation before execution
- Progress callbacks for long-running operations
- Comprehensive error handling
- Compatible with any simulation runner signature

### 2. api_client.py — Unified Client Interface

**Abstracts local vs remote execution**. Single interface used by all clients.

**Classes:**
- `SimulationAPIClient`: 
  - `validate_single_run()` / `validate_batch_runs()`
  - `run_single()` / `run_batch()`
  - Auto-detects local vs HTTP mode
  - Health checks for server availability

**Modes:**
- **LOCAL**: Direct function calls in-process (default for `app.py`)
- **HTTP**: REST API calls to remote server

### 3. api_server.py — FastAPI HTTP Server

**Exposes simulation service via HTTP REST API**.

**Endpoints:**
- `GET /health` — Health check
- `POST /validate/single` — Validate single config
- `POST /validate/batch` — Validate batch configs
- `POST /run/single` — Execute single run
- `POST /run/batch` — Execute batch runs
- `POST /run/single/stream` — Single run with SSE progress
- `GET /runs/{run_id}` — Get run status
- `GET /runs` — List all runs

**Features:**
- Server-Sent Events (SSE) for real-time progress
- Automatic mode detection in client
- OpenAPI/Swagger documentation at `/docs`
- Production-ready with Uvicorn

### 4. api_init.py — Bootstrap Module

**Manages singleton initialization**.

**Functions:**
- `initialize_simulation_api(runner, http_url)` → APIClient
- `get_api_client()` → APIClient
- `get_service()` → SimulationService

### 5. run_api_server.py — Standalone Server Launcher

**CLI to start HTTP server independently**.

```bash
python run_api_server.py --host 0.0.0.0 --port 8000 --reload
```

## Usage Patterns

### Pattern 1: Local Mode (app.py — Current)

```python
import simulation_service
from api_init import initialize_simulation_api

# At app startup
api_client = initialize_simulation_api(
    simulation_service.run_simulation_with_result
)

# In execution blocks
result = api_client.run_single(
    dataset_path,
    output_path,
    config,
    progress_callback=my_progress_fn
)
```

**Advantages:**
- No network overhead
- Fast startup
- No extra processes
- Good for development

---

### Pattern 2: HTTP Mode (Remote Server + app.py)

**Server (separate process):**
```bash
python run_api_server.py --host 0.0.0.0 --port 8000
```

**Client (app.py):**
```python
from api_init import initialize_simulation_api

# At app startup — tries HTTP first, falls back to local
api_client = initialize_simulation_api(
    simulation_service.run_simulation_with_result,
    http_server_url="http://localhost:8000"
)

# Usage identical to local mode
result = api_client.run_single(...)
```

**Advantages:**
- Scale server independent of UI
- Multiple UI clients can share one server
- Microservice deployments
- Load balancing / failover

---

### Pattern 3: External Clients (Python, curl, etc.)

**After server starts:**

```bash
# Curl example
curl -X POST http://localhost:8000/validate/single \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_path": "/path/to/dataset.nc",
    "config": {"mode": "random", "days": 2}
  }'
```

```python
# Python requests
import requests

resp = requests.post(
    'http://localhost:8000/run/single',
    json={
        'dataset_path': '/path/to/dataset.nc',
        'output_path': '/path/to/output',
        'config': {'mode': 'random', 'days': 2}
    }
)
result = resp.json()
```

---

## Deployment Scenarios

### Development

```
app.py (Streamlit) ─→ api_client ─→ api_service ─→ simulation_service
    (local mode, direct calls)
```

**Start:**
```bash
streamlit run app.py
```

### Production — Single Server

```
app.py
  ├─→ api_server (uvicorn)
  │   ├─→ api_service ─→ simulation_service
  │   └─→ database (for run history)
  │
  └─→ API documentation at /docs
```

**Start:**
```bash
# Terminal 1: API server
python run_api_server.py --host 0.0.0.0 --port 8000 --workers 4

# Terminal 2: Streamlit UI
streamlit run app.py
```

### Production — Scale Out

```
Load Balancer (port 80)
    ├─→ app.py (replica 1) ─→ API Server Pool
    ├─→ app.py (replica 2) ─→ /api1:8000
    └─→ app.py (replica 3) ─→ /api2:8000
                               /api3:8000
                    (scales independently)
```

**Benefits:**
- UI layer and compute layer decouple
- Scale servers based on simulation load
- Scale UIs based on user connections
- Better resource utilization

---

## Integration Checklist

- [x] **Phase 1**: Core API service (SimulationService)
- [x] **Phase 2**: Client abstraction (SimulationAPIClient)
- [x] **Phase 3**: HTTP server (FastAPI, Uvicorn)
- [x] **Phase 4**: Bootstrap & initialization
- [x] **Phase 5**: Standalone launcher
- [ ] **Phase 6**: Docker containerization
- [ ] **Phase 7**: Kubernetes manifests
- [ ] **Phase 8**: CI/CD pipeline

---

## Dependencies

### Core (Always)
- `pandas`
- `xarray`
- `numpy`

### Optional (For HTTP Server)
```bash
pip install fastapi uvicorn pydantic
```

### Optional (For Advanced Features)
- `redis` — For distributed caching
- `sqlalchemy` — For persistent run history
- `prometheus-client` — For metrics

---

## API Contract

All endpoints return JSON with consistent structure:

**Success:**
```json
{
  "status": "SUCCEEDED",
  "output_path": "/path/to/output",
  "elapsed_seconds": 1234.5,
  "artifacts": ["zarr", "csv"]
}
```

**Error:**
```json
{
  "status": "FAILED",
  "error_message": "Dataset validation failed: missing variable 'uo'",
  "output_path": null
}
```

---

## Performance Characteristics

| Mode | Latency | Throughput | Scalability |
|------|---------|-----------|------------|
| Local | 0ms overhead | Single process | Limited to 1 machine |
| HTTP | ~10-50ms (network) | Multiple workers | Unlimited (with LB) |

---

## Next Steps

1. **Testing**: Unit tests for api_service, api_client
2. **Monitoring**: Add Prometheus metrics
3. **Persistence**: Store run history in database
4. **Rate Limiting**: Protect server from overload
5. **Authentication**: Add API key validation
6. **Containerization**: Docker images for easy deployment
