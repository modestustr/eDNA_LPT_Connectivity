"""
Monitoring & Metrics Module
=============================
Prometheus-compatible metrics collection for simulation execution.

Metrics tracked:
- API request counts and latencies
- Simulation execution metrics (count, duration, success rate)
- System resource usage (when running simulations)
- Error rates and types
"""

import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import json


@dataclass
class RequestMetric:
    """Single HTTP request metric."""
    
    timestamp: str  # ISO format
    method: str  # GET, POST, etc
    endpoint: str  # /health, /run/single, etc
    status_code: int
    response_time_ms: float
    user_agent: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class SimulationMetric:
    """Single simulation execution metric."""
    
    run_id: str
    timestamp_start: str  # ISO format
    timestamp_end: str  # ISO format
    duration_seconds: float
    status: str  # "succeeded", "failed", "canceled"
    particle_count: Optional[int] = None
    time_steps: Optional[int] = None
    output_size_mb: Optional[float] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class MetricsCollector:
    """
    Collects and maintains API and simulation metrics.
    
    Supports:
    - Request-level metrics (count, latency by endpoint)
    - Simulation metrics (duration, success rate, particle counts)
    - Aggregated statistics (totals, averages)
    - Export to Prometheus format
    """

    def __init__(self):
        """Initialize metrics collector."""
        self.request_metrics: List[RequestMetric] = []
        self.simulation_metrics: List[SimulationMetric] = []
        self.start_time = datetime.utcnow()
        
        # Ephemeral counters (reset on startup)
        self.total_requests = 0
        self.total_simulations = 0
        self.failed_requests = 0
        self.failed_simulations = 0

    def record_request(
        self,
        method: str,
        endpoint: str,
        status_code: int,
        response_time_ms: float,
        user_agent: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Record HTTP request metric."""
        metric = RequestMetric(
            timestamp=datetime.utcnow().isoformat() + "Z",
            method=method,
            endpoint=endpoint,
            status_code=status_code,
            response_time_ms=response_time_ms,
            user_agent=user_agent,
            error_message=error_message,
        )
        self.request_metrics.append(metric)
        self.total_requests += 1
        
        if status_code >= 400:
            self.failed_requests += 1

    def record_simulation(
        self,
        run_id: str,
        timestamp_start: str,
        timestamp_end: str,
        duration_seconds: float,
        status: str,
        particle_count: Optional[int] = None,
        time_steps: Optional[int] = None,
        output_size_mb: Optional[float] = None,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record simulation execution metric."""
        metric = SimulationMetric(
            run_id=run_id,
            timestamp_start=timestamp_start,
            timestamp_end=timestamp_end,
            duration_seconds=duration_seconds,
            status=status,
            particle_count=particle_count,
            time_steps=time_steps,
            output_size_mb=output_size_mb,
            error_message=error_message,
            metadata=metadata or {},
        )
        self.simulation_metrics.append(metric)
        self.total_simulations += 1
        
        if status == "failed":
            self.failed_simulations += 1

    def get_request_stats(self) -> Dict[str, Any]:
        """Get aggregated request statistics."""
        if not self.request_metrics:
            return {
                "total_requests": 0,
                "total_errors": 0,
                "avg_response_time_ms": 0.0,
                "by_endpoint": {},
            }
        
        # Group by endpoint
        by_endpoint = {}
        for metric in self.request_metrics:
            if metric.endpoint not in by_endpoint:
                by_endpoint[metric.endpoint] = {
                    "count": 0,
                    "errors": 0,
                    "response_times": [],
                }
            
            by_endpoint[metric.endpoint]["count"] += 1
            by_endpoint[metric.endpoint]["response_times"].append(metric.response_time_ms)
            
            if metric.status_code >= 400:
                by_endpoint[metric.endpoint]["errors"] += 1
        
        # Calculate averages
        for endpoint in by_endpoint:
            times = by_endpoint[endpoint]["response_times"]
            by_endpoint[endpoint]["avg_response_time_ms"] = sum(times) / len(times) if times else 0.0
            by_endpoint[endpoint]["min_response_time_ms"] = min(times) if times else 0.0
            by_endpoint[endpoint]["max_response_time_ms"] = max(times) if times else 0.0
            del by_endpoint[endpoint]["response_times"]
        
        return {
            "total_requests": self.total_requests,
            "total_errors": self.failed_requests,
            "error_rate": self.failed_requests / self.total_requests if self.total_requests > 0 else 0.0,
            "avg_response_time_ms": sum(m.response_time_ms for m in self.request_metrics) / len(self.request_metrics),
            "by_endpoint": by_endpoint,
        }

    def get_simulation_stats(self) -> Dict[str, Any]:
        """Get aggregated simulation statistics."""
        if not self.simulation_metrics:
            return {
                "total_simulations": 0,
                "succeeded": 0,
                "failed": 0,
                "avg_duration_seconds": 0.0,
                "total_particles_executed": 0,
            }
        
        succeeded = sum(1 for m in self.simulation_metrics if m.status == "succeeded")
        failed = sum(1 for m in self.simulation_metrics if m.status == "failed")
        durations = [m.duration_seconds for m in self.simulation_metrics]
        total_particles = sum(m.particle_count for m in self.simulation_metrics if m.particle_count)
        total_output_mb = sum(m.output_size_mb for m in self.simulation_metrics if m.output_size_mb)
        
        return {
            "total_simulations": self.total_simulations,
            "succeeded": succeeded,
            "failed": failed,
            "success_rate": succeeded / self.total_simulations if self.total_simulations > 0 else 0.0,
            "avg_duration_seconds": sum(durations) / len(durations) if durations else 0.0,
            "min_duration_seconds": min(durations) if durations else 0.0,
            "max_duration_seconds": max(durations) if durations else 0.0,
            "total_particles_executed": total_particles,
            "total_output_mb": round(total_output_mb, 2),
        }

    def get_health_details(self) -> Dict[str, Any]:
        """Get detailed health information."""
        uptime_seconds = (datetime.utcnow() - self.start_time).total_seconds()
        
        req_stats = self.get_request_stats()
        sim_stats = self.get_simulation_stats()
        
        return {
            "uptime_seconds": uptime_seconds,
            "startup_time": self.start_time.isoformat() + "Z",
            "requests": req_stats,
            "simulations": sim_stats,
        }

    def export_prometheus(self) -> str:
        """Export metrics in Prometheus text format."""
        req_stats = self.get_request_stats()
        sim_stats = self.get_simulation_stats()
        
        lines = [
            "# HELP eDNA_requests_total Total HTTP requests",
            "# TYPE eDNA_requests_total counter",
            f"eDNA_requests_total {self.total_requests}",
            "",
            "# HELP eDNA_requests_errors_total Total failed requests",
            "# TYPE eDNA_requests_errors_total counter",
            f"eDNA_requests_errors_total {self.failed_requests}",
            "",
            "# HELP eDNA_request_duration_ms Average request duration",
            "# TYPE eDNA_request_duration_ms gauge",
            f"eDNA_request_duration_ms {req_stats.get('avg_response_time_ms', 0):.2f}",
            "",
            "# HELP eDNA_simulations_total Total simulations executed",
            "# TYPE eDNA_simulations_total counter",
            f"eDNA_simulations_total {self.total_simulations}",
            "",
            "# HELP eDNA_simulations_succeeded Total successful simulations",
            "# TYPE eDNA_simulations_succeeded counter",
            f"eDNA_simulations_succeeded {sim_stats.get('succeeded', 0)}",
            "",
            "# HELP eDNA_simulations_failed Total failed simulations",
            "# TYPE eDNA_simulations_failed counter",
            f"eDNA_simulations_failed {sim_stats.get('failed', 0)}",
            "",
            "# HELP eDNA_simulation_duration_seconds Average simulation duration",
            "# TYPE eDNA_simulation_duration_seconds gauge",
            f"eDNA_simulation_duration_seconds {sim_stats.get('avg_duration_seconds', 0):.2f}",
            "",
            "# HELP eDNA_particles_total Total particles executed",
            "# TYPE eDNA_particles_total counter",
            f"eDNA_particles_total {sim_stats.get('total_particles_executed', 0)}",
            "",
        ]
        
        return "\n".join(lines)

    def export_json(self, filepath: Optional[Path] = None) -> str:
        """Export all metrics as JSON."""
        export_data = {
            "export_time": datetime.utcnow().isoformat() + "Z",
            "uptime_seconds": (datetime.utcnow() - self.start_time).total_seconds(),
            "request_metrics": [
                {
                    "timestamp": m.timestamp,
                    "method": m.method,
                    "endpoint": m.endpoint,
                    "status_code": m.status_code,
                    "response_time_ms": m.response_time_ms,
                    "user_agent": m.user_agent,
                    "error_message": m.error_message,
                }
                for m in self.request_metrics[-1000:]  # Last 1000 to prevent huge exports
            ],
            "simulation_metrics": [
                {
                    "run_id": m.run_id,
                    "timestamp_start": m.timestamp_start,
                    "timestamp_end": m.timestamp_end,
                    "duration_seconds": m.duration_seconds,
                    "status": m.status,
                    "particle_count": m.particle_count,
                    "time_steps": m.time_steps,
                    "output_size_mb": m.output_size_mb,
                    "error_message": m.error_message,
                    "metadata": m.metadata,
                }
                for m in self.simulation_metrics
            ],
            "statistics": {
                "requests": self.get_request_stats(),
                "simulations": self.get_simulation_stats(),
            },
        }
        
        json_str = json.dumps(export_data, indent=2)
        
        if filepath:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, "w") as f:
                f.write(json_str)
        
        return json_str


# Global metrics instance
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Get or create global metrics collector."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


# Context manager for timing request/operation duration
class TimedOperation:
    """Context manager to measure operation duration."""
    
    def __init__(self, name: str = "operation"):
        self.name = name
        self.start_time = None
        self.duration_ms = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.duration_ms = (time.time() - self.start_time) * 1000
        return False


# Run with: python -m pytest tests/test_monitoring.py -v
if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
