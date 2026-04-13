"""Batch execution helpers and result processing."""

import pandas as pd
import streamlit as st


def build_base_batch_config(use_full, max_days, days, particle_mode, session_state, particle_count_override, random_seed, particle_backend, dt_minutes, output_hours, release_mode, repeat_release_hours, sample_velocity):
    """Build base batch configuration from current UI state."""
    return {
        "days": int(max_days) if use_full else int(days),
        "mode": str(particle_mode),
        "u_var": str(session_state.get("sim_u_var", "uo")),
        "v_var": str(session_state.get("sim_v_var", "vo")),
        "lon_coord": str(session_state.get("sim_lon_coord", "longitude")),
        "lat_coord": str(session_state.get("sim_lat_coord", "latitude")),
        "time_coord": str(session_state.get("sim_time_coord", "time")),
        "depth_coord": str(session_state.get("sim_depth_coord", "")),
        "mesh_adapter": str(session_state.get("sim_mesh_adapter", "none")),
        "particle_count": int(particle_count_override),
        "seed": int(random_seed),
        "backend": str(particle_backend),
        "dt_minutes": int(dt_minutes),
        "output_hours": int(output_hours),
        "release_mode": str(release_mode),
        "repeat_release_hours": int(repeat_release_hours),
        "sample_velocity": bool(sample_velocity),
    }


def render_batch_preflight_report(preflight_rows, executable_batch, batch_runs):
    """Render batch preflight report with result summary."""
    with st.expander("Batch Preflight Report", expanded=len(executable_batch) != len(batch_runs)):
        st.dataframe(pd.DataFrame(preflight_rows), width="stretch", hide_index=True)
    
    if not executable_batch:
        st.error("All batch runs failed preflight semantic checks. Fix mappings/config and retry.")
        return False
    
    return True


def render_batch_summary(summary_rows, success_count, executable_batch):
    """Render batch execution summary table."""
    st.subheader("Batch Run Summary")
    st.dataframe(pd.DataFrame(summary_rows), width="stretch")
    
    if success_count > 0:
        return f"Batch completed: {success_count}/{len(executable_batch)} executable runs successful"
    else:
        return "Batch failed: no successful runs"
