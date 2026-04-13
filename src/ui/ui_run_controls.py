"""Run button controls and execution blockers."""

import streamlit as st


def get_run_blockers(tmp_path, valid_data, readiness_issues):
    """Determine blockers preventing simulation run."""
    blockers = []
    if tmp_path is None:
        blockers.append("No uploaded NetCDF file is available.")
    if not valid_data:
        blockers.append("Dataset/variable mapping is incomplete.")
    if readiness_issues:
        blockers.append(readiness_issues[0])
    return blockers


def render_run_buttons(run_blockers, first_run_mode, show_advanced_controls):
    """Render run simulation and batch buttons with appropriate state."""
    run_col1, run_col2 = st.columns(2)
    
    with run_col1:
        run_button = st.button(
            "Run Simulation",
            type="primary",
            disabled=len(run_blockers) > 0,
            help="Run is disabled until required preflight conditions are met." if run_blockers else None,
        )
    with run_col2:
        run_batch_button = st.button(
            "Run Batch",
            type="secondary",
            disabled=((first_run_mode and not show_advanced_controls) or len(run_blockers) > 0),
            help=(
                "Turn off First Run Mode or enable Advanced Controls to use batch execution."
                if (first_run_mode and not show_advanced_controls)
                else ("Batch is disabled until required preflight conditions are met." if run_blockers else None)
            ),
        )
    
    if run_blockers:
        st.warning(f"Run is blocked: {run_blockers[0]}")
    
    return run_button, run_batch_button
