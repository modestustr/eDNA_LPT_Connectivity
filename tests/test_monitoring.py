"""
Monitoring Module Tests

Tests for metrics collection, Prometheus export, and health endpoints.
"""

import pytest
from pathlib import Path
from datetime import datetime
import json
import tempfile
import sys

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.monitoring.metrics import MetricsCollector, get_metrics_collector, TimedOperation
from src.core.simulation_contracts import RunStatus


class TestMetricsCollector:
    """Test metrics collection functionality."""
    
    @pytest.fixture
    def collector(self):
        """Create a fresh metrics collector."""
        return MetricsCollector()
    
    def test_record_single_request(self, collector):
        """Test recording a single HTTP request metric."""
        collector.record_request(
            method="POST",
            endpoint="/run/single",
            status_code=200,
            response_time_ms=1234.5,
            user_agent="test-client/1.0"
        )
        
        assert collector.total_requests == 1
        assert len(collector.request_metrics) == 1
        assert collector.request_metrics[0].endpoint == "/run/single"
        assert collector.request_metrics[0].status_code == 200

    def test_record_request_with_error(self, collector):
        """Test recording a failed request."""
        collector.record_request(
            method="GET",
            endpoint="/invalid",
            status_code=404,
            response_time_ms=50.0,
            error_message="Not found"
        )
        
        assert collector.total_requests == 1
        assert collector.failed_requests == 1

    def test_record_simulation_succeeded(self, collector):
        """Test recording a successful simulation."""
        collector.record_simulation(
            run_id="sim-001",
            timestamp_start="2024-01-01T00:00:00Z",
            timestamp_end="2024-01-01T00:10:00Z",
            duration_seconds=600.0,
            status="succeeded",
            particle_count=100,
            time_steps=60
        )
        
        assert collector.total_simulations == 1
        assert len(collector.simulation_metrics) == 1
        metric = collector.simulation_metrics[0]
        assert metric.run_id == "sim-001"
        assert metric.status == "succeeded"
        assert metric.particle_count == 100

    def test_record_simulation_failed(self, collector):
        """Test recording a failed simulation."""
        collector.record_simulation(
            run_id="sim-002",
            timestamp_start="2024-01-01T00:00:00Z",
            timestamp_end="2024-01-01T00:05:00Z",
            duration_seconds=300.0,
            status="failed",
            error_message="Out of memory"
        )
        
        assert collector.total_simulations == 1
        assert collector.failed_simulations == 1

    def test_get_request_stats(self, collector):
        """Test request statistics aggregation."""
        # Record several requests
        collector.record_request("GET", "/health", 200, 10.0)
        collector.record_request("POST", "/run/single", 200, 1000.0)
        collector.record_request("POST", "/run/single", 200, 1100.0)
        collector.record_request("GET", "/invalid", 404, 5.0)
        
        stats = collector.get_request_stats()
        
        assert stats["total_requests"] == 4
        assert stats["total_errors"] == 1
        assert stats["error_rate"] == 0.25
        assert "/health" in stats["by_endpoint"]
        assert stats["by_endpoint"]["/health"]["count"] == 1
        assert stats["by_endpoint"]["/run/single"]["count"] == 2

    def test_get_simulation_stats(self, collector):
        """Test simulation statistics aggregation."""
        # Record several simulations
        collector.record_simulation("sim-1", "2024-01-01T00:00:00Z", "2024-01-01T00:10:00Z", 
                                    600.0, "succeeded", particle_count=100)
        collector.record_simulation("sim-2", "2024-01-01T00:00:00Z", "2024-01-01T00:05:00Z",
                                    300.0, "failed", error_message="Error")
        
        stats = collector.get_simulation_stats()
        
        assert stats["total_simulations"] == 2
        assert stats["succeeded"] == 1
        assert stats["failed"] == 1
        assert stats["success_rate"] == 0.5
        assert stats["avg_duration_seconds"] == 450.0  # (600 + 300) / 2

    def test_export_prometheus(self, collector):
        """Test Prometheus format export."""
        collector.record_request("GET", "/health", 200, 10.0)
        collector.record_simulation("sim-1", "2024-01-01T00:00:00Z", "2024-01-01T00:10:00Z",
                                    600.0, "succeeded")
        
        prometheus_output = collector.export_prometheus()
        
        assert "eDNA_requests_total 1" in prometheus_output
        assert "eDNA_simulations_total 1" in prometheus_output
        assert "eDNA_simulations_succeeded 1" in prometheus_output
        assert "# HELP" in prometheus_output
        assert "# TYPE" in prometheus_output

    def test_export_json(self, collector):
        """Test JSON export functionality."""
        collector.record_request("GET", "/health", 200, 10.0)
        collector.record_simulation("sim-1", "2024-01-01T00:00:00Z", "2024-01-01T00:10:00Z",
                                    600.0, "succeeded")
        
        json_output = collector.export_json()
        data = json.loads(json_output)
        
        assert "export_time" in data
        assert "uptime_seconds" in data
        assert "request_metrics" in data
        assert "simulation_metrics" in data
        assert "statistics" in data
        assert len(data["request_metrics"]) == 1
        assert len(data["simulation_metrics"]) == 1

    def test_export_json_to_file(self, collector):
        """Test JSON export to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "metrics.json"
            
            collector.record_request("GET", "/health", 200, 10.0)
            json_str = collector.export_json(filepath)
            
            assert filepath.exists()
            with open(filepath) as f:
                data = json.load(f)
            
            assert "statistics" in data
            assert data["statistics"]["requests"]["total_requests"] == 1

    def test_get_health_details(self, collector):
        """Test detailed health information."""
        collector.record_request("GET", "/health", 200, 10.0)
        collector.record_simulation("sim-1", "2024-01-01T00:00:00Z", "2024-01-01T00:10:00Z",
                                    600.0, "succeeded", particle_count=100)
        
        health = collector.get_health_details()
        
        assert "uptime_seconds" in health
        assert "startup_time" in health
        assert "requests" in health
        assert "simulations" in health
        assert health["requests"]["total_requests"] == 1
        assert health["simulations"]["total_simulations"] == 1

    def test_timed_operation(self):
        """Test TimedOperation context manager."""
        import time
        
        with TimedOperation("test_op") as timer:
            time.sleep(0.01)  # Sleep 10ms
        
        assert timer.duration_ms >= 10  # Should be at least 10ms


class TestGlobalMetricsCollector:
    """Test global metrics collector initialization."""
    
    def test_get_global_collector(self):
        """Test getting singleton metrics collector."""
        collector1 = get_metrics_collector()
        collector2 = get_metrics_collector()
        
        assert collector1 is collector2  # Should be same instance


# Run with: pytest tests/test_monitoring.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
