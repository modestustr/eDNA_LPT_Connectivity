"""Visualization memory and control rendering."""

import streamlit as st


def render_visualization_memory_check(viz_memory_risk):
    """Render visualization memory risk assessment and confirmation."""
    st.caption(
        f"Estimated render memory load: ~{viz_memory_risk['estimated_mb']:.0f} MB "
        f"for {viz_memory_risk['trajectory_count']:,} trajectories x {viz_memory_risk['frames']} frame(s)."
    )
    if viz_memory_risk["tier"] == "medium":
        st.warning("Visualization memory risk: MEDIUM. Consider higher point thinning or lower selected step.")
    elif viz_memory_risk["tier"] == "high":
        st.error("Visualization memory risk: HIGH. Rendering can be slow or unstable on limited-memory systems.")
        st.checkbox(
            "I understand. Proceed with high-memory render.",
            key="viz_confirm_high_memory_render",
            help="Required for very heavy render loads.",
        )
        if not st.session_state.get("viz_confirm_high_memory_render", False):
            st.info("Enable the confirmation checkbox to continue rendering this frame.")
            return False
    return True


def render_visualization_header_alerts(use_full, dt_minutes):
    """Render header-level alerts for visualization parameters."""
    if use_full:
        st.warning("Use full dataset duration is enabled. This is the biggest reason default runs can become unexpectedly long.")
    if int(dt_minutes) <= 2:
        st.warning("Very small dt selected. A 1-2 minute timestep increases integration cost dramatically.")
    elif int(dt_minutes) <= 5:
        st.info("Small dt selected. Runtime rises quickly below 10 minutes.")
