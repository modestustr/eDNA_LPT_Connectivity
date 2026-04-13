"""Runtime cost estimation and memory risk assessment helpers."""


def estimate_particle_count(mode, particle_count_override):
    """Resolve the effective particle count for cost estimation and UI display.

    If particle_count_override > 0 the user-supplied value is used directly.
    Otherwise the mode-specific default is returned:
        uniform  –  10   (debug grid, deterministic)
        random   – 200   (stochastic, UI-responsive sweet spot)
        hybrid   – 300   (100 global + 200 hotspot)
        valid    – 200   (resampled from hydrodynamic grid nodes)
    """
    if int(particle_count_override) > 0:
        return int(particle_count_override)
    defaults = {
        "uniform": 10,
        "random": 200,
        "hybrid": 300,
        "valid": 200,
    }
    return defaults.get(str(mode), 200)


def estimate_memory_risk_tier(estimated_days, estimated_particles, output_hours, sample_velocity, release_mode, repeat_release_hours):
    """Return an approximate memory risk tier for trajectory-heavy runs.

    Heuristic model:
    - More saved frames (short output interval) and more particles increase memory.
    - Repeated release multiplies particle instances over run duration.
    - Velocity sampling (u, v, speed) increases per-point payload.
    """
    frames = max(1, int((int(estimated_days) * 24) / max(1, int(output_hours))))
    release_factor = 1
    if str(release_mode) == "repeated":
        release_factor = max(1, int((int(estimated_days) * 24) / max(1, int(repeat_release_hours))))

    effective_particle_instances = int(estimated_particles) * int(release_factor)
    bytes_per_point = 88 if bool(sample_velocity) else 56
    estimated_mb = (effective_particle_instances * frames * bytes_per_point) / (1024.0 * 1024.0)

    if estimated_mb < 128:
        tier = "low"
        guidance = "Low memory pressure expected on most laptops/workstations."
    elif estimated_mb < 512:
        tier = "medium"
        guidance = "Moderate memory pressure possible; prefer fewer particles or coarser output interval if instability appears."
    else:
        tier = "high"
        guidance = "High memory pressure risk; reduce particles, shorten duration, or increase output interval before long runs."

    return {
        "tier": tier,
        "estimated_mb": float(estimated_mb),
        "frames": int(frames),
        "release_factor": int(release_factor),
        "effective_particle_instances": int(effective_particle_instances),
        "guidance": guidance,
    }


def estimate_visualization_memory_risk(trajectory_count, step, has_sampled_speed):
    """Estimate in-memory footprint of the selected visualization frame load.

    This models the materialization pattern in get_zarr_step_data where
    trajectory arrays are loaded up to the selected step.
    """
    n_traj = max(0, int(trajectory_count))
    n_frame = max(1, int(step) + 1)

    base_elements = (n_traj * n_frame * 2) + (n_traj * 2)
    speed_elements = (n_traj * n_frame) + n_traj if bool(has_sampled_speed) else 0
    total_elements = base_elements + speed_elements

    estimated_mb = (total_elements * 8.0) / (1024.0 * 1024.0)
    if estimated_mb < 128:
        tier = "low"
    elif estimated_mb < 512:
        tier = "medium"
    else:
        tier = "high"

    return {
        "tier": tier,
        "estimated_mb": float(estimated_mb),
        "trajectory_count": n_traj,
        "frames": n_frame,
        "has_sampled_speed": bool(has_sampled_speed),
    }


def build_memory_materialization_inventory():
    """Return a concise inventory of major array materialization points.

    Used for Industrial Week-1 memory audit visibility in the UI.
    """
    return [
        {
            "Component": "Grid adapter reshape",
            "Location": "adapt_dataset_flattened_grid_1d",
            "Pattern": "values + reshape",
            "Risk": "caution",
            "Notes": "Loads node-aligned velocity arrays to build adapted regular grid.",
        },
        {
            "Component": "Frame render data",
            "Location": "get_zarr_step_data",
            "Pattern": "load().values slices",
            "Risk": "high",
            "Notes": "Materializes lon/lat trajectories up to selected step; speed arrays add overhead.",
        },
        {
            "Component": "QC summary",
            "Location": "get_zarr_qc_summary",
            "Pattern": "load().values at key steps",
            "Risk": "caution",
            "Notes": "Loads step 0/current/final lon-lat vectors for aggregate metrics.",
        },
        {
            "Component": "Station analytics",
            "Location": "get_station_analytics",
            "Pattern": "load().values slices",
            "Risk": "caution",
            "Notes": "Loads trajectory slices for proximity and connectivity analysis.",
        },
    ]
