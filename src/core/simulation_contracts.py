from dataclasses import dataclass
from typing import Any, Dict, List, Optional


DEFAULT_OUTPUT_HOURS = 1
DEFAULT_DT_MINUTES = 10


@dataclass
class SimRunConfig:
    """Canonical simulation contract for UI/API callers."""

    file_path: str
    output_path: str
    days: int = 2
    mode: str = "uniform"
    u_var: str = "uo"
    v_var: str = "vo"
    lon_coord: str = "longitude"
    lat_coord: str = "latitude"
    time_coord: str = "time"
    depth_coord: str = ""
    particle_count: Optional[int] = None
    seed: Optional[int] = None
    backend: str = "scipy"
    dt_minutes: int = DEFAULT_DT_MINUTES
    output_hours: int = DEFAULT_OUTPUT_HOURS
    repeat_release_hours: Optional[int] = None
    sample_velocity: bool = True

    @classmethod
    def from_mapping(cls, file_path: str, output_path: str, values: Dict[str, Any]) -> "SimRunConfig":
        """Build a normalized SimRunConfig from a generic mapping."""
        payload = dict(values or {})
        release_mode = str(payload.get("release_mode", "instant"))
        particle_count = payload.get("particle_count", None)
        seed = payload.get("seed", None)
        repeat_release_hours = payload.get("repeat_release_hours", None)

        normalized_particle_count = None
        if particle_count is not None and int(particle_count) > 0:
            normalized_particle_count = int(particle_count)

        normalized_seed = None
        if seed is not None and int(seed) > 0:
            normalized_seed = int(seed)

        normalized_repeat_hours = None
        if release_mode == "repeated" and repeat_release_hours is not None:
            normalized_repeat_hours = int(repeat_release_hours)

        return cls(
            file_path=str(file_path),
            output_path=str(output_path),
            days=int(payload.get("days", 2)),
            mode=str(payload.get("mode", "uniform")),
            u_var=str(payload.get("u_var", "uo")),
            v_var=str(payload.get("v_var", "vo")),
            lon_coord=str(payload.get("lon_coord", "longitude")),
            lat_coord=str(payload.get("lat_coord", "latitude")),
            time_coord=str(payload.get("time_coord", "time")),
            depth_coord=str(payload.get("depth_coord", "")),
            particle_count=normalized_particle_count,
            seed=normalized_seed,
            backend=str(payload.get("backend", "scipy")),
            dt_minutes=int(payload.get("dt_minutes", DEFAULT_DT_MINUTES)),
            output_hours=int(payload.get("output_hours", DEFAULT_OUTPUT_HOURS)),
            repeat_release_hours=normalized_repeat_hours,
            sample_velocity=bool(payload.get("sample_velocity", True)),
        )


class RunStatus:
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass
class RunResult:
    """Canonical run result contract for UI/API callers."""

    status: str
    output_path: str
    started_at_utc: str
    ended_at_utc: str
    elapsed_seconds: float
    error_message: str = ""
    metadata: Optional[Dict[str, Any]] = None
    artifacts: Optional[List[Dict[str, str]]] = None