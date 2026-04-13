"""Single run execution helpers and result processing."""

import streamlit as st


def build_single_run_config(days, particle_mode, particle_count_override, random_seed, particle_backend, dt_minutes, output_hours, release_mode, repeat_release_hours, sample_velocity, session_state, prepared_single_cfg):
    """Build single run configuration from UI state."""
    return {
        "days": int(days),
        "mode": str(particle_mode),
        "u_var": prepared_single_cfg.get("u_var", session_state.get("sim_u_var", "uo")),
        "v_var": prepared_single_cfg.get("v_var", session_state.get("sim_v_var", "vo")),
        "lon_coord": prepared_single_cfg.get("lon_coord", session_state.get("sim_lon_coord", "longitude")),
        "lat_coord": prepared_single_cfg.get("lat_coord", session_state.get("sim_lat_coord", "latitude")),
        "time_coord": prepared_single_cfg.get("time_coord", session_state.get("sim_time_coord", "time")),
        "depth_coord": prepared_single_cfg.get("depth_coord", session_state.get("sim_depth_coord", "")),
        "particle_count": (int(particle_count_override) if int(particle_count_override) > 0 else 0),
        "seed": (int(random_seed) if int(random_seed) > 0 else 0),
        "backend": str(particle_backend),
        "dt_minutes": int(dt_minutes),
        "output_hours": int(output_hours),
        "release_mode": str(release_mode),
        "repeat_release_hours": int(repeat_release_hours),
        "sample_velocity": bool(sample_velocity),
    }


def render_single_run_success_info(runtime_hint, run_started_ts, run_ended_ts, elapsed):
    """Render success information for single run."""
    st.caption(
        f"Run timing: started {str(run_started_ts)[:19]}, ended {str(run_ended_ts)[:19]}, "
        f"elapsed {elapsed / 60:.1f} min."
    )
    st.success("Simulation finished. You can now adjust visualization controls below.")
