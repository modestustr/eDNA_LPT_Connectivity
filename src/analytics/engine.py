"""
Analytics Module
=================
Advanced analytics and performance insights for simulation runs.

Features:
- Performance trend detection
- Anomaly detection (slow runs, failures)
- Comparison analysis (A/B testing insights)
- Efficiency metrics (particles/second, success rate trends)
- Resource utilization analysis
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import statistics
from dataclasses import dataclass


@dataclass
class PerformanceTrend:
    """Performance trend insight."""
    metric: str  # "duration", "success_rate", "particles_per_sec"
    trend: str  # "improving", "degrading", "stable"
    change_percent: float
    period_start: str
    period_end: str
    details: str


@dataclass
class Anomaly:
    """Detected anomaly in run data."""
    type: str  # "slow_run", "failure_spike", "memory_spike"
    severity: str  # "low", "medium", "high"
    run_id: Optional[str]
    timestamp: str
    description: str
    context: Dict[str, Any]


class SimulationAnalytics:
    """
    Analytics engine for simulation performance analysis.
    """

    def __init__(self, run_history_db):
        """
        Initialize analytics engine.
        
        Args:
            run_history_db: RunHistoryDB instance for data access
        """
        self.db = run_history_db

    def get_performance_trends(self, days: int = 30) -> List[PerformanceTrend]:
        """
        Analyze performance trends over a period.
        
        Args:
            days: Period to analyze
            
        Returns:
            List of detected trends
        """
        trends = []
        
        # Get first and second half of period
        end_date = datetime.utcnow()
        mid_date = end_date - timedelta(days=days // 2)
        start_date = end_date - timedelta(days=days)
        
        first_half_stats = self.db.get_stats(days=days // 2)
        second_half_stats = self.db.get_stats(days=days - (days // 2))
        
        # Duration trend
        first_avg_duration = first_half_stats["duration"].get("avg_seconds", 0) or 0
        second_avg_duration = second_half_stats["duration"].get("avg_seconds", 0) or 0
        
        if first_avg_duration > 0:
            duration_change = (second_avg_duration - first_avg_duration) / first_avg_duration * 100
            duration_trend = "degrading" if duration_change > 5 else ("improving" if duration_change < -5 else "stable")
            
            trends.append(PerformanceTrend(
                metric="duration",
                trend=duration_trend,
                change_percent=duration_change,
                period_start=start_date.isoformat() + "Z",
                period_end=end_date.isoformat() + "Z",
                details=f"Average duration changed from {first_avg_duration:.1f}s to {second_avg_duration:.1f}s"
            ))
        
        # Success rate trend
        first_success = first_half_stats.get("success_rate", 0)
        second_success = second_half_stats.get("success_rate", 0)
        
        if first_success > 0:
            success_change = (second_success - first_success) * 100
            success_trend = "improving" if success_change > 2 else ("degrading" if success_change < -2 else "stable")
            
            trends.append(PerformanceTrend(
                metric="success_rate",
                trend=success_trend,
                change_percent=success_change,
                period_start=start_date.isoformat() + "Z",
                period_end=end_date.isoformat() + "Z",
                details=f"Success rate changed from {first_success*100:.1f}% to {second_success*100:.1f}%"
            ))
        
        return trends

    def detect_anomalies(self, lookback_hours: int = 24, sensitivity: str = "medium") -> List[Anomaly]:
        """
        Detect anomalies in recent runs.
        
        Args:
            lookback_hours: Hours to analyze
            sensitivity: Detection sensitivity ("low", "medium", "high")
            
        Returns:
            List of detected anomalies
        """
        anomalies = []
        
        # Get recent runs
        recent_runs = self.db.get_runs(limit=1000)
        if not recent_runs:
            return anomalies
        
        # Filter to timeframe (use naive datetime for comparison)
        cutoff_time = datetime.utcnow() - timedelta(hours=lookback_hours)
        
        recent_runs = [
            r for r in recent_runs
            if r.get("timestamp_start") and 
            datetime.fromisoformat(r["timestamp_start"].replace("Z", "+00:00")).replace(tzinfo=None) > cutoff_time
        ]
        
        if len(recent_runs) < 3:
            return anomalies
        
        # Calculate baseline metrics
        durations = [r.get("duration_seconds", 0) for r in recent_runs if r.get("duration_seconds")]
        success_runs = [r for r in recent_runs if r.get("status") == "succeeded"]
        failed_runs = [r for r in recent_runs if r.get("status") == "failed"]
        
        if durations:
            # Detect slow runs
            avg_duration = statistics.mean(durations)
            stdev_duration = statistics.stdev(durations) if len(durations) > 1 else 0
            
            threshold_multipliers = {
                "low": 3.0,
                "medium": 2.0,
                "high": 1.5
            }
            threshold = avg_duration + (stdev_duration * threshold_multipliers.get(sensitivity, 2.0))
            
            for run in recent_runs:
                if run.get("duration_seconds", 0) > threshold:
                    anomalies.append(Anomaly(
                        type="slow_run",
                        severity="high" if run.get("duration_seconds", 0) > avg_duration * 3 else "medium",
                        run_id=run.get("run_id"),
                        timestamp=run.get("timestamp_start", ""),
                        description=f"Run took {run.get('duration_seconds', 0):.1f}s (avg: {avg_duration:.1f}s)",
                        context={"duration": run.get("duration_seconds"), "avg": avg_duration}
                    ))
        
        # Detect failure spikes
        if len(recent_runs) >= 10:
            failure_rate = len(failed_runs) / len(recent_runs)
            if failure_rate > 0.3:  # >30% failure rate
                anomalies.append(Anomaly(
                    type="failure_spike",
                    severity="high",
                    run_id=None,
                    timestamp=datetime.utcnow().isoformat() + "Z",
                    description=f"High failure rate: {failure_rate*100:.1f}% ({len(failed_runs)}/{len(recent_runs)})",
                    context={"failure_rate": failure_rate, "failed_count": len(failed_runs)}
                ))
        
        return anomalies

    def get_efficiency_metrics(self, days: int = 7) -> Dict[str, Any]:
        """
        Calculate efficiency metrics.
        
        Args:
            days: Period to analyze
            
        Returns:
            Dictionary with efficiency metrics
        """
        stats = self.db.get_stats(days=days)
        
        metrics = {
            "success_rate": stats.get("success_rate", 0),
            "avg_duration_seconds": stats["duration"].get("avg_seconds", 0),
            "total_particles_executed": stats["particles"].get("total_executed", 0),
            "avg_particles_per_run": stats["particles"].get("avg_per_run", 0),
            "total_runs": stats.get("total_runs", 0),
        }
        
        # Calculate particles per second (throughput)
        avg_duration = stats["duration"].get("avg_seconds") or 1
        total_duration = stats.get("total_runs", 0) * avg_duration
        if total_duration > 0:
            metrics["particles_per_second"] = stats["particles"].get("total_executed", 0) / total_duration
        else:
            metrics["particles_per_second"] = 0
        
        # Efficiency score (0-100)
        # Based on success rate, speed, and throughput
        efficiency_score = (
            stats.get("success_rate", 0) * 50 +  # 50% from success
            min(50, (1 / max(1, avg_duration)) * 10)  # Speed factor
        )
        metrics["efficiency_score"] = round(min(100, efficiency_score), 1)
        
        return metrics

    def compare_runs(self, run_ids: List[str]) -> Dict[str, Any]:
        """
        Compare multiple runs side-by-side.
        
        Args:
            run_ids: List of run IDs to compare
            
        Returns:
            Comparison data
        """
        runs = []
        for run_id in run_ids:
            run = self.db.get_run(run_id)
            if run:
                runs.append(run)
        
        if not runs:
            return {"error": "No runs found"}
        
        comparison = {
            "runs_compared": len(runs),
            "detail_by_run": [],
            "summary": {
                "avg_duration": 0,
                "fastest": None,
                "slowest": None,
                "success_count": sum(1 for r in runs if r.get("status") == "succeeded"),
                "failure_count": sum(1 for r in runs if r.get("status") == "failed"),
            }
        }
        
        durations = []
        for run in runs:
            duration = run.get("duration_seconds", 0)
            durations.append(duration)
            
            comparison["detail_by_run"].append({
                "run_id": run.get("run_id"),
                "status": run.get("status"),
                "duration_seconds": duration,
                "particle_count": run.get("particle_count"),
                "particles_per_sec": run.get("particle_count", 0) / max(1, duration),
                "output_size_mb": run.get("output_size_mb"),
            })
        
        if durations:
            comparison["summary"]["avg_duration"] = statistics.mean(durations)
            comparison["summary"]["fastest"] = min(durations)
            comparison["summary"]["slowest"] = max(durations)
        
        return comparison

    def get_resource_profile(self, run_id: str) -> Dict[str, Any]:
        """
        Get resource utilization profile for a run.
        
        Args:
            run_id: Run ID to profile
            
        Returns:
            Resource profile data
        """
        run = self.db.get_run(run_id)
        if not run:
            return {"error": "Run not found"}
        
        duration = run.get("duration_seconds", 1)
        particle_count = run.get("particle_count", 0)
        
        profile = {
            "run_id": run_id,
            "duration_seconds": duration,
            "particle_count": particle_count,
            "time_steps": run.get("time_steps"),
            "output_size_mb": run.get("output_size_mb", 0),
            "throughput_metrics": {
                "particles_per_second": particle_count / max(1, duration),
                "time_steps_per_second": (run.get("time_steps", 0) or 0) / max(1, duration),
                "output_mb_per_second": (run.get("output_size_mb", 0) or 0) / max(1, duration),
            },
            "efficiency_estimate": {
                "particles_per_mb": particle_count / max(1, run.get("output_size_mb", 1)),
                "time_steps_per_mb": (run.get("time_steps", 0) or 0) / max(1, run.get("output_size_mb", 1)),
                "speed_rating": "fast" if duration < 300 else ("medium" if duration < 1200 else "slow"),
            }
        }
        
        return profile

    def get_worst_performing_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get runs with poorest performance."""
        runs = self.db.get_runs(limit=1000)
        
        # Score each run (lower is worse)
        scored_runs = []
        for run in runs:
            score = _calculate_run_score(run)
            scored_runs.append((score, run))
        
        # Sort by score (ascending = worst first)
        scored_runs.sort(key=lambda x: x[0])
        
        return [run for _, run in scored_runs[:limit]]

    def get_best_performing_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get runs with best performance."""
        runs = self.db.get_runs(limit=1000)
        
        # Score each run (higher is better)
        scored_runs = []
        for run in runs:
            score = _calculate_run_score(run)
            scored_runs.append((score, run))
        
        # Sort by score (descending = best first)
        scored_runs.sort(key=lambda x: x[0], reverse=True)
        
        return [run for _, run in scored_runs[:limit]]


def _calculate_run_score(run: Dict[str, Any]) -> float:
    """
    Calculate performance score for a run.
    
    Factors:
    - Success (0 if failed, 1 if succeeded)
    - Speed (faster is better, normalized)
    - Efficiency (particles per second)
    """
    score = 0
    
    # Success factor (40%)
    if run.get("status") == "succeeded":
        score += 40
    
    # Speed factor (30%)
    # Assume 300s is "normal", faster is better
    duration = run.get("duration_seconds", 300)
    speed_score = min(30, (300 / max(1, duration)) * 10)
    score += speed_score
    
    # Efficiency factor (30%)
    # Particles per second
    particles = run.get("particle_count", 0)
    efficiency = particles / max(1, duration)
    # Assume 1 particle/sec is baseline
    efficiency_score = min(30, efficiency * 10)
    score += efficiency_score
    
    return score


if __name__ == "__main__":
    from .history import get_run_history_db
    
    # Example usage
    db = get_run_history_db()
    analytics = SimulationAnalytics(db)
    
    # Get trends
    trends = analytics.get_performance_trends(days=30)
    print(f"Trends: {len(trends)} detected")
    
    # Detect anomalies
    anomalies = analytics.detect_anomalies(lookback_hours=24)
    print(f"Anomalies: {len(anomalies)} detected")
    
    # Get efficiency metrics
    efficiency = analytics.get_efficiency_metrics(days=7)
    print(f"Efficiency Score: {efficiency.get('efficiency_score', 0)}")
