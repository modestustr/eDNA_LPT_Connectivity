"""
Run History Database Module
============================
Persistent storage of simulation run history in SQLite.

Features:
- Automatic database creation and schema
- Store run metadata, configuration, and results
- Query and filter runs by various criteria
- Compute aggregated statistics
- Export run history as JSON/CSV
"""

import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import json
from dataclasses import asdict
from contextlib import contextmanager

from src.core.simulation_contracts import RunStatus


class RunHistoryDB:
    """
    SQLite database for persistent run history storage.
    
    Schema:
    - runs: Core run metadata (id, status, timing, config hash)
    - run_details: Run details (particle_count, time_steps, output_size)
    - run_config: Serialized configuration JSON
    - run_errors: Error logging for failed runs
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize run history database.
        
        Args:
            db_path: Path to SQLite database file.
                    If None, uses "runs_history.db" in current directory.
        """
        self.db_path = Path(db_path or "runs_history.db")
        self._ensure_schema()

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row  # Return rows as dicts
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self):
        """Create database schema if it doesn't exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Core runs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    timestamp_start TEXT NOT NULL,
                    timestamp_end TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Run details (metrics)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS run_details (
                    run_id TEXT PRIMARY KEY,
                    particle_count INTEGER,
                    time_steps INTEGER,
                    output_size_mb REAL,
                    endpoint_latency_ms REAL,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                )
            """)
            
            # Run configuration (JSON)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS run_config (
                    run_id TEXT PRIMARY KEY,
                    config_json TEXT NOT NULL,
                    dataset_path TEXT,
                    output_path TEXT,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                )
            """)
            
            # Error logs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS run_errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    error_type TEXT,
                    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                )
            """)
            
            # Create indices for common queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_runs_timestamp ON runs(timestamp_start DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_run_details_particle_count ON run_details(particle_count)")
            
            conn.commit()

    def save_run(
        self,
        run_id: str,
        status: str,
        timestamp_start: str,
        timestamp_end: str,
        duration_seconds: float,
        config: Optional[Dict[str, Any]] = None,
        dataset_path: Optional[str] = None,
        output_path: Optional[str] = None,
        particle_count: Optional[int] = None,
        time_steps: Optional[int] = None,
        output_size_mb: Optional[float] = None,
        endpoint_latency_ms: Optional[float] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Save a run to the database.
        
        Args:
            run_id: Unique run identifier
            status: "succeeded", "failed", "canceled"
            timestamp_start: ISO format start time
            timestamp_end: ISO format end time
            duration_seconds: Total execution time
            config: Configuration dictionary
            dataset_path: Path to input dataset
            output_path: Path to output
            particle_count: Number of particles
            time_steps: Number of time steps
            output_size_mb: Output size in MB
            endpoint_latency_ms: API endpoint latency
            error_message: Error message if failed
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Save core run record
            cursor.execute("""
                INSERT OR REPLACE INTO runs 
                (run_id, status, timestamp_start, timestamp_end, duration_seconds)
                VALUES (?, ?, ?, ?, ?)
            """, (run_id, status, timestamp_start, timestamp_end, duration_seconds))
            
            # Save run details
            cursor.execute("""
                INSERT OR REPLACE INTO run_details
                (run_id, particle_count, time_steps, output_size_mb, endpoint_latency_ms)
                VALUES (?, ?, ?, ?, ?)
            """, (run_id, particle_count, time_steps, output_size_mb, endpoint_latency_ms))
            
            # Save config
            if config or dataset_path or output_path:
                config_json = json.dumps(config or {})
                cursor.execute("""
                    INSERT OR REPLACE INTO run_config
                    (run_id, config_json, dataset_path, output_path)
                    VALUES (?, ?, ?, ?)
                """, (run_id, config_json, dataset_path, output_path))
            
            # Save error if present
            if error_message:
                cursor.execute("""
                    INSERT INTO run_errors
                    (run_id, error_message, error_type)
                    VALUES (?, ?, ?)
                """, (run_id, error_message, "execution_error"))
            
            conn.commit()

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get a single run by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT r.*, rd.*, rc.config_json
                FROM runs r
                LEFT JOIN run_details rd ON r.run_id = rd.run_id
                LEFT JOIN run_config rc ON r.run_id = rc.run_id
                WHERE r.run_id = ?
            """, (run_id,))
            
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_runs(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "timestamp_start DESC",
    ) -> List[Dict[str, Any]]:
        """
        Get multiple runs with optional filtering.
        
        Args:
            status: Filter by status ("succeeded", "failed", etc)
            limit: Max results
            offset: Skip N results
            order_by: Sort order (default: newest first)
            
        Returns:
            List of run records
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            query = """
                SELECT r.*, rd.*, rc.config_json
                FROM runs r
                LEFT JOIN run_details rd ON r.run_id = rd.run_id
                LEFT JOIN run_config rc ON r.run_id = rc.run_id
            """
            
            params = []
            if status:
                query += " WHERE r.status = ?"
                params.append(status)
            
            query += f" ORDER BY {order_by}"
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_stats(self, days: Optional[int] = None) -> Dict[str, Any]:
        """
        Get aggregated run statistics.
        
        Args:
            days: If specified, only include runs from last N days
            
        Returns:
            Dictionary with aggregated statistics
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            where_clause = ""
            params = []
            if days:
                where_clause = f" WHERE datetime(r.timestamp_start) > datetime('now', '-{days} days')"
            
            # Total runs by status
            cursor.execute(f"""
                SELECT status, COUNT(*) as count
                FROM runs r
                {where_clause}
                GROUP BY status
            """, params)
            
            status_counts = {}
            for row in cursor.fetchall():
                status_counts[row["status"]] = row["count"]
            
            # Duration statistics
            cursor.execute(f"""
                SELECT 
                    COUNT(*) as total,
                    AVG(duration_seconds) as avg_duration,
                    MIN(duration_seconds) as min_duration,
                    MAX(duration_seconds) as max_duration
                FROM runs r
                {where_clause}
            """, params)
            
            duration_stats = dict(cursor.fetchone() or {})
            
            # Particle statistics
            cursor.execute(f"""
                SELECT 
                    SUM(particle_count) as total_particles,
                    AVG(particle_count) as avg_particles,
                    MAX(output_size_mb) as max_output_mb
                FROM run_details rd
                JOIN runs r ON rd.run_id = r.run_id
                {where_clause}
            """, params)
            
            particle_stats = dict(cursor.fetchone() or {})
            
            total_runs = sum(status_counts.values())
            success_count = status_counts.get("succeeded", 0)
            
            return {
                "total_runs": total_runs,
                "status_breakdown": status_counts,
                "success_rate": success_count / total_runs if total_runs > 0 else 0.0,
                "duration": {
                    "avg_seconds": duration_stats.get("avg_duration", 0),
                    "min_seconds": duration_stats.get("min_duration", 0),
                    "max_seconds": duration_stats.get("max_duration", 0),
                },
                "particles": {
                    "total_executed": particle_stats.get("total_particles") or 0,
                    "avg_per_run": particle_stats.get("avg_particles", 0),
                    "max_output_mb": particle_stats.get("max_output_mb", 0),
                },
            }

    def get_timeline(self, days: int = 7, bucket_hours: int = 1) -> List[Dict[str, Any]]:
        """
        Get run timeline data (for charting).
        
        Args:
            days: Number of days to look back
            bucket_hours: Aggregate runs into N-hour buckets
            
        Returns:
            List of {timestamp, count, success_count, avg_duration}
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute(f"""
                SELECT 
                    strftime('%Y-%m-%d %H:00:00', r.timestamp_start) as bucket,
                    COUNT(*) as count,
                    SUM(CASE WHEN r.status = 'succeeded' THEN 1 ELSE 0 END) as success_count,
                    AVG(r.duration_seconds) as avg_duration
                FROM runs r
                WHERE datetime(r.timestamp_start) > datetime('now', '-{days} days')
                GROUP BY bucket
                ORDER BY bucket ASC
            """)
            
            return [dict(row) for row in cursor.fetchall()]

    def get_failure_analysis(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most common failure types."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    error_type,
                    COUNT(*) as count,
                    MAX(timestamp) as latest
                FROM run_errors
                GROUP BY error_type
                ORDER BY count DESC
                LIMIT ?
            """, (limit,))
            
            return [dict(row) for row in cursor.fetchall()]

    def export_json(self, filepath: Optional[Path] = None) -> str:
        """Export all runs as JSON."""
        runs = self.get_runs(limit=10000)  # Get all runs
        stats = self.get_stats()
        
        export_data = {
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "statistics": stats,
            "runs": runs,
        }
        
        json_str = json.dumps(export_data, indent=2, default=str)
        
        if filepath:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, "w") as f:
                f.write(json_str)
        
        return json_str

    def export_csv(self, filepath: Path) -> None:
        """Export runs as CSV."""
        import csv
        
        runs = self.get_runs(limit=10000)
        if not runs:
            return
        
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=runs[0].keys())
            writer.writeheader()
            writer.writerows(runs)

    def clear_old_runs(self, days: int = 90) -> int:
        """
        Delete runs older than N days.
        
        Args:
            days: Delete runs older than this many days
            
        Returns:
            Number of deleted runs
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Find runs to delete
            cursor.execute("""
                SELECT run_id FROM runs
                WHERE datetime(timestamp_start) < datetime('now', ? || ' days')
            """, (f"-{days}",))
            
            old_runs = [row["run_id"] for row in cursor.fetchall()]
            
            # Delete associated records
            for run_id in old_runs:
                cursor.execute("DELETE FROM run_errors WHERE run_id = ?", (run_id,))
                cursor.execute("DELETE FROM run_details WHERE run_id = ?", (run_id,))
                cursor.execute("DELETE FROM run_config WHERE run_id = ?", (run_id,))
                cursor.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            
            conn.commit()
            return len(old_runs)


# Global instance
_run_history_db: Optional[RunHistoryDB] = None


def get_run_history_db(db_path: Optional[Path] = None) -> RunHistoryDB:
    """Get or create global run history database."""
    global _run_history_db
    if _run_history_db is None:
        _run_history_db = RunHistoryDB(db_path)
    return _run_history_db


if __name__ == "__main__":
    # Example usage
    db = RunHistoryDB()
    
    # Query stats
    stats = db.get_stats()
    print(json.dumps(stats, indent=2))
    
    # Get timeline
    timeline = db.get_timeline(days=7)
    print(f"Timeline: {len(timeline)} buckets")
