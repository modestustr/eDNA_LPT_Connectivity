"""
API Client Layer
================
Client wrapper for app.py to call the Simulation Service.
Can interface with local service or HTTP API.

This is the unified interface that app.py uses - all execution requests go through here.
"""

from typing import Optional, List, Dict, Any, Callable, Tuple
from pathlib import Path
import pandas as pd
import requests
import json

from src.core.simulation_contracts import RunResult, RunStatus
from .service import SimulationService


class SimulationAPIClient:
    """
    Unified client for simulation execution.
    - Local mode: Direct function calls to SimulationService (default)
    - HTTP mode: Posts to remote FastAPI server (when available)
    """

    def __init__(self, service: Optional[SimulationService] = None, http_base_url: Optional[str] = None):
        """
        Args:
            service: SimulationService instance (local mode).
            http_base_url: Optional HTTP server base URL (e.g., "http://localhost:8000")
                          If provided and accessible, HTTP mode takes priority.
        """
        self.service = service
        self.http_base_url = http_base_url
        self.mode = self._detect_mode()

    def _detect_mode(self) -> str:
        """Detect whether to use local or HTTP mode."""
        if self.http_base_url:
            try:
                resp = requests.get(f"{self.http_base_url}/health", timeout=2)
                if resp.status_code == 200:
                    return "http"
            except Exception:
                pass
        
        return "local" if self.service else "http"

    # ============================================================================
    # PUBLIC INTERFACE: What app.py calls
    # ============================================================================

    def validate_single_run(
        self,
        dataset_path: str,
        config: Dict[str, Any],
    ) -> Tuple[bool, List[str]]:
        """
        Validate a single run before execution.

        Returns:
            (is_valid: bool, issues: List[str])
        """
        if self.mode == "local":
            return self.service.preflight_single_run(dataset_path, config)
        else:
            return self._http_validate_single(dataset_path, config)

    def validate_batch_runs(
        self,
        dataset_path: str,
        batch_configs: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Validate multiple runs.

        Returns:
            (valid_configs, invalid_configs)
        """
        if self.mode == "local":
            return self.service.preflight_batch_run(dataset_path, batch_configs)
        else:
            return self._http_validate_batch(dataset_path, batch_configs)

    def run_single(
        self,
        dataset_path: str,
        output_path: str,
        config: Dict[str, Any],
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> RunResult:
        """
        Execute a single simulation.

        Args:
            dataset_path: Path to prepared dataset
            output_path: Where to save output
            config: Simulation config dict
            progress_callback: Optional callback(percent, message)

        Returns:
            RunResult
        """
        if self.mode == "local":
            return self.service.execute_single_run(
                dataset_path,
                output_path,
                config,
                progress_callback,
            )
        else:
            return self._http_run_single(dataset_path, output_path, config, progress_callback)

    def run_batch(
        self,
        dataset_path: str,
        output_base_path: str,
        batch_configs: List[Dict[str, Any]],
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Execute multiple simulations.

        Args:
            dataset_path: Path to prepared dataset
            output_base_path: Base output directory
            batch_configs: List of per-run configs
            progress_callback: Optional callback(percent, message)

        Returns:
            {
                "summary": [...],
                "results": [...],
                "success_count": int,
                "total_count": int,
            }
        """
        if self.mode == "local":
            return self.service.execute_batch_runs(
                dataset_path,
                output_base_path,
                batch_configs,
                progress_callback,
            )
        else:
            return self._http_run_batch(dataset_path, output_base_path, batch_configs, progress_callback)

    # ============================================================================
    # INTERNAL: HTTP method implementations
    # ============================================================================

    def _http_validate_single(self, dataset_path: str, config: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """HTTP: Validate single run."""
        try:
            resp = requests.post(
                f"{self.http_base_url}/validate/single",
                json={"dataset_path": dataset_path, "config": config},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("valid", False), data.get("issues", [])
        except Exception as e:
            return False, [f"HTTP validation failed: {str(e)}"]

    def _http_validate_batch(
        self,
        dataset_path: str,
        batch_configs: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """HTTP: Validate batch runs."""
        try:
            resp = requests.post(
                f"{self.http_base_url}/validate/batch",
                json={"dataset_path": dataset_path, "batch_configs": batch_configs},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("valid_configs", []), data.get("invalid_configs", [])
        except Exception as e:
            return [], [{"error": f"HTTP batch validation failed: {str(e)}", "config": None}]

    def _http_run_single(
        self,
        dataset_path: str,
        output_path: str,
        config: Dict[str, Any],
        progress_callback: Optional[Callable[[int, str], None]],
    ) -> RunResult:
        """HTTP: Execute single run."""
        try:
            # Use streaming endpoint if progress callback provided
            if progress_callback:
                return self._http_run_single_streaming(dataset_path, output_path, config, progress_callback)
            
            # Standard execution
            resp = requests.post(
                f"{self.http_base_url}/run/single",
                json={"dataset_path": dataset_path, "output_path": output_path, "config": config},
                timeout=3600,  # 1 hour timeout
            )
            resp.raise_for_status()
            data = resp.json()
            
            return RunResult(
                status=data.get("status", "FAILED"),
                output_path=data.get("output_path"),
                error_message=data.get("error_message"),
                started_at_utc=data.get("started_at_utc"),
                ended_at_utc=data.get("ended_at_utc"),
                elapsed_seconds=data.get("elapsed_seconds", 0),
                artifacts=data.get("artifacts"),
            )
        except Exception as e:
            return RunResult(
                status=RunStatus.FAILED,
                output_path=output_path,
                error_message=f"HTTP execution failed: {str(e)}",
                started_at_utc=pd.Timestamp.now().isoformat(),
                ended_at_utc=pd.Timestamp.now().isoformat(),
                elapsed_seconds=0,
            )

    def _http_run_single_streaming(
        self,
        dataset_path: str,
        output_path: str,
        config: Dict[str, Any],
        progress_callback: Callable[[int, str], None],
    ) -> RunResult:
        """HTTP: Execute single run with progress streaming (SSE)."""
        try:
            resp = requests.post(
                f"{self.http_base_url}/run/single/stream",
                json={"dataset_path": dataset_path, "output_path": output_path, "config": config},
                timeout=3600,
                stream=True,
            )
            resp.raise_for_status()
            
            # Process SSE stream
            result = None
            for line in resp.iter_lines():
                if line and line.startswith(b"data: "):
                    try:
                        event = json.loads(line[6:].decode())
                        event_type = event.get("type")
                        
                        if event_type == "progress":
                            progress_callback(event.get("percent", 0), event.get("message", ""))
                        elif event_type == "result":
                            result_data = event.get("data", {})
                            result = RunResult(
                                status=result_data.get("status", "FAILED"),
                                output_path=result_data.get("output_path"),
                                error_message=result_data.get("error_message"),
                                started_at_utc=result_data.get("started_at_utc"),
                                ended_at_utc=result_data.get("ended_at_utc"),
                                elapsed_seconds=result_data.get("elapsed_seconds", 0),
                            )
                        elif event_type == "error":
                            raise Exception(event.get("error", "Unknown streaming error"))
                    except json.JSONDecodeError:
                        pass
            
            return result or RunResult(
                status=RunStatus.FAILED,
                output_path=output_path,
                error_message="No result received from stream",
                started_at_utc=pd.Timestamp.now().isoformat(),
                ended_at_utc=pd.Timestamp.now().isoformat(),
                elapsed_seconds=0,
            )
        except Exception as e:
            return RunResult(
                status=RunStatus.FAILED,
                output_path=output_path,
                error_message=f"HTTP streaming execution failed: {str(e)}",
                started_at_utc=pd.Timestamp.now().isoformat(),
                ended_at_utc=pd.Timestamp.now().isoformat(),
                elapsed_seconds=0,
            )

    def _http_run_batch(
        self,
        dataset_path: str,
        output_base_path: str,
        batch_configs: List[Dict[str, Any]],
        progress_callback: Optional[Callable[[int, str], None]],
    ) -> Dict[str, Any]:
        """HTTP: Execute batch runs."""
        try:
            resp = requests.post(
                f"{self.http_base_url}/run/batch",
                json={
                    "dataset_path": dataset_path,
                    "output_base_path": output_base_path,
                    "batch_configs": batch_configs,
                },
                timeout=7200,  # 2 hour timeout
            )
            resp.raise_for_status()
            data = resp.json()
            
            return {
                "summary": data.get("summary", []),
                "results": data.get("results", []),
                "success_count": data.get("success_count", 0),
                "total_count": data.get("total_count", 0),
                "valid_count": data.get("valid_count", 0),
                "invalid_count": data.get("invalid_count", 0),
            }
        except Exception as e:
            return {
                "summary": [],
                "results": [],
                "success_count": 0,
                "total_count": 0,
                "valid_count": 0,
                "invalid_count": -1,
                "error": f"HTTP batch execution failed: {str(e)}",
            }

