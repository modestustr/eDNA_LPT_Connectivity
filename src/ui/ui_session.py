"""Session management and runtime cleanup helpers."""

import os
import shutil
import time
import uuid

import streamlit as st


SESSION_RETENTION_HOURS = 72


def cleanup_stale_runtime_sessions(runs_root, current_session_id, max_age_hours=SESSION_RETENTION_HOURS):
    """Remove stale session runtime folders to avoid unbounded disk growth."""
    if not os.path.isdir(runs_root):
        return 0
    now_ts = time.time()
    removed = 0
    for name in os.listdir(runs_root):
        path = os.path.join(runs_root, name)
        if not os.path.isdir(path):
            continue
        if str(name) == str(current_session_id):
            continue
        try:
            age_hours = (now_ts - os.path.getmtime(path)) / 3600.0
        except OSError:
            continue
        if age_hours >= float(max_age_hours):
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed


SIMULATION_STATE_DEFAULTS = {
    "sim_use_full": False,
    "sim_days": 2,
    "sim_particle_mode": "random",
    "sim_particle_backend": "scipy",
    "sim_u_var": "uo",
    "sim_v_var": "vo",
    "sim_lon_coord": "longitude",
    "sim_lat_coord": "latitude",
    "sim_time_coord": "time",
    "sim_depth_coord": "",
    "sim_mesh_adapter": "none",
    "sim_particle_count_override": 0,
    "sim_random_seed": 0,
    "sim_dt_minutes": 10,
    "sim_output_hours": 3,
    "sim_release_mode": "instant",
    "sim_repeat_release_hours": 6,
    "sim_sample_velocity": True,
    "sim_selected_preset": "Custom (manual)",
    "sim_last_applied_preset": "Custom (manual)",
    "sim_batch_config_text": "",
    "sim_batch_form_rows": [],
    "sim_batch_import_text": "",
    "runtime_stats": [],
    "batch_last_summary": [],
    "run_history": [],
    "ux_first_run_mode": True,
    "ux_show_advanced_controls": False,
}


def ensure_simulation_state_defaults():
    """Initialise all simulation session-state keys to their default values
    if they have not yet been set.

    Must be called once near the top of the Streamlit script before any widget
    that reads from st.session_state is evaluated.  Uses setdefault() so
    existing values are never overwritten during reruns.
    """
    for key, value in SIMULATION_STATE_DEFAULTS.items():
        st.session_state.setdefault(key, value)


def init_session_id():
    """Initialize or retrieve the current session ID."""
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = uuid.uuid4().hex[:8]
    return st.session_state["session_id"]
