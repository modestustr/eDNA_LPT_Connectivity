"""
FastAPI HTTP Server for Simulation Service
============================================
Exposes the SimulationService as HTTP REST API endpoints.

Run with:
    uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload

Or from within the app:
    import uvicorn
    from threading import Thread
    server_thread = Thread(target=lambda: uvicorn.run(app, host="0.0.0.0", port=8000), daemon=True)
    server_thread.start()
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Request
from fastapi.responses import StreamingResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import json
import asyncio
from datetime import datetime
import uuid

from .service import SimulationService
from src.core.simulation_contracts import RunStatus
from src.monitoring.metrics import get_metrics_collector, TimedOperation
from src.monitoring.logging import get_contextual_logger, RequestContext
from src.analytics.history import get_run_history_db
from src.analytics.engine import SimulationAnalytics


# ============================================================================
# Request/Response Models
# ============================================================================

class SingleRunRequest(BaseModel):
    """Single simulation run request."""
    dataset_path: str = Field(..., description="Path to prepared NetCDF/Zarr dataset")
    output_path: str = Field(..., description="Where to save simulation output")
    config: Dict[str, Any] = Field(..., description="Simulation configuration")


class BatchRunRequest(BaseModel):
    """Batch simulation runs request."""
    dataset_path: str = Field(..., description="Path to prepared dataset")
    output_base_path: str = Field(..., description="Base directory for all outputs")
    batch_configs: List[Dict[str, Any]] = Field(..., description="List of run configs")


class ValidationRequest(BaseModel):
    """Validation request for single run."""
    dataset_path: str = Field(..., description="Path to dataset")
    config: Dict[str, Any] = Field(..., description="Simulation configuration")


class BatchValidationRequest(BaseModel):
    """Validation request for batch runs."""
    dataset_path: str = Field(..., description="Path to dataset")
    batch_configs: List[Dict[str, Any]] = Field(..., description="List of configs")


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    version: str = "1.0.0"


# ============================================================================
# FastAPI App Setup
# ============================================================================

app = FastAPI(
    title="eDNA LPT Simulation Service API",
    description="REST API for Lagrangian Particle Tracking simulation execution and validation",
    version="1.0.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize logging and metrics
logger = get_contextual_logger(__name__)
metrics = get_metrics_collector()


# Request tracking middleware
@app.middleware("http")
async def track_requests(request: Request, call_next):
    """Middleware to track all HTTP requests."""
    request_id = str(uuid.uuid4())
    
    with RequestContext(
        request_id=request_id,
        endpoint=request.url.path,
        user_agent=request.headers.get("user-agent"),
    ):
        logger.info(f"Request started: {request.method} {request.url.path}")
        
        with TimedOperation(f"{request.method} {request.url.path}") as timer:
            response = await call_next(request)
        
        # Record metric
        metrics.record_request(
            method=request.method,
            endpoint=request.url.path,
            status_code=response.status_code,
            response_time_ms=timer.duration_ms,
            user_agent=request.headers.get("user-agent"),
        )
        
        logger.info(
            f"Request completed: {request.method} {request.url.path} "
            f"[{response.status_code}] ({timer.duration_ms:.1f}ms)"
        )
        
        return response


# Global service instance (initialized by caller)
_simulation_service: Optional[SimulationService] = None


def initialize_service(service: SimulationService):
    """Initialize the service (call this at server startup)."""
    global _simulation_service
    _simulation_service = service


def _get_service() -> SimulationService:
    """Get the service or raise 500 if not initialized."""
    if _simulation_service is None:
        raise HTTPException(
            status_code=500,
            detail="Simulation service not initialized. Call initialize_service() at startup."
        )
    return _simulation_service


# ============================================================================
# Health & Info Endpoints
# ============================================================================

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """
    Health check endpoint.
    
    Returns:
        {"status": "healthy", "version": "1.0.0"}
    """
    logger.info("Health check performed")
    return HealthResponse()


@app.get("/health/detailed", tags=["System", "Monitoring"])
async def health_check_detailed():
    """
    Detailed health check with metrics and system status.
    
    Returns:
        {
            "status": "healthy",
            "version": "1.0.0",
            "uptime_seconds": float,
            "requests": {...},
            "simulations": {...}
        }
    """
    health = metrics.get_health_details()
    health["status"] = "healthy"
    health["version"] = "1.0.0"
    logger.info("Detailed health check performed", extra={"detail": "full"})
    return health


@app.get("/metrics", tags=["Monitoring"])
async def get_metrics():
    """
    Prometheus-compatible metrics endpoint.
    
    Returns:
        Text-format Prometheus metrics
    """
    logger.info("Metrics endpoint accessed")
    prometheus_metrics = metrics.export_prometheus()
    return PlainTextResponse(prometheus_metrics, media_type="text/plain; charset=utf-8")


@app.get("/metrics/json", tags=["Monitoring"])
async def get_metrics_json():
    """
    JSON-formatted metrics export.
    
    Returns:
        Detailed metrics in JSON format
    """
    logger.info("JSON metrics endpoint accessed")
    return metrics.get_health_details()


@app.get("/version", tags=["System"])
async def get_version():
    """Get API version."""
    return {"version": "1.0.0"}


# ============================================================================
# Validation Endpoints
# ============================================================================

@app.post("/validate/single", tags=["Validation"])
async def validate_single_run(request: ValidationRequest):
    """
    Validate a single simulation configuration.
    
    Args:
        request: ValidationRequest with dataset_path and config
        
    Returns:
        {"valid": bool, "issues": [str]}
    """
    try:
        service = _get_service()
        is_valid, issues = service.preflight_single_run(
            request.dataset_path,
            request.config
        )
        return {
            "valid": is_valid,
            "issues": issues,
        }
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Validation failed: {str(e)}"
        )


@app.post("/validate/batch", tags=["Validation"])
async def validate_batch_runs(request: BatchValidationRequest):
    """
    Validate multiple simulation configurations.
    
    Args:
        request: BatchValidationRequest with dataset_path and batch_configs
        
    Returns:
        {
            "valid_configs": [...],
            "invalid_configs": [...],
            "valid_count": int,
            "invalid_count": int
        }
    """
    try:
        service = _get_service()
        valid_configs, invalid_configs = service.preflight_batch_run(
            request.dataset_path,
            request.batch_configs
        )
        return {
            "valid_configs": valid_configs,
            "invalid_configs": invalid_configs,
            "valid_count": len(valid_configs),
            "invalid_count": len(invalid_configs),
        }
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Batch validation failed: {str(e)}"
        )


# ============================================================================
# Execution Endpoints
# ============================================================================

@app.post("/run/single", tags=["Execution"])
async def run_single(request: SingleRunRequest, background_tasks: BackgroundTasks):
    """
    Execute a single simulation run.
    
    Args:
        request: SingleRunRequest with dataset_path, output_path, config
        
    Returns:
        RunResult object with status, timing, artifacts, errors
    """
    run_id = str(uuid.uuid4())
    timestamp_start = datetime.utcnow().isoformat() + "Z"
    
    try:
        service = _get_service()
        logger.info(f"Starting simulation run {run_id}")
        
        with TimedOperation("simulation_execution") as timer:
            # Create a progress callback that streams updates 
            progress_queue = asyncio.Queue()
            
            def progress_callback(percent: int, message: str):
                try:
                    asyncio.create_task(
                        progress_queue.put({"type": "progress", "percent": percent, "message": message}),
                    )
                except:
                    pass  # Silently skip if queue is full or event loop unavailable
            
            result = service.execute_single_run(
                request.dataset_path,
                request.output_path,
                request.config,
                progress_callback=progress_callback,
            )
        
        timestamp_end = datetime.utcnow().isoformat() + "Z"
        
        # Record metrics
        metrics.record_simulation(
            run_id=run_id,
            timestamp_start=timestamp_start,
            timestamp_end=timestamp_end,
            duration_seconds=result.elapsed_seconds,
            status=result.status if isinstance(result.status, str) else result.status.value,
            error_message=result.error_message,
            metadata={"output_path": result.output_path}
        )
        
        # Save to run history database
        try:
            db = get_run_history_db()
            db.save_run(
                run_id=run_id,
                status="succeeded" if result.status == RunStatus.SUCCEEDED or result.status == "succeeded" else "failed",
                timestamp_start=timestamp_start,
                timestamp_end=timestamp_end,
                duration_seconds=result.elapsed_seconds,
                config=request.config,
                dataset_path=request.dataset_path,
                output_path=result.output_path,
                particle_count=request.config.get("particle_count", 0),
                time_steps=request.config.get("time_steps", 0),
                output_size_mb=0,  # Can be calculated if needed
                endpoint_latency_ms=timer.duration_ms,
            )
        except Exception as db_error:
            logger.warning(f"Failed to save run to history database: {str(db_error)}")
        
        logger.info(f"Simulation {run_id} completed: {result.status}")
        
        return {
            "run_id": run_id,
            "status": result.status.value if hasattr(result.status, 'value') else result.status,
            "output_path": result.output_path,
            "error_message": result.error_message,
            "started_at_utc": result.started_at_utc,
            "ended_at_utc": result.ended_at_utc,
            "elapsed_seconds": result.elapsed_seconds,
            "artifacts": result.artifacts or [],
        }
    except Exception as e:
        timestamp_end = datetime.utcnow().isoformat() + "Z"
        
        # Record failure metric
        metrics.record_simulation(
            run_id=run_id,
            timestamp_start=timestamp_start,
            timestamp_end=timestamp_end,
            duration_seconds=(datetime.fromisoformat(timestamp_end.replace("Z", "+00:00")) - 
                            datetime.fromisoformat(timestamp_start.replace("Z", "+00:00"))).total_seconds(),
            status="failed",
            error_message=str(e)
        )
        
        # Save failed run to history database
        try:
            db = get_run_history_db()
            duration = (datetime.fromisoformat(timestamp_end.replace("Z", "+00:00")) - 
                       datetime.fromisoformat(timestamp_start.replace("Z", "+00:00"))).total_seconds()
            db.save_run(
                run_id=run_id,
                status="failed",
                timestamp_start=timestamp_start,
                timestamp_end=timestamp_end,
                duration_seconds=duration,
                config=request.config,
                dataset_path=request.dataset_path,
                output_path=request.output_path,
                particle_count=request.config.get("particle_count", 0),
                time_steps=request.config.get("time_steps", 0),
                output_size_mb=0,
                endpoint_latency_ms=0,
                error_message=str(e),
            )
        except Exception as db_error:
            logger.warning(f"Failed to save failed run to history database: {str(db_error)}")
        
        logger.error(f"Simulation {run_id} failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Simulation execution failed: {str(e)}"
        )


@app.post("/run/batch", tags=["Execution"])
async def run_batch(request: BatchRunRequest):
    """
    Execute multiple simulations sequentially.
    
    Args:
        request: BatchRunRequest with dataset_path, output_base_path, batch_configs
        
    Returns:
        {
            "summary": [...],
            "results": [...],
            "success_count": int,
            "total_count": int,
            "valid_count": int,
            "invalid_count": int
        }
    """
    try:
        service = _get_service()
        batch_result = service.execute_batch_runs(
            request.dataset_path,
            request.output_base_path,
            request.batch_configs,
            progress_callback=None,
        )
        
        # Convert results to JSON-serializable format
        results_serialized = []
        for result in batch_result.get("results", []):
            results_serialized.append({
                "status": result.status.value if hasattr(result.status, 'value') else str(result.status),
                "output_path": result.output_path,
                "error_message": result.error_message,
                "started_at_utc": result.started_at_utc,
                "ended_at_utc": result.ended_at_utc,
                "elapsed_seconds": result.elapsed_seconds,
            })
        
        return {
            "summary": batch_result.get("summary", []),
            "results": results_serialized,
            "success_count": batch_result.get("success_count", 0),
            "total_count": batch_result.get("total_count", 0),
            "valid_count": batch_result.get("valid_count", 0),
            "invalid_count": batch_result.get("invalid_count", 0),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Batch execution failed: {str(e)}"
        )


# ============================================================================
# Streaming Endpoints (for real-time progress)
# ============================================================================

@app.post("/run/single/stream", tags=["Execution"])
async def run_single_streaming(request: SingleRunRequest):
    """
    Execute single simulation with Server-Sent Events (SSE) progress streaming.
    
    Returns:
        Stream of events:
        - {"type": "progress", "percent": int, "message": str}
        - {"type": "result", "data": RunResult}
        - {"type": "error", "error": str}
    """
    async def event_generator():
        # Queue for progress updates
        progress_queue = asyncio.Queue()
        
        def progress_callback(percent: int, message: str):
            """Callback that puts events in queue."""
            try:
                asyncio.run_coroutine_threadsafe(
                    progress_queue.put({"type": "progress", "percent": percent, "message": message}),
                    asyncio.get_event_loop()
                )
            except Exception:
                pass
        
        try:
            service = _get_service()
            
            # Run simulation
            result = service.execute_single_run(
                request.dataset_path,
                request.output_path,
                request.config,
                progress_callback=progress_callback,
            )
            
            # Yield all queued progress updates
            while not progress_queue.empty():
                try:
                    event = progress_queue.get_nowait()
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.QueueEmpty:
                    break
            
            # Yield final result
            result_data = {
                "type": "result",
                "data": {
                    "status": result.status.value if hasattr(result.status, 'value') else str(result.status),
                    "output_path": result.output_path,
                    "error_message": result.error_message,
                    "started_at_utc": str(result.started_at_utc) if result.started_at_utc else None,
                    "ended_at_utc": str(result.ended_at_utc) if result.ended_at_utc else None,
                    "elapsed_seconds": result.elapsed_seconds,
                    "artifacts": result.artifacts,
                }
            }
            yield f"data: {json.dumps(result_data)}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ============================================================================
# Status Tracking (for long-running operations)
# ============================================================================

# In-memory run tracking (in production, use a database)
_active_runs: Dict[str, Dict] = {}


@app.get("/runs/{run_id}", tags=["Status"])
async def get_run_status(run_id: str):
    """
    Get status of a specific run.
    
    Args:
        run_id: Run identifier
        
    Returns:
        Run status or 404 if not found
    """
    if run_id not in _active_runs:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    
    return _active_runs[run_id]


@app.get("/runs", tags=["Status"])
async def list_runs(status: Optional[str] = Query(None)):
    """
    List all tracked runs, optionally filtered by status.
    
    Args:
        status: Optional status filter (RUNNING, SUCCEEDED, FAILED, etc.)
        
    Returns:
        List of run records
    """
    runs = list(_active_runs.values())
    
    if status:
        runs = [r for r in runs if r.get("status") == status]
    
    return runs


# ============================================================================
# Analytics Endpoints
# ============================================================================

@app.get("/analytics/summary", tags=["Analytics"])
async def analytics_summary(days: int = Query(7, description="Days to analyze")):
    """
    Get summary analytics for recent runs.
    
    Args:
        days: Number of days to analyze (default: 7)
        
    Returns:
        Dictionary with summary metrics:
        - success_rate: Percentage of successful runs
        - avg_duration: Average run duration in seconds
        - total_particles: Total particles executed
        - efficiency_score: Overall efficiency metric (0-100)
    """
    try:
        db = get_run_history_db()
        analytics = SimulationAnalytics(db)
        
        efficiency = analytics.get_efficiency_metrics(days=days)
        
        logger.info(f"Analytics summary retrieved for {days} days")
        return efficiency
    except Exception as e:
        logger.error(f"Analytics summary failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Analytics failed: {str(e)}")


@app.get("/analytics/trends", tags=["Analytics"])
async def analytics_trends(days: int = Query(30, description="Days to analyze")):
    """
    Get performance trends over time.
    
    Args:
        days: Number of days to analyze (default: 30)
        
    Returns:
        List of detected trends with direction and magnitude:
        - metric: "duration", "success_rate", "particles_per_sec"
        - trend: "improving", "degrading", "stable"
        - change_percent: Percentage change
        - details: Human-readable description
    """
    try:
        db = get_run_history_db()
        analytics = SimulationAnalytics(db)
        
        trends = analytics.get_performance_trends(days=days)
        
        logger.info(f"Trends retrieved for {days} days ({len(trends)} trends)")
        return {"trends": [t.__dict__ for t in trends]}
    except Exception as e:
        logger.error(f"Trends analysis failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Trends analysis failed: {str(e)}")


@app.get("/analytics/anomalies", tags=["Analytics"])
async def analytics_anomalies(
    hours: int = Query(24, description="Hours to lookback"),
    sensitivity: str = Query("medium", description="Detection sensitivity: low/medium/high")
):
    """
    Detect anomalies in recent simulation runs.
    
    Args:
        hours: Hours to analyze (default: 24)
        sensitivity: Detection sensitivity (default: medium)
        
    Returns:
        List of detected anomalies:
        - type: "slow_run", "failure_spike", etc
        - severity: "low", "medium", "high"
        - description: Human-readable description
        - timestamp: When the anomaly was detected
    """
    try:
        db = get_run_history_db()
        analytics = SimulationAnalytics(db)
        
        anomalies = analytics.detect_anomalies(lookback_hours=hours, sensitivity=sensitivity)
        
        logger.info(f"Anomalies detected: {len(anomalies)} in {hours}h with {sensitivity} sensitivity")
        return {"anomalies": [a.__dict__ for a in anomalies]}
    except Exception as e:
        logger.error(f"Anomaly detection failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Anomaly detection failed: {str(e)}")


@app.get("/analytics/performance/{run_id}", tags=["Analytics"])
async def analytics_run_performance(run_id: str):
    """
    Get detailed performance profile for a specific run.
    
    Args:
        run_id: Run identifier
        
    Returns:
        Performance profile with:
        - duration, particle count, output size
        - throughput metrics (particles/sec, MB/sec)
        - efficiency estimates
    """
    try:
        db = get_run_history_db()
        analytics = SimulationAnalytics(db)
        
        profile = analytics.get_resource_profile(run_id)
        
        if "error" in profile:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        
        logger.info(f"Performance profile retrieved for run {run_id}")
        return profile
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Performance profile failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Performance analysis failed: {str(e)}")


@app.post("/analytics/compare", tags=["Analytics"])
async def analytics_compare_runs(run_ids: List[str]):
    """
    Compare multiple runs side-by-side.
    
    Args:
        run_ids: List of run IDs to compare
        
    Returns:
        Comparison data with side-by-side metrics and aggregated summary
    """
    try:
        db = get_run_history_db()
        analytics = SimulationAnalytics(db)
        
        comparison = analytics.compare_runs(run_ids)
        
        logger.info(f"Comparison completed for {len(run_ids)} runs")
        return comparison
    except Exception as e:
        logger.error(f"Comparison failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Run comparison failed: {str(e)}")


@app.get("/analytics/best-runs", tags=["Analytics"])
async def analytics_best_runs(limit: int = Query(10, description="Number of runs to return")):
    """
    Get best performing runs.
    
    Args:
        limit: Max runs to return
        
    Returns:
        List of top performing runs with scores and metrics
    """
    try:
        db = get_run_history_db()
        analytics = SimulationAnalytics(db)
        
        best_runs = analytics.get_best_performing_runs(limit=limit)
        
        logger.info(f"Retrieved {len(best_runs)} best runs")
        return {"best_runs": best_runs}
    except Exception as e:
        logger.error(f"Best runs retrieval failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Best runs retrieval failed: {str(e)}")


@app.get("/analytics/worst-runs", tags=["Analytics"])
async def analytics_worst_runs(limit: int = Query(10, description="Number of runs to return")):
    """
    Get worst performing runs.
    
    Args:
        limit: Max runs to return
        
    Returns:
        List of worst performing runs with issues and metrics
    """
    try:
        db = get_run_history_db()
        analytics = SimulationAnalytics(db)
        
        worst_runs = analytics.get_worst_performing_runs(limit=limit)
        
        logger.info(f"Retrieved {len(worst_runs)} worst runs")
        return {"worst_runs": worst_runs}
    except Exception as e:
        logger.error(f"Worst runs retrieval failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Worst runs retrieval failed: {str(e)}")


@app.get("/analytics/runs", tags=["Analytics"])
async def analytics_list_runs(
    status: Optional[str] = Query(None, description="Filter by status: succeeded/failed/canceled"),
    limit: int = Query(100, description="Max runs to return"),
    offset: int = Query(0, description="Offset for pagination")
):
    """
    List tracked runs with optional filtering.
    
    Args:
        status: Optional status filter
        limit: Maximum runs to return
        offset: Pagination offset
        
    Returns:
        List of runs matching criteria with metadata
    """
    try:
        db = get_run_history_db()
        
        runs = db.get_runs(status=status, limit=limit, offset=offset)
        
        logger.info(f"Listed {len(runs)} runs (status={status}, limit={limit})")
        return {"runs": runs, "count": len(runs)}
    except Exception as e:
        logger.error(f"Run listing failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Run listing failed: {str(e)}")


@app.get("/analytics/export/json", tags=["Analytics", "Export"])
async def analytics_export_json():
    """
    Export all run history as JSON.
    
    Returns:
        JSON file with complete run history and statistics
    """
    try:
        db = get_run_history_db()
        
        json_data = db.export_json()
        
        logger.info("Run history exported to JSON")
        return JSONResponse(json.loads(json_data))
    except Exception as e:
        logger.error(f"JSON export failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"JSON export failed: {str(e)}")


@app.get("/analytics/export/csv", tags=["Analytics", "Export"])
async def analytics_export_csv(output_path: Optional[str] = Query(None, description="Optional file path")):
    """
    Export run history as CSV.
    
    Args:
        output_path: Optional file path to save CSV
        
    Returns:
        CSV content or file path if saved
    """
    try:
        db = get_run_history_db()
        
        csv_path = db.export_csv(output_path=output_path)
        
        logger.info(f"Run history exported to CSV: {csv_path}")
        return {"csv_path": csv_path, "message": "CSV export completed"}
    except Exception as e:
        logger.error(f"CSV export failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"CSV export failed: {str(e)}")


# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    from . import get_service
    
    # Initialize the service
    try:
        service = get_service()
        initialize_service(service)
        print("✓ Simulation service initialized")
    except RuntimeError as e:
        print(f"⚠ Service not pre-initialized: {e}")
        print("  Run api_init.initialize_simulation_api() before starting server")
    
    # Start server
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
