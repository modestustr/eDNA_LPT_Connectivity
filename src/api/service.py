"""
Simulation Service Layer
========================
Core API service for simulation execution, preflight validation, and result tracking.
This service encapsulates all simulation orchestration logic independent of UI.

Can be wrapped by FastAPI endpoints or called directly by app.py as local client.
"""

from typing import Optional, List, Dict, Any, Callable, Tuple
import traceback
import pandas as pd
import xarray as xr
from pathlib import Path

from src.core.simulation_contracts import RunStatus, SimRunConfig, RunResult
from src.ui.ui_validation import validate_run_semantics


class SimulationServiceError(Exception):
    """Base exception for simulation service errors."""
    pass


class CallbackProgressBar:
    """Adapter that converts a callback function to Streamlit progress bar interface.
    
    Converts callback(percent, message) → progress_bar.progress(percent, text=message)
    """
    def __init__(self, callback: Optional[Callable[[int, str], None]] = None):
        self.callback = callback
    
    def progress(self, percent: float, text: str = ""):
        """Convert to callback interface."""
        if self.callback:
            # Convert 0-1 to 0-100 for callback percentage
            callback_percent = int(percent * 100)
            self.callback(callback_percent, text)


class SimulationService:
    """
    Core simulation orchestration service.
    Handles single runs, batch execution, preflight validation.
    """

    def __init__(self, simulation_runner: Callable):
        """
        Args:
            simulation_runner: Callable that executes actual simulation.
                               Signature: (cfg: SimRunConfig, progress_callback) -> RunResult
        """
        self.simulation_runner = simulation_runner

    def preflight_single_run(
        self,
        dataset_path: str,
        config: Dict[str, Any],
    ) -> Tuple[bool, List[str]]:
        """
        Validate a single run configuration before execution.

        Returns:
            (is_valid: bool, issues: List[str])
        """
        try:
            ds = xr.open_dataset(dataset_path)
            try:
                issues = validate_run_semantics(ds, config)
                return len(issues) == 0, issues
            finally:
                ds.close()
        except Exception as e:
            return False, [f"Dataset validation failed: {str(e)}"]

    def preflight_batch_run(
        self,
        dataset_path: str,
        batch_configs: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Validate multiple run configurations.

        Returns:
            (valid_configs: List, invalid_configs: List)
                where each invalid config has {'error': str, 'config': dict}
        """
        valid_configs = []
        invalid_configs = []

        for i, cfg in enumerate(batch_configs):
            is_valid, issues = self.preflight_single_run(dataset_path, cfg)
            if is_valid:
                valid_configs.append(cfg)
            else:
                invalid_configs.append({
                    "index": i,
                    "config": cfg,
                    "error": " | ".join(issues),
                })

        return valid_configs, invalid_configs

    def execute_single_run(
        self,
        dataset_path: str,
        output_path: str,
        config: Dict[str, Any],
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> RunResult:
        """
        Execute a single simulation run.

        Args:
            dataset_path: Path to prepared NetCDF/Zarr dataset
            output_path: Where to save simulation output
            config: Simulation parameters
            progress_callback: Optional callback(percent, message)

        Returns:
            RunResult with status, timing, artifacts, errors
        """
        try:
            if progress_callback:
                progress_callback(0, "Preparing simulation...")

            sim_config = SimRunConfig.from_mapping(dataset_path, output_path, config)

            if progress_callback:
                progress_callback(10, "Starting execution...")

            # Wrap callback in progress bar interface for core_lpt
            progress_bar = CallbackProgressBar(progress_callback)
            
            result = self.simulation_runner(
                sim_config,
                progress_bar=progress_bar,
            )

            return result

        except Exception as e:
            error_msg = f"Single run execution failed: {str(e)}\n{traceback.format_exc()}"
            return RunResult(
                status=RunStatus.FAILED,
                output_path=output_path,
                error_message=error_msg,
                started_at_utc=pd.Timestamp.now().isoformat(),
                ended_at_utc=pd.Timestamp.now().isoformat(),
                elapsed_seconds=0.0,
            )

    def execute_batch_runs(
        self,
        dataset_path: str,
        output_base_path: str,
        batch_configs: List[Dict[str, Any]],
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Execute multiple simulation runs sequentially (or could be parallel in future).

        Args:
            dataset_path: Path to prepared dataset
            output_base_path: Base directory for all outputs
            batch_configs: List of run configurations
            progress_callback: Optional callback(percent, message)

        Returns:
            {
                "summary": [...],
                "results": [...],
                "success_count": int,
                "total_count": int,
            }
        """
        # Preflight all configs first
        valid_configs, invalid_configs = self.preflight_batch_run(dataset_path, batch_configs)

        summary = []
        results = []
        success_count = 0

        # Add preflight failures to summary
        for invalid in invalid_configs:
            summary.append({
                "run_index": invalid["index"],
                "name": invalid["config"].get("name", f"Run {invalid['index']}"),
                "status": "preflight_failed",
                "reason": invalid["error"],
            })

        # Execute valid configs
        for run_idx, cfg in enumerate(valid_configs, start=1):
            if progress_callback:
                percent = int((run_idx / max(1, len(valid_configs))) * 100)
                progress_callback(percent, f"Running {run_idx}/{len(valid_configs)}...")

            run_name = cfg.get("name", f"Run {run_idx}")
            run_output_path = str(Path(output_base_path) / f"run_{run_idx:03d}")

            result = self.execute_single_run(
                dataset_path,
                run_output_path,
                cfg,
                progress_callback=None,  # Sub-callback per run
            )

            results.append(result)

            if result.status == RunStatus.SUCCEEDED:
                success_count += 1
                summary.append({
                    "run_index": run_idx,
                    "name": run_name,
                    "status": "success",
                    "output_path": result.output_path,
                    "elapsed": result.elapsed_seconds,
                })
            else:
                summary.append({
                    "run_index": run_idx,
                    "name": run_name,
                    "status": "failed",
                    "error": result.error_message,
                })

        return {
            "summary": summary,
            "results": results,
            "success_count": success_count,
            "total_count": len(batch_configs),
            "valid_count": len(valid_configs),
            "invalid_count": len(invalid_configs),
        }
