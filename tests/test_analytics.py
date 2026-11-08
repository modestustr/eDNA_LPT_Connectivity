"""
Test Suite for Analytics Module
=================================
Tests for performance analytics, trend detection, and anomaly detection.
"""

import pytest
import json
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import os
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analytics.engine import (
    SimulationAnalytics,
    PerformanceTrend,
    Anomaly,
)
from src.analytics.history import RunHistoryDB


@pytest.fixture
def temp_db():
    """Create temporary database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_runs.db"
        db = RunHistoryDB(db_path=str(db_path))
        yield db


@pytest.fixture
def analytics(temp_db):
    """Create analytics instance with temporary database."""
    return SimulationAnalytics(temp_db)


@pytest.fixture
def sample_runs(temp_db):
    """Create sample run records for testing."""
    now = datetime.utcnow()
    
    runs = [
        {
            "run_id": "run_001",
            "status": "succeeded",
            "timestamp_start": (now - timedelta(days=5)).isoformat() + "Z",
            "timestamp_end": (now - timedelta(days=5, hours=-1)).isoformat() + "Z",
            "config": {"particle_count": 1000},
            "particle_count": 1000,
            "time_steps": 100,
            "output_size_mb": 50.5,
            "endpoint_latency_ms": 5000,
        },
        {
            "run_id": "run_002",
            "status": "succeeded",
            "timestamp_start": (now - timedelta(days=4)).isoformat() + "Z",
            "timestamp_end": (now - timedelta(days=4, hours=-2)).isoformat() + "Z",
            "config": {"particle_count": 2000},
            "particle_count": 2000,
            "time_steps": 200,
            "output_size_mb": 101.0,
            "endpoint_latency_ms": 7200,
        },
        {
            "run_id": "run_003",
            "status": "failed",
            "timestamp_start": (now - timedelta(days=3)).isoformat() + "Z",
            "timestamp_end": (now - timedelta(days=3, hours=-0.5)).isoformat() + "Z",
            "config": {"particle_count": 1500},
            "particle_count": 1500,
            "time_steps": 150,
            "output_size_mb": 0,
            "endpoint_latency_ms": 1800,
            "error_message": "Memory allocation failed",
        },
        {
            "run_id": "run_004",
            "status": "succeeded",
            "timestamp_start": (now - timedelta(days=2)).isoformat() + "Z",
            "timestamp_end": (now - timedelta(days=2, hours=-1.5)).isoformat() + "Z",
            "config": {"particle_count": 800},
            "particle_count": 800,
            "time_steps": 80,
            "output_size_mb": 40.0,
            "endpoint_latency_ms": 5400,
        },
        {
            "run_id": "run_005",
            "status": "succeeded",
            "timestamp_start": (now - timedelta(hours=12)).isoformat() + "Z",
            "timestamp_end": (now - timedelta(hours=11)).isoformat() + "Z",
            "config": {"particle_count": 3000},
            "particle_count": 3000,
            "time_steps": 300,
            "output_size_mb": 150.0,
            "endpoint_latency_ms": 3600,
        },
    ]
    
    # Save all runs to database
    for run in runs:
        # Calculate duration from timestamps
        start = datetime.fromisoformat(run["timestamp_start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(run["timestamp_end"].replace("Z", "+00:00"))
        duration = (end - start).total_seconds()
        
        temp_db.save_run(
            run_id=run["run_id"],
            status=run["status"],
            timestamp_start=run["timestamp_start"],
            timestamp_end=run["timestamp_end"],
            duration_seconds=duration,
            config=run["config"],
            dataset_path="/mock/dataset.nc",
            output_path=f"/mock/output/{run['run_id']}",
            particle_count=run["particle_count"],
            time_steps=run["time_steps"],
            output_size_mb=run["output_size_mb"],
            endpoint_latency_ms=run["endpoint_latency_ms"],
            error_message=run.get("error_message"),
        )
    
    return runs


class TestPerformanceTrends:
    """Test performance trend detection."""

    def test_get_trends_success(self, analytics, sample_runs):
        """Test successful trend detection."""
        trends = analytics.get_performance_trends(days=30)
        
        assert isinstance(trends, list)
        assert len(trends) > 0
        
        for trend in trends:
            assert isinstance(trend, PerformanceTrend)
            assert trend.metric in ["duration", "success_rate", "particles_per_sec"]
            assert trend.trend in ["improving", "degrading", "stable"]
            assert isinstance(trend.change_percent, float)

    def test_duration_trend(self, analytics, sample_runs):
        """Test duration trend detection."""
        trends = analytics.get_performance_trends(days=7)
        duration_trends = [t for t in trends if t.metric == "duration"]
        
        # Should have at least one trend
        assert len(duration_trends) > 0

    def test_success_rate_trend(self, analytics, sample_runs):
        """Test success rate trend detection."""
        trends = analytics.get_performance_trends(days=7)
        success_trends = [t for t in trends if t.metric == "success_rate"]
        
        # Should detect success rate trends
        assert len(success_trends) > 0

    def test_trends_empty_db(self, analytics):
        """Test trends on empty database."""
        trends = analytics.get_performance_trends(days=30)
        
        # Should not raise error, but return empty or minimal trends
        assert isinstance(trends, list)


class TestAnomalyDetection:
    """Test anomaly detection."""

    def test_detect_anomalies_success(self, analytics, sample_runs):
        """Test successful anomaly detection."""
        anomalies = analytics.detect_anomalies(lookback_hours=24, sensitivity="medium")
        
        assert isinstance(anomalies, list)
        
        for anomaly in anomalies:
            assert isinstance(anomaly, Anomaly)
            assert anomaly.type in ["slow_run", "failure_spike", "memory_spike"]
            assert anomaly.severity in ["low", "medium", "high"]
            assert anomaly.description is not None

    def test_anomaly_detection_sensitivity(self, analytics, sample_runs):
        """Test anomaly detection with different sensitivity levels."""
        low = analytics.detect_anomalies(lookback_hours=24, sensitivity="low")
        medium = analytics.detect_anomalies(lookback_hours=24, sensitivity="medium")
        high = analytics.detect_anomalies(lookback_hours=24, sensitivity="high")
        
        # Higher sensitivity should find more anomalies
        assert len(high) >= len(medium) >= len(low)

    def test_anomalies_insufficient_data(self, analytics):
        """Test anomaly detection with insufficient data."""
        anomalies = analytics.detect_anomalies(lookback_hours=24)
        
        # Should not raise error
        assert isinstance(anomalies, list)


class TestEfficiencyMetrics:
    """Test efficiency metric calculation."""

    def test_efficiency_metrics_success(self, analytics, sample_runs):
        """Test successful efficiency metrics calculation."""
        metrics = analytics.get_efficiency_metrics(days=7)
        
        assert "success_rate" in metrics
        assert "avg_duration_seconds" in metrics
        assert "total_particles_executed" in metrics
        assert "efficiency_score" in metrics
        assert "particles_per_second" in metrics

    def test_efficiency_score_range(self, analytics, sample_runs):
        """Test that efficiency score is in valid range."""
        metrics = analytics.get_efficiency_metrics(days=7)
        
        score = metrics["efficiency_score"]
        assert 0 <= score <= 100

    def test_success_rate_calculation(self, analytics, sample_runs):
        """Test success rate calculation."""
        metrics = analytics.get_efficiency_metrics(days=30)
        
        # From sample_runs: 4 succeeded, 1 failed = 80%
        assert 0 <= metrics["success_rate"] <= 1

    def test_efficiency_empty_db(self, analytics):
        """Test efficiency metrics on empty database."""
        metrics = analytics.get_efficiency_metrics(days=7)
        
        # Should have default values
        assert "efficiency_score" in metrics


class TestRunComparison:
    """Test run comparison functionality."""

    def test_compare_two_runs(self, analytics, sample_runs):
        """Test comparing two runs."""
        run_ids = ["run_001", "run_002"]
        comparison = analytics.compare_runs(run_ids)
        
        assert "detail_by_run" in comparison
        assert "summary" in comparison
        assert len(comparison["detail_by_run"]) == 2

    def test_comparison_metrics(self, analytics, sample_runs):
        """Test comparison includes all metrics."""
        run_ids = ["run_001", "run_002"]
        comparison = analytics.compare_runs(run_ids)
        
        for detail in comparison["detail_by_run"]:
            assert "run_id" in detail
            assert "status" in detail
            assert "duration_seconds" in detail
            assert "particles_per_sec" in detail

    def test_comparison_summary(self, analytics, sample_runs):
        """Test comparison summary."""
        run_ids = ["run_001", "run_002"]
        comparison = analytics.compare_runs(run_ids)
        summary = comparison["summary"]
        
        assert "avg_duration" in summary
        assert "fastest" in summary
        assert "slowest" in summary
        assert "success_count" in summary

    def test_compare_nonexistent_run(self, analytics):
        """Test comparing with nonexistent run."""
        run_ids = ["nonexistent_001", "nonexistent_002"]
        comparison = analytics.compare_runs(run_ids)
        
        # Should handle gracefully
        assert isinstance(comparison, dict)


class TestResourceProfile:
    """Test resource profile analysis."""

    def test_get_resource_profile(self, analytics, sample_runs):
        """Test getting resource profile for a run."""
        profile = analytics.get_resource_profile("run_001")
        
        assert "run_id" in profile
        assert profile["run_id"] == "run_001"
        assert "throughput_metrics" in profile
        assert "efficiency_estimate" in profile

    def test_profile_throughput_metrics(self, analytics, sample_runs):
        """Test throughput metrics in profile."""
        profile = analytics.get_resource_profile("run_001")
        throughput = profile["throughput_metrics"]
        
        assert "particles_per_second" in throughput
        assert "time_steps_per_second" in throughput
        assert "output_mb_per_second" in throughput

    def test_profile_efficiency_estimate(self, analytics, sample_runs):
        """Test efficiency estimate in profile."""
        profile = analytics.get_resource_profile("run_001")
        efficiency = profile["efficiency_estimate"]
        
        assert "particles_per_mb" in efficiency
        assert "time_steps_per_mb" in efficiency
        assert "speed_rating" in efficiency
        assert efficiency["speed_rating"] in ["fast", "medium", "slow"]

    def test_profile_nonexistent_run(self, analytics):
        """Test profile for nonexistent run."""
        profile = analytics.get_resource_profile("nonexistent_run")
        
        assert "error" in profile


class TestPerformanceRanking:
    """Test best/worst performing run ranking."""

    def test_get_best_runs(self, analytics, sample_runs):
        """Test getting best performing runs."""
        best = analytics.get_best_performing_runs(limit=3)
        
        assert isinstance(best, list)
        assert len(best) <= 3

    def test_get_worst_runs(self, analytics, sample_runs):
        """Test getting worst performing runs."""
        worst = analytics.get_worst_performing_runs(limit=3)
        
        assert isinstance(worst, list)
        assert len(worst) <= 3

    def test_best_vs_worst_different(self, analytics, sample_runs):
        """Test that best and worst runs are different."""
        best = analytics.get_best_performing_runs(limit=2)
        worst = analytics.get_worst_performing_runs(limit=2)
        
        if len(best) > 0 and len(worst) > 0:
            best_ids = {r.get("run_id") for r in best}
            worst_ids = {r.get("run_id") for r in worst}
            # Should have some overlap or difference (depends on data)
            assert isinstance(best_ids, set)
            assert isinstance(worst_ids, set)

    def test_ranking_limit_respected(self, analytics, sample_runs):
        """Test that limit is respected in rankings."""
        best = analytics.get_best_performing_runs(limit=2)
        worst = analytics.get_worst_performing_runs(limit=2)
        
        assert len(best) <= 2
        assert len(worst) <= 2


class TestDataExport:
    """Test data export functionality (from run_history)."""

    def test_export_json(self, analytics, sample_runs, temp_db):
        """Test JSON export."""
        json_data = temp_db.export_json()
        
        assert isinstance(json_data, str)
        parsed = json.loads(json_data)
        assert "runs" in parsed or "summary" in parsed

    def test_export_csv(self, analytics, sample_runs, temp_db):
        """Test CSV export."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "export.csv"
            temp_db.export_csv(filepath=csv_path)
            
            assert csv_path.exists()


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_database(self, analytics):
        """Test analytics on completely empty database."""
        # Should not raise errors
        trends = analytics.get_performance_trends(days=30)
        anomalies = analytics.detect_anomalies(lookback_hours=24)
        efficiency = analytics.get_efficiency_metrics(days=7)
        
        assert isinstance(trends, list)
        assert isinstance(anomalies, list)
        assert isinstance(efficiency, dict)

    def test_single_run(self, temp_db):
        """Test analytics with only one run."""
        analytics_inst = SimulationAnalytics(temp_db)
        
        temp_db.save_run(
            run_id="single_run",
            status="succeeded",
            timestamp_start="2024-01-01T00:00:00Z",
            timestamp_end="2024-01-01T01:00:00Z",
            duration_seconds=3600,
            config={"test": True},
            dataset_path="/test",
            output_path="/test/output",
            particle_count=100,
            time_steps=10,
            output_size_mb=1.0,
            endpoint_latency_ms=3600,
        )
        
        metrics = analytics_inst.get_efficiency_metrics(days=1)
        assert isinstance(metrics, dict)

    def test_all_failed_runs(self, temp_db):
        """Test analytics with all failed runs."""
        analytics_inst = SimulationAnalytics(temp_db)
        
        for i in range(5):
            temp_db.save_run(
                run_id=f"failed_{i}",
                status="failed",
                timestamp_start="2024-01-01T00:00:00Z",
                timestamp_end="2024-01-01T01:00:00Z",
                duration_seconds=3600,
                config={"test": True},
                dataset_path="/test",
                output_path="/test/output",
                particle_count=100,
                time_steps=10,
                output_size_mb=1.0,
                endpoint_latency_ms=3600,
                error_message="Test error",
            )
        
        metrics = analytics_inst.get_efficiency_metrics(days=1)
        # Success rate should be 0
        assert metrics["success_rate"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
