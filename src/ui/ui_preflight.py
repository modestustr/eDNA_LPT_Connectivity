"""Preflight readiness and configuration display helpers."""

import pandas as pd
import streamlit as st


def build_preflight_rows(session_state, estimated_days, estimated_particles, particle_backend, dt_minutes, output_hours, sample_velocity, memory_risk, spatial_warnings):
    """Build preflight configuration rows for display."""
    return [
        {"Item": "U variable", "Value": session_state.get("sim_u_var", "") or "not selected"},
        {"Item": "V variable", "Value": session_state.get("sim_v_var", "") or "not selected"},
        {"Item": "Longitude coordinate", "Value": session_state.get("sim_lon_coord", "") or "not selected"},
        {"Item": "Latitude coordinate", "Value": session_state.get("sim_lat_coord", "") or "not selected"},
        {"Item": "Time coordinate", "Value": session_state.get("sim_time_coord", "") or "not selected"},
        {"Item": "Depth coordinate", "Value": session_state.get("sim_depth_coord", "") or "not used"},
        {"Item": "Duration (days)", "Value": estimated_days},
        {"Item": "Simulation preset", "Value": session_state.get("sim_selected_preset", "Custom (manual)")},
        {"Item": "Particle estimate", "Value": estimated_particles},
        {"Item": "Backend", "Value": particle_backend},
        {"Item": "Mesh adapter", "Value": session_state.get("sim_mesh_adapter", "none")},
        {"Item": "dt (minutes)", "Value": int(dt_minutes)},
        {"Item": "Output interval (hours)", "Value": int(output_hours)},
        {"Item": "Velocity sampling", "Value": bool(sample_velocity)},
        {"Item": "Memory risk tier", "Value": str(memory_risk["tier"]).upper()},
        {"Item": "Spatial sanity warnings", "Value": int(len(spatial_warnings))},
    ]


def render_preflight_readiness(session_state, estimated_days, estimated_particles, particle_backend, dt_minutes, output_hours, sample_velocity, memory_risk, spatial_warnings, runtime_hint):
    """Render preflight readiness expander with configuration table and runtime hints."""
    with st.expander("Preflight Readiness", expanded=False):
        preflight_rows = build_preflight_rows(
            session_state,
            estimated_days,
            estimated_particles,
            particle_backend,
            dt_minutes,
            output_hours,
            sample_velocity,
            memory_risk,
            spatial_warnings,
        )
        preflight_df = pd.DataFrame(preflight_rows)
        preflight_df["Value"] = preflight_df["Value"].map(
            lambda v: "Yes" if v is True else ("No" if v is False else str(v))
        )
        st.dataframe(preflight_df, width="stretch", hide_index=True)
        st.caption("This is the exact configuration that will be used when you start the run.")
        
        if runtime_hint is not None:
            st.caption(
                f"Historical runtime hint: median ~{runtime_hint['median_seconds'] / 60:.1f} min, "
                f"p75 ~{runtime_hint['p75_seconds'] / 60:.1f} min "
                f"from {runtime_hint['sample_count']} similar run(s)."
            )
        else:
            st.caption("No historical runtime estimate yet for this parameter profile.")
