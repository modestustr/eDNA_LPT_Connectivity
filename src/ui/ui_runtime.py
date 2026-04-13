import numpy as np
import pandas as pd


def restore_run_history_config(session_state, config, max_days):
    """Restore saved run settings into session state."""
    for key, value in config.items():
        # Skip keys that are bound to widgets - they will cause "cannot be modified" error
        widget_keys = {
            "sim_use_full",
            "sim_seed",
            "sim_days",
            "sim_particles",
            "sim_dt_minutes",
            "sim_output_hours",
            "sim_mode",
            "sim_backend",
        }
        if key in widget_keys:
            if key == "sim_days":
                try:
                    session_state[key] = max(1, min(int(value), int(max_days)))
                except:
                    pass  # Widget already instantiated, skip
            # Skip other widget keys - they're bound to UI elements
            continue
        # Set non-widget keys normally
        try:
            session_state[key] = value
        except:
            pass  # Skip if already instantiated


def save_run_history_entry(session_state, entry, max_entries=10):
    """Prepend a run history entry and keep bounded list length."""
    history = session_state.get("run_history", [])
    history.insert(0, entry)
    session_state["run_history"] = history[: int(max_entries)]


def build_runtime_signature(days, particles, mode, backend, dt_minutes, output_hours, release_mode, repeat_release_hours, sample_velocity):
    """Build a comparable runtime signature for duration hints."""
    particle_bucket = int(max(50, (int(particles) // 50) * 50))
    return {
        "days": int(days),
        "particle_bucket": int(particle_bucket),
        "mode": str(mode),
        "backend": str(backend),
        "dt_minutes": int(dt_minutes),
        "output_hours": int(output_hours),
        "release_mode": str(release_mode),
        "repeat_release_hours": int(repeat_release_hours),
        "sample_velocity": bool(sample_velocity),
    }


def record_runtime_stat(session_state, signature, elapsed_seconds, started_at=None, ended_at=None, status="success"):
    """Append runtime observation and keep bounded history."""
    stats = session_state.get("runtime_stats", [])
    row = dict(signature)
    row.update(
        {
            "elapsed_seconds": float(elapsed_seconds),
            "started_at": str(started_at) if started_at is not None else "",
            "ended_at": str(ended_at) if ended_at is not None else "",
            "status": str(status),
            "recorded_at": str(pd.Timestamp.now()),
        }
    )
    stats.append(row)
    session_state["runtime_stats"] = stats[-200:]


def estimate_runtime_hint(session_state, signature):
    """Estimate expected runtime from prior successful similar runs."""
    stats = session_state.get("runtime_stats", [])
    if not stats:
        return None

    def _matches(row):
        return (
            row.get("status") == "success"
            and int(row.get("days", -1)) == int(signature["days"])
            and str(row.get("mode", "")) == str(signature["mode"])
            and str(row.get("backend", "")) == str(signature["backend"])
            and int(row.get("dt_minutes", -1)) == int(signature["dt_minutes"])
            and int(row.get("output_hours", -1)) == int(signature["output_hours"])
            and str(row.get("release_mode", "")) == str(signature["release_mode"])
            and int(row.get("repeat_release_hours", -1)) == int(signature["repeat_release_hours"])
            and bool(row.get("sample_velocity", False)) == bool(signature["sample_velocity"])
            and abs(int(row.get("particle_bucket", 0)) - int(signature["particle_bucket"])) <= 100
        )

    matches = [
        float(r.get("elapsed_seconds", 0.0))
        for r in stats
        if _matches(r) and float(r.get("elapsed_seconds", 0.0)) > 0
    ]
    if not matches:
        return None

    arr = np.asarray(matches, dtype=float)
    return {
        "sample_count": int(arr.size),
        "median_seconds": float(np.median(arr)),
        "p75_seconds": float(np.percentile(arr, 75)),
    }