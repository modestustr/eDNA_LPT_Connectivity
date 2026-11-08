"""Cost estimation expanders and memory audit rendering."""

import pandas as pd
import streamlit as st


def render_estimated_simulation_cost(estimated_days, estimated_particles, dt_minutes, estimated_steps_per_particle, estimated_outputs, estimated_operations, memory_risk, use_full):
    """Render estimated simulation cost expander."""
    with st.expander("Estimated Simulation Cost", expanded=True):
        est1, est2, est3, est4, est5 = st.columns(5)
        with est1:
            st.metric("Days", estimated_days)
        with est2:
            st.metric("Particles", estimated_particles)
        with est3:
            st.metric("dt (minutes)", int(dt_minutes))
        with est4:
            st.metric("Steps / Particle", estimated_steps_per_particle)
        with est5:
            st.metric("Saved Frames", estimated_outputs)
        
        st.caption(
            f"Approx workload index: {estimated_operations:,} particle-kernel steps. "
            f"Longer runs are mainly driven by full-duration mode, 10-minute dt, sampled velocity, and hourly outputs."
        )
        st.caption(
            f"Estimated trajectory-memory footprint: ~{memory_risk['estimated_mb']:.0f} MB "
            f"(effective particle instances: {memory_risk['effective_particle_instances']:,}, frames: {memory_risk['frames']:,})."
        )
        if memory_risk["tier"] == "high":
            st.error(f"Memory Risk: HIGH. {memory_risk['guidance']}")
        elif memory_risk["tier"] == "medium":
            st.warning(f"Memory Risk: MEDIUM. {memory_risk['guidance']}")
        else:
            st.success(f"Memory Risk: LOW. {memory_risk['guidance']}")
        if use_full:
            st.warning("Use full dataset duration is enabled. This is the biggest reason default runs can become unexpectedly long.")
        if int(dt_minutes) <= 2:
            st.warning("Very small dt selected. A 1-2 minute timestep increases integration cost dramatically.")
        elif int(dt_minutes) <= 5:
            st.info("Small dt selected. Runtime rises quickly below 10 minutes.")


def render_memory_materialization_audit(build_inventory_func):
    """Render memory materialization audit expander."""
    with st.expander("Memory Materialization Audit", expanded=False):
        audit_df = pd.DataFrame(build_inventory_func())
        st.dataframe(audit_df, width="stretch", hide_index=True)
        st.caption(
            "This inventory highlights major in-memory materialization points used in the current workflow. "
            "High-risk entries have runtime guardrails in cost and visualization panels."
        )
