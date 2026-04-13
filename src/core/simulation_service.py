import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from . import core_lpt
from .simulation_contracts import RunResult, RunStatus, SimRunConfig


def build_run_metadata(config: SimRunConfig) -> Dict[str, Any]:
    """Build lightweight metadata describing a run contract."""
    return {
        "days": int(config.days),
        "mode": str(config.mode),
        "backend": str(config.backend),
        "u_var": str(config.u_var),
        "v_var": str(config.v_var),
        "lon_coord": str(config.lon_coord),
        "lat_coord": str(config.lat_coord),
        "time_coord": str(config.time_coord),
        "depth_coord": str(config.depth_coord),
        "particle_count": (None if config.particle_count is None else int(config.particle_count)),
        "seed": (None if config.seed is None else int(config.seed)),
        "dt_minutes": int(config.dt_minutes),
        "output_hours": int(config.output_hours),
        "repeat_release_hours": (
            None if config.repeat_release_hours is None else int(config.repeat_release_hours)
        ),
        "sample_velocity": bool(config.sample_velocity),
    }


def build_run_artifacts(output_path: str) -> List[Dict[str, str]]:
    """Build a minimal artifact manifest for service-style callers."""
    if not output_path:
        return []
    return [
        {
            "kind": "trajectory_zarr",
            "label": "trajectory_store",
            "path": str(output_path),
        }
    ]


def run_simulation_from_config(config: SimRunConfig, progress_bar=None):
    """Compatibility wrapper that executes a run from SimRunConfig."""
    if not isinstance(config, SimRunConfig):
        raise TypeError("config must be an instance of SimRunConfig")

    return core_lpt.run_simulation(
        file_path=config.file_path,
        output_path=config.output_path,
        days=int(config.days),
        mode=str(config.mode),
        progress_bar=progress_bar,
        u_var=str(config.u_var),
        v_var=str(config.v_var),
        lon_coord=str(config.lon_coord),
        lat_coord=str(config.lat_coord),
        time_coord=str(config.time_coord),
        depth_coord=str(config.depth_coord),
        particle_count=(None if config.particle_count is None else int(config.particle_count)),
        seed=(None if config.seed is None else int(config.seed)),
        backend=str(config.backend),
        dt_minutes=int(config.dt_minutes),
        output_hours=int(config.output_hours),
        repeat_release_hours=(
            None if config.repeat_release_hours is None else int(config.repeat_release_hours)
        ),
        sample_velocity=bool(config.sample_velocity),
    )


def run_simulation_with_result(config: SimRunConfig, progress_bar=None) -> RunResult:
    """Execute simulation and return a structured RunResult without raising."""
    started_perf = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    run_metadata = build_run_metadata(config)
    try:
        output_path = run_simulation_from_config(config, progress_bar=progress_bar)
        ended_at = datetime.now(timezone.utc)
        return RunResult(
            status=RunStatus.SUCCEEDED,
            output_path=str(output_path),
            started_at_utc=started_at.isoformat(),
            ended_at_utc=ended_at.isoformat(),
            elapsed_seconds=float(time.perf_counter() - started_perf),
            error_message="",
            metadata=run_metadata,
            artifacts=build_run_artifacts(output_path),
        )
    except Exception as e:
        ended_at = datetime.now(timezone.utc)
        return RunResult(
            status=RunStatus.FAILED,
            output_path="",
            started_at_utc=started_at.isoformat(),
            ended_at_utc=ended_at.isoformat(),
            elapsed_seconds=float(time.perf_counter() - started_perf),
            error_message=str(e),
            metadata=run_metadata,
            artifacts=[],
        )