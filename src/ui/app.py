import streamlit as st
import xarray as xr
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.colors
import matplotlib.cm
from matplotlib.collections import LineCollection
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import os
import numpy as np
import pandas as pd
import io
import json
import zipfile
import time
import requests
from src.core import simulation_service
from src.core.simulation_contracts import RunStatus
from src.api import initialize_simulation_api
from src.ui.ui_history import render_run_history_and_comparison
from src.ui.ui_runtime import (
    build_runtime_signature,
    estimate_runtime_hint,
    record_runtime_stat,
    restore_run_history_config,
    save_run_history_entry,
)
from src.ui.ui_batch import (
    _build_batch_payload_from_rows,
    _default_batch_form_rows,
    apply_simulation_preset,
    get_simulation_presets,
    parse_batch_config_payload,
)
from src.ui.ui_geoanalytics import (
    build_station_metrics_geojson,
    build_trajectory_geojson,
    get_station_analytics,
)
from src.ui.ui_markdown import (
    load_markdown_file,
    parse_markdown_sections,
    render_sections_as_expanders,
)
from src.ui.ui_data import (
    get_netcdf_domain_extent,
    get_zarr_metadata,
    get_zarr_particle_extent,
    get_zarr_qc_summary,
    get_zarr_step_data,
    get_zarr_step_summary,
    parse_stations_csv,
)
from src.ui.ui_adapt import (
    build_run_output_path,
    prepare_dataset_for_run,
)
from src.ui.ui_storage import get_or_cache_uploaded_file, snapshot_run_output, ensure_runtime_paths
from src.ui.ui_validation import (
    build_dataset_readiness_report,
    build_spatial_sanity_warnings,
    get_actionable_error_guidance,
    name_exists_in_dataset,
    validate_dataset_structure,
    validate_run_semantics,
)
from src.ui.ui_session import (
    ensure_simulation_state_defaults,
)
from src.ui.ui_estimation import (
    build_memory_materialization_inventory,
    estimate_memory_risk_tier,
    estimate_particle_count,
    estimate_visualization_memory_risk,
)
from src.ui.ui_visualization import (
    apply_visualization_preset,
    format_station_caption,
    build_trajectory_csv_records,
)
from src.ui.ui_sidebar import (
    render_library_versions,
    render_scientific_context,
    render_stations_uploader,
)
from src.ui.ui_help import render_help_tab
from src.ui.ui_preflight import render_preflight_readiness
from src.ui.ui_cost import render_estimated_simulation_cost, render_memory_materialization_audit
from src.ui.ui_run_controls import get_run_blockers, render_run_buttons
from src.ui.ui_viz_controls import render_visualization_memory_check
from src.ui.ui_batch_execution import build_base_batch_config
from src.ui.ui_single_execution import build_single_run_config, render_single_run_success_info

APP_ROOT = os.path.dirname(os.path.abspath(__file__))


# ------------------------------------------------------------
# ROADMAP TODO (persistent project checklist)
# ------------------------------------------------------------
# [x] 1) Preset profiles for one-click visualization setup
#       - Fast Explore, Publication Quality, Station Focus
# [x] 2) Export bundle
#       - Single ZIP containing map PNG + trajectories CSV + run params JSON
# [x] 3) QC summary panel
#       - Initial/active counts, out-of-bounds ratio, mean/max speed
# [x] 4) Run history with restore
#       - Save previous simulation settings and reload with one click
# [x] 5) Comparison mode (A/B)
#       - Compare two runs (seed/mode/dt) side-by-side
# [x] 6) Station analytics
#       - Entries near station, first-arrival times, station connectivity matrix
# [x] 7) Batch execution mode
#       - Run multiple parameter sets and summarize outputs in one table
# [x] 8) Additional rendering controls
#       - Active-only trajectories, trajectory cap, time-window plotting
# [x] 9) UX hardening
#       - More actionable error messages and guided fixes for data issues
# [x] 10) Documentation
#       - Detailed README.md with setup, workflow, data schema, troubleshooting


# Page configuration
st.set_page_config(page_title="eDNA LPT Connectivity Analysis", layout="wide")

# Initialize simulation API layer
# Try to connect to local API server first, fall back to LOCAL mode
if 'api_client' not in st.session_state:
    try:
        # Try to reach API server (retry a few times in case it's still initializing)
        for attempt in range(3):
            try:
                response = requests.get("http://127.0.0.1:8000/health", timeout=2)
                if response.status_code == 200:
                    # API server is running, use HTTP client
                    from src.api.client import SimulationAPIClient
                    st.session_state['api_client'] = SimulationAPIClient(http_base_url="http://127.0.0.1:8000")
                    st.session_state['api_mode'] = "API"
                    break
            except:
                if attempt < 2:
                    time.sleep(1)  # Brief wait before retry
                    continue
                raise
    except:
        pass
    
    # Fall back to LOCAL mode if API server not available
    if st.session_state.get('api_mode') != "API":
        st.session_state['api_client'] = initialize_simulation_api(
            simulation_service.run_simulation_with_result
        )
        st.session_state['api_mode'] = "LOCAL"
    
    # Show current mode in sidebar
    mode_emoji = "📡" if st.session_state.get('api_mode') == "API" else "💻"
    st.sidebar.info(f"{mode_emoji} Mode: **{st.session_state.get('api_mode', 'LOCAL')}**")

# Get the initialized client for this execution
api_client = st.session_state['api_client']


# Helper for Streamlit progress bar integration with API
def _streamlit_progress_callback(progress_bar, percent: int, message: str):
    """Callback adapter: translates API progress to Streamlit progress bar."""
    try:
        progress_bar.progress(min(percent / 100.0, 1.0), text=message)
    except Exception:
        pass  # Silent fail if progress bar is stale


# -----------------------------
# SIDEBAR: METADATA & REFERENCES
# -----------------------------
render_library_versions()
render_scientific_context()
# -----------------------------
# SIDEBAR: SAMPLING STATIONS LOADER
# -----------------------------
stations_df = render_stations_uploader(parse_stations_csv)

# -----------------------------
# MAIN PAGE: HEADER & OVERVIEW
# -----------------------------
st.title("Lagrangian Particle Tracking (LPT) Connectivity Dashboard")
st.subheader("Hydrodynamic Connectivity Analysis")

overview_tab, help_tab = st.tabs(["Overview", "How To / Help"])

with overview_tab:
    st.markdown(
        """
### Project Overview
This application visualizes the transport of passive particles in a user-supplied hydrodynamic flow field.
It is designed for general Lagrangian connectivity analysis rather than a single fixed region or event.

**Key Research Objectives:**
- Evaluate particle transport pathways between user-defined source and sink areas.
- Quantify how the uploaded flow field structures transport and retention.
- Provide a physical interpretation layer for station-based observations such as eDNA, ecology, or tracer sampling.
"""
    )

with help_tab:
    render_help_tab(
        load_markdown_func=load_markdown_file,
        parse_markdown_sections_func=parse_markdown_sections,
        render_sections_as_expanders_func=render_sections_as_expanders,
        quick_markdown_file="../../docs/HOW_TO.md",
        tech_markdown_file="../../docs/README.md",
    )

st.divider()

# -----------------------------
# MAIN PAGE: DATA MANAGEMENT
# -----------------------------
st.header("1. Data Management")
uploaded_file = st.file_uploader("Upload hydrodynamic NetCDF (.nc)", type=["nc"])

runtime_paths = ensure_runtime_paths()
ZARR_PATH = str(st.session_state.get("active_output_path", "")).strip()
tmp_path = None
days = 2
valid_data = False  # Flag to control simulation execution
particle_mode = "unknown"
particle_backend = "scipy"
particle_count_override = 0
random_seed = 0
dt_minutes = 10
output_hours = 1
release_mode = "instant"
repeat_release_hours = 6
sample_velocity = True

ensure_simulation_state_defaults()

# Handle pending restore (from run history select -> restore button click)
if st.session_state.get("_pending_restore_config"):
    config = st.session_state.pop("_pending_restore_config")
    max_days = st.session_state.pop("_pending_restore_max_days")
    restore_run_history_config(st.session_state, config, max_days)
    st.success("✓ Run configuration restored successfully!")

# -----------------------------
# FILE HANDLING, VALIDATION & METADATA
# -----------------------------
if uploaded_file is not None:
    tmp_path, upload_error = get_or_cache_uploaded_file(uploaded_file, st.session_state, ensure_runtime_paths)
    if upload_error:
        st.error(upload_error)
        tmp_path = None

if uploaded_file and tmp_path:
    # Open dataset to validate contents
    ds_temp = xr.open_dataset(tmp_path)
    data_var_names = sorted([str(v) for v in ds_temp.data_vars.keys()])
    axis_names = sorted([str(v) for v in ds_temp.variables.keys()])

    # Check for required velocity variables
    has_uo = "uo" in ds_temp.data_vars
    has_vo = "vo" in ds_temp.data_vars
    if has_uo:
        st.session_state["sim_u_var"] = "uo"
    elif st.session_state.get("sim_u_var") not in data_var_names:
        st.session_state["sim_u_var"] = ""

    if has_vo:
        st.session_state["sim_v_var"] = "vo"
    elif st.session_state.get("sim_v_var") not in data_var_names:
        st.session_state["sim_v_var"] = ""

    if "longitude" in ds_temp.variables:
        st.session_state["sim_lon_coord"] = "longitude"
    elif st.session_state.get("sim_lon_coord") not in axis_names:
        st.session_state["sim_lon_coord"] = "lon" if "lon" in ds_temp.variables else ""

    if "latitude" in ds_temp.variables:
        st.session_state["sim_lat_coord"] = "latitude"
    elif st.session_state.get("sim_lat_coord") not in axis_names:
        st.session_state["sim_lat_coord"] = "lat" if "lat" in ds_temp.variables else ""

    if "time" in ds_temp.variables:
        st.session_state["sim_time_coord"] = "time"
    elif st.session_state.get("sim_time_coord") not in axis_names:
        for candidate in ["time_counter", "ocean_time", "Times", "t"]:
            if candidate in ds_temp.variables:
                st.session_state["sim_time_coord"] = candidate
                break
        else:
            st.session_state["sim_time_coord"] = ""

    if st.session_state.get("sim_depth_coord") and st.session_state.get("sim_depth_coord") not in axis_names:
        st.session_state["sim_depth_coord"] = ""
    elif not st.session_state.get("sim_depth_coord"):
        for candidate in ["depth", "lev", "depthu", "depthv", "z"]:
            if candidate in ds_temp.variables:
                st.session_state["sim_depth_coord"] = candidate
                break

    selected_u_var = st.session_state.get("sim_u_var", "")
    selected_v_var = st.session_state.get("sim_v_var", "")
    selected_lon_coord = st.session_state.get("sim_lon_coord", "")
    selected_lat_coord = st.session_state.get("sim_lat_coord", "")
    selected_time_coord = st.session_state.get("sim_time_coord", "")
    selected_depth_coord = st.session_state.get("sim_depth_coord", "")
    readiness_df, readiness_issues = build_dataset_readiness_report(
        ds_temp,
        selected_u_var,
        selected_v_var,
        selected_lon_coord,
        selected_lat_coord,
        selected_time_coord,
        selected_depth_coord,
    )
    spatial_warnings = build_spatial_sanity_warnings(ds_temp, selected_lon_coord, selected_lat_coord)
    valid_data = (
        selected_u_var in ds_temp.data_vars
        and selected_v_var in ds_temp.data_vars
        and name_exists_in_dataset(ds_temp, selected_lon_coord)
        and name_exists_in_dataset(ds_temp, selected_lat_coord)
        and name_exists_in_dataset(ds_temp, selected_time_coord)
        and selected_u_var != selected_v_var
        and selected_lon_coord != selected_lat_coord
        and len(validate_dataset_structure(ds_temp, selected_u_var, selected_v_var, selected_lon_coord, selected_lat_coord, selected_time_coord, selected_depth_coord)) == 0
    )

    with st.expander("View Uploaded NetCDF File Details", expanded=True):
        st.markdown("**Detected Variables:**")
        st.code(", ".join(list(ds_temp.data_vars.keys())))

        has_default_lon = "longitude" in ds_temp.variables
        has_default_lat = "latitude" in ds_temp.variables
        has_default_time = "time" in ds_temp.variables
        if has_uo and has_vo and has_default_lon and has_default_lat and has_default_time:
            st.success(
                "Velocity fields ('uo', 'vo') and axes ('longitude', 'latitude', 'time') detected automatically. Ready for simulation."
            )
        else:
            st.warning(
                "Default velocity fields and/or coordinates were not fully found. "
                "Use the mapping controls below to choose U, V, longitude, latitude, and time names."
            )
            st.markdown("**Velocity Variable Mapping**")
            map_col1, map_col2 = st.columns(2)
            with map_col1:
                st.selectbox(
                    "Eastward Velocity Variable (U)",
                    options=[""] + data_var_names,
                    key="sim_u_var",
                    help="Map the dataset variable that represents the eastward velocity component.",
                )
            with map_col2:
                st.selectbox(
                    "Northward Velocity Variable (V)",
                    options=[""] + data_var_names,
                    key="sim_v_var",
                    help="Map the dataset variable that represents the northward velocity component.",
                )

            st.markdown("**Coordinate Mapping**")
            coord_col1, coord_col2 = st.columns(2)
            with coord_col1:
                st.selectbox(
                    "Longitude Coordinate",
                    options=[""] + axis_names,
                    key="sim_lon_coord",
                    help="Map the coordinate that stores longitudes for the hydrodynamic grid.",
                )
            with coord_col2:
                st.selectbox(
                    "Latitude Coordinate",
                    options=[""] + axis_names,
                    key="sim_lat_coord",
                    help="Map the coordinate that stores latitudes for the hydrodynamic grid.",
                )

            st.markdown("**Time / Vertical Mapping**")
            axis_col1, axis_col2 = st.columns(2)
            with axis_col1:
                st.selectbox(
                    "Time Coordinate",
                    options=[""] + axis_names,
                    key="sim_time_coord",
                    help="Map the axis that stores model time.",
                )
            with axis_col2:
                st.selectbox(
                    "Depth Coordinate (optional)",
                    options=[""] + axis_names,
                    key="sim_depth_coord",
                    help="Select this when the velocity fields include a vertical axis.",
                )

            selected_u_var = st.session_state.get("sim_u_var", "")
            selected_v_var = st.session_state.get("sim_v_var", "")
            selected_lon_coord = st.session_state.get("sim_lon_coord", "")
            selected_lat_coord = st.session_state.get("sim_lat_coord", "")
            selected_time_coord = st.session_state.get("sim_time_coord", "")
            selected_depth_coord = st.session_state.get("sim_depth_coord", "")
            valid_data = (
                selected_u_var in ds_temp.data_vars
                and selected_v_var in ds_temp.data_vars
                and name_exists_in_dataset(ds_temp, selected_lon_coord)
                and name_exists_in_dataset(ds_temp, selected_lat_coord)
                and name_exists_in_dataset(ds_temp, selected_time_coord)
                and selected_u_var != selected_v_var
                and selected_lon_coord != selected_lat_coord
                and len(validate_dataset_structure(ds_temp, selected_u_var, selected_v_var, selected_lon_coord, selected_lat_coord, selected_time_coord, selected_depth_coord)) == 0
            )

            if selected_u_var == selected_v_var and selected_u_var:
                st.error("U and V variables must be different fields.")
            elif selected_lon_coord == selected_lat_coord and selected_lon_coord:
                st.error("Longitude and latitude coordinates must be different fields.")
            elif valid_data:
                st.success(
                    f"Mapping ready: U='{selected_u_var}', V='{selected_v_var}', Lon='{selected_lon_coord}', Lat='{selected_lat_coord}', Time='{selected_time_coord}', Depth='{selected_depth_coord or 'not used'}'."
                )
            else:
                st.info("Choose U, V, longitude, latitude, and time names. Add depth when the velocity fields contain a vertical dimension.")

        st.markdown("**Detected Dimensions:**")
        st.code(str(dict(ds_temp.sizes)))

        with st.expander("Compatibility Checklist", expanded=not valid_data):
            st.dataframe(readiness_df, width="stretch", hide_index=True)
            if readiness_issues:
                st.markdown("**What to fix before running:**")
                for issue in readiness_issues:
                    st.write(f"- {issue}")
            else:
                st.success("Dataset structure looks compatible with the current app configuration.")
            if spatial_warnings:
                st.markdown("**Spatial Sanity Warnings (non-blocking):**")
                for warn in spatial_warnings:
                    st.warning(warn)

        if selected_time_coord and selected_time_coord in ds_temp.variables:
            start_time = str(ds_temp[selected_time_coord].values[0])[:19]
            end_time = str(ds_temp[selected_time_coord].values[-1])[:19]
            st.markdown("**Time Coverage:**")
            st.info(f"{start_time} to {end_time}")

        # Cache source domain so Zoom Out can work even when tmp upload path changes
        lon_name = st.session_state.get("sim_lon_coord", "") if name_exists_in_dataset(ds_temp, st.session_state.get("sim_lon_coord", "")) else None
        lat_name = st.session_state.get("sim_lat_coord", "") if name_exists_in_dataset(ds_temp, st.session_state.get("sim_lat_coord", "")) else None
        if lon_name is not None and lat_name is not None:
            st.session_state["source_domain_extent"] = (
                float(ds_temp[lon_name].min()),
                float(ds_temp[lon_name].max()),
                float(ds_temp[lat_name].min()),
                float(ds_temp[lat_name].max()),
            )

    if valid_data:
        st.header("2. Simulation Parameters")
        if selected_time_coord and selected_time_coord in ds_temp.variables:
            max_days = max(1, len(ds_temp[selected_time_coord]) - 1)
        else:
            max_days = 2
        if st.session_state.sim_days > max_days:
            st.session_state.sim_days = int(max_days)

        history_count = len(st.session_state.run_history)
        if history_count == 0 and st.session_state.get("ux_first_run_mode") is False:
            st.session_state["ux_first_run_mode"] = True

        st.toggle(
            "First Run Mode (Recommended)",
            key="ux_first_run_mode",
            help="Keeps the interface focused on the minimum path: map fields, choose core settings, run simulation.",
        )
        first_run_mode = bool(st.session_state.get("ux_first_run_mode", True))
        if first_run_mode:
            st.info(
                "First Run Mode is ON: advanced, batch, and comparison workflows are hidden by default. "
                "Use this mode for the quickest first successful run."
            )

        if first_run_mode:
            st.checkbox(
                "Show Advanced Controls",
                key="ux_show_advanced_controls",
                value=False,
                help="Reveal backend, mesh adapter, and batch controls.",
            )
        else:
            st.session_state["ux_show_advanced_controls"] = True
        show_advanced_controls = bool(st.session_state.get("ux_show_advanced_controls", False))

        preset_catalog = get_simulation_presets(max_days)
        preset_options = ["Custom (manual)"] + list(preset_catalog.keys())
        if st.session_state.get("sim_selected_preset") not in preset_options:
            st.session_state["sim_selected_preset"] = "Custom (manual)"

        # preset_col1, preset_col3 = st.columns([2, 3])
        # with preset_col1:
        st.selectbox(
            "Simulation Preset",
            options=preset_options,
            key="sim_selected_preset",
            help="Presets are for single-run setup. Batch mode remains a separate multi-run workflow.",
        )
        # with preset_col3:
        st.caption("Preset = one-run quick setup. Batch = multiple runs for sensitivity/comparison. Preset selection applies automatically.")

        selected_preset = st.session_state.get("sim_selected_preset", "Custom (manual)")
        last_applied_preset = st.session_state.get("sim_last_applied_preset", "Custom (manual)")
        if selected_preset != last_applied_preset:
            st.session_state["sim_last_applied_preset"] = selected_preset
            if selected_preset == "Custom (manual)":
                st.info("Custom (manual) selected. Preset auto-apply is disabled for manual tuning.")
            else:
                ok, msg = apply_simulation_preset(st.session_state, selected_preset, max_days)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

        use_full = st.checkbox("Use full dataset duration", key="sim_use_full")
        days = (
            max_days
            if use_full
            else st.slider(
                "Simulation Duration (days)", 1, int(max_days), key="sim_days"
            )
        )
    ds_temp.close()

else:
    st.header("2. Simulation Parameters")

# -----------------------------
# PARTICLE MODE SELECTION (Visible only if data is valid)
# -----------------------------
if valid_data:
    particle_mode = st.selectbox(
        "Particle Mode", ["uniform", "random", "hybrid", "valid"], key="sim_particle_mode"
    )
    # Display mode-specific information
    st.warning(
        f"USER NOTICE: This simulation uses U='{st.session_state.get('sim_u_var', '')}' and "
        f"V='{st.session_state.get('sim_v_var', '')}' as velocity fields. "
        "If particles go out-of-bounds, this is expected physical behavior and not an error in the code."
    )
    if particle_mode == "uniform":
        st.info(
            "**Technical Details: Uniform Mode**\n\n"
            "**Logic:** Generates an N x N grid using `numpy.meshgrid`.\n"
            "**Particle Count (N=10):** Set as a baseline debug value. It creates a 3x3 (9 particles) "
            "deterministic matrix to verify boundary conditions without computational overhead."
        )
    elif particle_mode == "random":
        st.info(
            "**Technical Details: Random Mode**\n\n"
            "**Logic:** Stochastic uniform distribution via `numpy.random.uniform`.\n"
            "**Particle Count (N=200):** Selected as the 'Optimization Sweet Spot' for UI responsiveness."
        )
    elif particle_mode == "hybrid":
        st.info(
            "**Technical Details: Hybrid Mode**\n\n"
            "**Logic:** Bimodal distribution (Global + Hotspot).\n"
            "**Particle Count (100:200):** Simulates a 1:2 ratio of background noise vs concentrated release."
        )
    elif particle_mode == "valid":
        st.info(
            "**Technical Details: Valid (Grid) Mode**\n\n"
            "**Logic:** Direct sampling from the hydrodynamic FieldSet grid nodes.\n"
            "**Particle Count (N=200):** Ensures particles start exactly on the selected hydrodynamic grid nodes."
        )

    st.markdown("---")
    st.markdown(
        "### Numerical Rationale\n"
        "Particle counts are constrained by **Web-UI Rendering Limits** to ensure interactive frame rates."
    )

    if show_advanced_controls:
        with st.expander("Advanced Simulation Settings", expanded=False):
            st.markdown(
            """
**How and Why to Use These Settings**

- **Backend:** `scipy` is the safest default. `jit` can be faster for large runs, but it needs a C compiler on the system.
- **Particle Count Override:** controls statistical coverage. Lower is faster; higher is more representative.
- **Random Seed:** use a fixed value (e.g. `42`) for reproducible runs.
- **Advection Time Step (minutes):** lower values improve numerical stability/accuracy but increase runtime.
- **Output Interval (hours):** lower values save denser trajectories but produce larger output.
- **Release Strategy:**
  - `instant`: one-time pulse release.
  - `repeated`: continuous source behavior using periodic releases.
- **Repeated Release Interval (hours):** only used in `repeated` mode; shorter interval means more frequent injection.
- **Sample Velocity Along Trajectories:** stores sampled `u`, `v`, and speed values for downstream interpretation.
"""
        )

            st.info(
            "Recommended starting profile: backend=scipy, particle_count=200, "
            "seed=42, dt=10 min, output=1 hour, release=instant"
            )

            particle_backend = st.selectbox(
            "Backend",
            ["scipy", "jit"],
            help="scipy is generally more compatible; jit can be faster but requires a working C compiler.",
            key="sim_particle_backend",
            )

            mesh_adapter = st.selectbox(
            "Mesh Adapter",
            ["none", "flattened_grid_1d"],
            help="Use flattened_grid_1d when velocity is stored on a 1D flattened node grid that can be reshaped into regular lat/lon.",
            key="sim_mesh_adapter",
            )

            if particle_backend == "jit":
                st.warning(
                "JIT requires a C compiler (e.g., gcc/clang). If unavailable, select scipy."
                )

            particle_count_override = st.number_input(
            "Particle Count Override (0 = mode default)",
            min_value=0,
            step=10,
            key="sim_particle_count_override",
            )
            random_seed = st.number_input(
            "Random Seed (0 = random)",
            min_value=0,
            step=1,
            key="sim_random_seed",
            )
            dt_minutes = st.slider(
            "Advection Time Step (minutes)", min_value=1, max_value=60, key="sim_dt_minutes"
            )
            output_hours = st.slider(
            "Output Interval (hours)", min_value=1, max_value=24, key="sim_output_hours"
            )
            release_mode = st.selectbox(
            "Release Strategy",
            ["instant", "repeated"],
            help="instant releases particles once; repeated injects new particles at a fixed interval.",
            key="sim_release_mode",
            )
            if release_mode == "repeated":
                repeat_release_hours = st.slider(
                "Repeated Release Interval (hours)",
                min_value=1,
                max_value=24,
                key="sim_repeat_release_hours",
                )
            sample_velocity = st.checkbox(
            "Sample Velocity Along Trajectories",
            help="Stores sampled u, v and speed fields in the trajectory output.",
            key="sim_sample_velocity",
            )
    elif first_run_mode:
        st.caption("Advanced simulation controls are hidden in First Run Mode.")

    if show_advanced_controls:
        with st.expander("Batch Execution Mode", expanded=False):
            st.caption(
                "Define multiple runs in a form. The app converts these rows to batch JSON internally "
                "and sends the same validated payload to preflight and execution."
            )

            if not st.session_state.get("sim_batch_form_rows"):
                st.session_state["sim_batch_form_rows"] = _default_batch_form_rows(days, particle_mode, random_seed)

            form_rows_df = pd.DataFrame(st.session_state.get("sim_batch_form_rows", []))
            if form_rows_df.empty:
                form_rows_df = pd.DataFrame(_default_batch_form_rows(days, particle_mode, random_seed))

            desired_order = [
                "name",
                "use_full",
                "days",
                "mode",
                "mesh_adapter",
                "backend",
                "dt_minutes",
                "output_hours",
                "particle_count",
                "seed",
                "release_mode",
                "repeat_release_hours",
                "sample_velocity",
                "u_var",
                "v_var",
                "lon_coord",
                "lat_coord",
                "time_coord",
                "depth_coord",
            ]
            for col in desired_order:
                if col not in form_rows_df.columns:
                    form_rows_df[col] = "" if col not in {"use_full", "sample_velocity"} else False
            form_rows_df = form_rows_df[desired_order]

            edited_batch_df = st.data_editor(
                form_rows_df,
                key="sim_batch_form_editor",
                num_rows="dynamic",
                width="stretch",
                hide_index=True,
                column_config={
                    "name": st.column_config.TextColumn("Name"),
                    "use_full": st.column_config.CheckboxColumn("Use full"),
                    "days": st.column_config.NumberColumn("Days", min_value=1, step=1),
                    "mode": st.column_config.SelectboxColumn("Mode", options=["uniform", "random", "hybrid", "valid"]),
                    "mesh_adapter": st.column_config.SelectboxColumn("Mesh adapter", options=["none", "flattened_grid_1d"]),
                    "backend": st.column_config.SelectboxColumn("Backend", options=["scipy", "jit"]),
                    "dt_minutes": st.column_config.NumberColumn("dt (min)", min_value=1, max_value=60, step=1),
                    "output_hours": st.column_config.NumberColumn("Output (h)", min_value=1, max_value=24, step=1),
                    "particle_count": st.column_config.NumberColumn("Particle override", min_value=0, step=1),
                    "seed": st.column_config.NumberColumn("Seed", min_value=0, step=1),
                    "release_mode": st.column_config.SelectboxColumn("Release", options=["instant", "repeated"]),
                    "repeat_release_hours": st.column_config.NumberColumn("Repeat (h)", min_value=1, max_value=24, step=1),
                    "sample_velocity": st.column_config.CheckboxColumn("Sample vel"),
                    "u_var": st.column_config.TextColumn("U var"),
                    "v_var": st.column_config.TextColumn("V var"),
                    "lon_coord": st.column_config.TextColumn("Lon coord"),
                    "lat_coord": st.column_config.TextColumn("Lat coord"),
                    "time_coord": st.column_config.TextColumn("Time coord"),
                    "depth_coord": st.column_config.TextColumn("Depth coord"),
                },
            )
            st.session_state["sim_batch_form_rows"] = edited_batch_df.to_dict(orient="records")

            current_batch_payload = _build_batch_payload_from_rows(st.session_state.get("sim_batch_form_rows", []))
            st.session_state["sim_batch_config_text"] = json.dumps(current_batch_payload, indent=2)

            import_col, export_col = st.columns([1, 1])
            with import_col:
                st.text_area(
                    "Import Batch JSON",
                    key="sim_batch_import_text",
                    height=110,
                    help="Paste a JSON list of run objects and click Apply Import.",
                )
                if st.button("Apply Import", key="sim_batch_apply_import"):
                    try:
                        imported_payload = json.loads(str(st.session_state.get("sim_batch_import_text", "")).strip() or "[]")
                        if not isinstance(imported_payload, list):
                            raise ValueError("Imported JSON must be a list of run objects.")
                        st.session_state["sim_batch_form_rows"] = imported_payload
                        st.success(f"Imported {len(imported_payload)} batch row(s).")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Import failed: {e}")
            with export_col:
                st.download_button(
                    "Export Batch JSON",
                    data=st.session_state.get("sim_batch_config_text", "[]"),
                    file_name="batch_config.json",
                    mime="application/json",
                    key="sim_batch_export_json",
                )
    elif first_run_mode:
        st.caption("Batch execution is hidden in First Run Mode.")

    # Always resolve runtime simulation knobs from session state, even when
    # advanced controls are hidden by First Run Mode.
    particle_backend = str(st.session_state.get("sim_particle_backend", "scipy"))
    mesh_adapter = str(st.session_state.get("sim_mesh_adapter", "none"))
    particle_count_override = int(st.session_state.get("sim_particle_count_override", 0))
    random_seed = int(st.session_state.get("sim_random_seed", 0))
    dt_minutes = int(st.session_state.get("sim_dt_minutes", 10))
    output_hours = int(st.session_state.get("sim_output_hours", 3))
    release_mode = str(st.session_state.get("sim_release_mode", "instant"))
    repeat_release_hours = int(st.session_state.get("sim_repeat_release_hours", 6))
    sample_velocity = bool(st.session_state.get("sim_sample_velocity", True))

    estimated_days = int(max_days) if use_full else int(days)
    estimated_particles = estimate_particle_count(particle_mode, particle_count_override)
    steps_per_day = max(1, int((24 * 60) / int(dt_minutes)))
    estimated_steps_per_particle = estimated_days * steps_per_day
    kernel_count = 3 if sample_velocity else 2
    estimated_operations = estimated_particles * estimated_steps_per_particle * kernel_count
    estimated_outputs = max(1, int((estimated_days * 24) / max(1, int(output_hours))))
    memory_risk = estimate_memory_risk_tier(
        estimated_days=estimated_days,
        estimated_particles=estimated_particles,
        output_hours=output_hours,
        sample_velocity=sample_velocity,
        release_mode=release_mode,
        repeat_release_hours=repeat_release_hours,
    )
    runtime_signature = build_runtime_signature(
        days=estimated_days,
        particles=estimated_particles,
        mode=particle_mode,
        backend=particle_backend,
        dt_minutes=dt_minutes,
        output_hours=output_hours,
        release_mode=release_mode,
        repeat_release_hours=repeat_release_hours,
        sample_velocity=sample_velocity,
    )
    runtime_hint = estimate_runtime_hint(st.session_state, runtime_signature)

    render_estimated_simulation_cost(
        estimated_days,
        estimated_particles,
        dt_minutes,
        estimated_steps_per_particle,
        estimated_outputs,
        estimated_operations,
        memory_risk,
        use_full,
    )

    render_memory_materialization_audit(build_memory_materialization_inventory)

    with st.expander("Preflight Readiness", expanded=False):
        render_preflight_readiness(
            st.session_state,
            estimated_days,
            estimated_particles,
            particle_backend,
            dt_minutes,
            output_hours,
            sample_velocity,
            memory_risk,
            spatial_warnings,
            runtime_hint,
        )

    run_blockers = get_run_blockers(tmp_path, valid_data, readiness_issues)
    run_button, run_batch_button = render_run_buttons(run_blockers, first_run_mode, show_advanced_controls)

    # -----------------------------
    # EXECUTION
    # -----------------------------
    if run_batch_button and tmp_path is not None:
        base_batch_config = build_base_batch_config(
            use_full,
            max_days,
            days,
            particle_mode,
            st.session_state,
            particle_count_override,
            random_seed,
            particle_backend,
            dt_minutes,
            output_hours,
            release_mode,
            repeat_release_hours,
            sample_velocity,
        )
        batch_runs, batch_errors = parse_batch_config_payload(
            _build_batch_payload_from_rows(st.session_state.get("sim_batch_form_rows", [])),
            base_batch_config,
            max_days,
        )
        if batch_errors:
            st.error("Batch config has issues:")
            for err in batch_errors:
                st.write(f"- {err}")
            st.caption("Batch tip: each JSON run item may override only the parameters you want to change; everything else falls back to the current UI values.")
        if batch_runs:
            summary_rows = []
            success_count = 0
            preflight_rows = []
            executable_batch = []
            for i, cfg in enumerate(batch_runs, start=1):
                try:
                    prepared_path, prepared_cfg, adapter_note = prepare_dataset_for_run(tmp_path, cfg)
                    ds_preflight = xr.open_dataset(prepared_path)
                    try:
                        sem_issues = validate_run_semantics(ds_preflight, prepared_cfg)
                    finally:
                        ds_preflight.close()
                except Exception as e:
                    sem_issues = [str(e)]
                    prepared_path, prepared_cfg, adapter_note = None, None, str(cfg.get("mesh_adapter", "none"))

                if sem_issues:
                    preflight_rows.append(
                        {
                            "Run": i,
                            "Name": cfg["name"],
                            "Preflight": "invalid",
                            "Reason": sem_issues[0],
                            "Mesh Adapter": adapter_note,
                            "Suggested Fix": " | ".join(get_actionable_error_guidance(" | ".join(sem_issues))),
                        }
                    )
                else:
                    preflight_rows.append(
                        {
                            "Run": i,
                            "Name": cfg["name"],
                            "Preflight": "ok",
                            "Reason": "",
                            "Mesh Adapter": adapter_note,
                            "Suggested Fix": "",
                        }
                    )
                    executable_batch.append((i, cfg, prepared_path, prepared_cfg, adapter_note))

            with st.expander("Batch Preflight Report", expanded=len(executable_batch) != len(batch_runs)):
                st.dataframe(pd.DataFrame(preflight_rows), width="stretch", hide_index=True)

            if not executable_batch:
                st.error("All batch runs failed preflight semantic checks. Fix mappings/config and retry.")
            with st.status(f"Running batch simulations ({len(executable_batch)} executable run(s))...", expanded=True) as status:
                global_progress = st.progress(0, text="Starting batch...")
                for done_idx, (i, cfg, prepared_path, prepared_cfg, adapter_note) in enumerate(executable_batch, start=1):
                    run_bar = st.progress(0, text=f"Run {i}/{len(batch_runs)} | {cfg['name']}: initializing")
                    run_started_ts = pd.Timestamp.now()
                    started_at = time.perf_counter()
                    cfg_signature = build_runtime_signature(
                        days=int(cfg["days"]),
                        particles=estimate_particle_count(cfg["mode"], int(cfg["particle_count"])),
                        mode=cfg["mode"],
                        backend=cfg["backend"],
                        dt_minutes=int(cfg["dt_minutes"]),
                        output_hours=int(cfg["output_hours"]),
                        release_mode=cfg["release_mode"],
                        repeat_release_hours=int(cfg["repeat_release_hours"]),
                        sample_velocity=bool(cfg["sample_velocity"]),
                    )
                    cfg_hint = estimate_runtime_hint(st.session_state, cfg_signature)
                    if cfg_hint is not None:
                        status.update(
                            label=(
                                f"Run {i}/{len(executable_batch)} | {cfg['name']} | "
                                f"expected ~{cfg_hint['median_seconds'] / 60:.1f} min (p75 {cfg_hint['p75_seconds'] / 60:.1f})"
                            ),
                            expanded=True,
                        )
                    else:
                        status.update(
                            label=f"Run {i}/{len(executable_batch)} | {cfg['name']} | no runtime history yet",
                            expanded=True,
                        )
                    if cfg_hint is not None:
                        st.caption(
                            f"Run {i} started at {str(run_started_ts)[:19]} | "
                            f"Expected (similar runs): median ~{cfg_hint['median_seconds'] / 60:.1f} min, "
                            f"p75 ~{cfg_hint['p75_seconds'] / 60:.1f} min."
                        )
                    else:
                        st.caption(f"Run {i} started at {str(run_started_ts)[:19]} | No similar runtime history yet.")
                    try:
                        run_output_path = build_run_output_path(f"batch_{i}")
                        # Use new API client instead of direct simulation_service call
                        batch_result = api_client.run_single(
                            prepared_path,
                            run_output_path,
                            prepared_cfg,
                            progress_callback=lambda pct, msg: _streamlit_progress_callback(run_bar, pct, msg),
                        )
                        if batch_result.status != RunStatus.SUCCEEDED:
                            raise RuntimeError(batch_result.error_message or "Batch simulation failed")
                        ZARR_PATH = batch_result.output_path
                        st.session_state["active_output_path"] = ZARR_PATH

                        elapsed = float(batch_result.elapsed_seconds)
                        run_started_ts = pd.Timestamp(batch_result.started_at_utc)
                        run_ended_ts = pd.Timestamp(batch_result.ended_at_utc)
                        run_id = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S_%f")
                        snapshot_path, snapshot_warning = snapshot_run_output(
                            ZARR_PATH,
                            f"batch_{run_id}_{i}",
                            ensure_runtime_paths,
                        )
                        zarr_mtime = os.path.getmtime(ZARR_PATH)
                        run_meta = get_zarr_metadata(ZARR_PATH, zarr_mtime)

                        save_run_history_entry(
                            st.session_state,
                            {
                                "label": f"{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')} | batch | {cfg['name']}",
                                "summary": (
                                    f"mode={cfg['mode']}, days={cfg['days']}, backend={cfg['backend']}, "
                                    f"u={cfg.get('u_var', st.session_state.get('sim_u_var', 'uo'))}, "
                                    f"v={cfg.get('v_var', st.session_state.get('sim_v_var', 'vo'))}, "
                                    f"lon={cfg.get('lon_coord', st.session_state.get('sim_lon_coord', 'longitude'))}, "
                                    f"lat={cfg.get('lat_coord', st.session_state.get('sim_lat_coord', 'latitude'))}, "
                                    f"time={cfg.get('time_coord', st.session_state.get('sim_time_coord', 'time'))}, "
                                    f"depth={cfg.get('depth_coord', st.session_state.get('sim_depth_coord', '')) or 'none'}, "
                                    f"count_override={cfg['particle_count']}, seed={cfg['seed']}, "
                                    f"dt={cfg['dt_minutes']} min, output={cfg['output_hours']} h, "
                                    f"release={cfg['release_mode']}"
                                ),
                                "snapshot_path": snapshot_path,
                                "config": {
                                    "sim_use_full": bool(cfg["days"] >= int(max_days)),
                                    "sim_days": int(cfg["days"]),
                                    "sim_particle_mode": cfg["mode"],
                                    "sim_particle_backend": cfg["backend"],
                                    "sim_u_var": cfg.get("u_var", st.session_state.get("sim_u_var", "uo")),
                                    "sim_v_var": cfg.get("v_var", st.session_state.get("sim_v_var", "vo")),
                                    "sim_lon_coord": cfg.get("lon_coord", st.session_state.get("sim_lon_coord", "longitude")),
                                    "sim_lat_coord": cfg.get("lat_coord", st.session_state.get("sim_lat_coord", "latitude")),
                                    "sim_time_coord": cfg.get("time_coord", st.session_state.get("sim_time_coord", "time")),
                                    "sim_depth_coord": cfg.get("depth_coord", st.session_state.get("sim_depth_coord", "")),
                                    "sim_particle_count_override": int(cfg["particle_count"]),
                                    "sim_random_seed": int(cfg["seed"]),
                                    "sim_dt_minutes": int(cfg["dt_minutes"]),
                                    "sim_output_hours": int(cfg["output_hours"]),
                                    "sim_release_mode": cfg["release_mode"],
                                    "sim_repeat_release_hours": int(cfg["repeat_release_hours"]),
                                    "sim_sample_velocity": bool(cfg["sample_velocity"]),
                                },
                            }
                        )

                        summary_rows.append(
                            {
                                "Run": i,
                                "Name": cfg["name"],
                                "Status": "success",
                                "Started_At": str(run_started_ts)[:19],
                                "Ended_At": str(run_ended_ts)[:19],
                                "Days": int(cfg["days"]),
                                "Mode": cfg["mode"],
                                "dt_min": int(cfg["dt_minutes"]),
                                "Output_h": int(cfg["output_hours"]),
                                "Mesh Adapter": adapter_note,
                                "Trajectories": int(run_meta["trajectory_count"]),
                                "Saved_Steps": int(run_meta["n_steps"]),
                                "Duration_s": round(float(elapsed), 2),
                                "Artifacts": int(len(batch_result.artifacts or [])),
                                "Warning": snapshot_warning or "",
                                "Suggested Fix": "",
                            }
                        )
                        record_runtime_stat(
                            st.session_state,
                            cfg_signature,
                            elapsed_seconds=float(elapsed),
                            started_at=run_started_ts,
                            ended_at=run_ended_ts,
                            status="success",
                        )
                        success_count += 1
                    except Exception as e:
                        elapsed = time.perf_counter() - started_at
                        run_ended_ts = pd.Timestamp.now()
                        summary_rows.append(
                            {
                                "Run": i,
                                "Name": cfg["name"],
                                "Status": "failed",
                                "Started_At": str(run_started_ts)[:19],
                                "Ended_At": str(run_ended_ts)[:19],
                                "Days": int(cfg["days"]),
                                "Mode": cfg["mode"],
                                "dt_min": int(cfg["dt_minutes"]),
                                "Output_h": int(cfg["output_hours"]),
                                "Mesh Adapter": adapter_note,
                                "Trajectories": None,
                                "Saved_Steps": None,
                                "Duration_s": round(float(elapsed), 2),
                                "Warning": str(e),
                                "Suggested Fix": " | ".join(get_actionable_error_guidance(str(e))),
                            }
                        )
                    finally:
                        global_progress.progress(
                            int((done_idx / max(1, len(executable_batch))) * 100),
                            text=f"Completed {done_idx}/{len(executable_batch)} executable runs",
                        )

                st.session_state["batch_last_summary"] = summary_rows
                st.subheader("Batch Run Summary")
                st.dataframe(pd.DataFrame(summary_rows), width="stretch")

                if success_count > 0:
                    status.update(
                        label=f"Batch completed: {success_count}/{len(executable_batch)} executable runs successful",
                        state="complete",
                        expanded=False,
                    )
                    st.success("Batch finished. Visualization now shows the latest successful run.")
                else:
                    status.update(
                        label="Batch failed: no successful runs",
                        state="error",
                        expanded=True,
                    )
                    st.error("No successful run in batch. Check the summary warnings table.")
    elif run_button and tmp_path is not None:
        # Using st.status to mimic the terminal logging behavior
        single_status_label = "Running Lagrangian Particle Tracking..."
        if runtime_hint is not None:
            single_status_label = (
                "Running Lagrangian Particle Tracking "
                f"(expected ~{runtime_hint['median_seconds'] / 60:.1f} min, "
                f"p75 {runtime_hint['p75_seconds'] / 60:.1f} min)..."
            )
        with st.status(
            single_status_label, expanded=True
        ) as status:
            if runtime_hint is not None:
                st.caption(
                    f"Expected duration (similar runs): median ~{runtime_hint['median_seconds'] / 60:.1f} min, "
                    f"p75 ~{runtime_hint['p75_seconds'] / 60:.1f} min."
                )
            else:
                st.caption("Expected duration: no similar runtime history yet for this profile.")
            my_bar = st.progress(0, text="Initializing simulation...")
            run_started_ts = pd.Timestamp.now()
            st.caption(f"Run started at: {str(run_started_ts)[:19]}")
            started_at = time.perf_counter()
            try:
                single_cfg = {
                    "u_var": st.session_state.get("sim_u_var", "uo"),
                    "v_var": st.session_state.get("sim_v_var", "vo"),
                    "lon_coord": st.session_state.get("sim_lon_coord", "longitude"),
                    "lat_coord": st.session_state.get("sim_lat_coord", "latitude"),
                    "time_coord": st.session_state.get("sim_time_coord", "time"),
                    "depth_coord": st.session_state.get("sim_depth_coord", ""),
                    "mesh_adapter": st.session_state.get("sim_mesh_adapter", "none"),
                }
                prepared_single_path, prepared_single_cfg, _single_adapter_note = prepare_dataset_for_run(tmp_path, single_cfg)
                run_output_path = build_run_output_path("single")
                single_run_cfg = build_single_run_config(
                    days,
                    particle_mode,
                    particle_count_override,
                    random_seed,
                    particle_backend,
                    dt_minutes,
                    output_hours,
                    release_mode,
                    repeat_release_hours,
                    sample_velocity,
                    st.session_state,
                    prepared_single_cfg,
                )
                # Use new API client instead of direct simulation_service call
                single_result = api_client.run_single(
                    prepared_single_path,
                    run_output_path,
                    single_run_cfg,
                    progress_callback=lambda pct, msg: _streamlit_progress_callback(my_bar, pct, msg),
                )
                if single_result.status != RunStatus.SUCCEEDED:
                    raise RuntimeError(single_result.error_message or "Simulation failed")
                ZARR_PATH = single_result.output_path
                st.session_state["active_output_path"] = ZARR_PATH
                elapsed = float(single_result.elapsed_seconds)
                run_started_ts = pd.Timestamp(single_result.started_at_utc)
                run_ended_ts = pd.Timestamp(single_result.ended_at_utc)

                status.update(
                    label="Success! Simulation Finished",
                    state="complete",
                    expanded=False,
                )
                render_single_run_success_info(runtime_hint, run_started_ts, run_ended_ts, elapsed)

                history_timestamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
                history_days = int(max_days) if use_full else int(days)
                run_id = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S_%f")
                snapshot_path, snapshot_warning = snapshot_run_output(
                    ZARR_PATH,
                    run_id,
                    ensure_runtime_paths,
                )
                history_config = {
                    "sim_use_full": bool(use_full),
                    "sim_days": history_days,
                    "sim_particle_mode": str(particle_mode),
                    "sim_particle_backend": str(particle_backend),
                    "sim_u_var": str(st.session_state.get("sim_u_var", "uo")),
                    "sim_v_var": str(st.session_state.get("sim_v_var", "vo")),
                    "sim_lon_coord": str(st.session_state.get("sim_lon_coord", "longitude")),
                    "sim_lat_coord": str(st.session_state.get("sim_lat_coord", "latitude")),
                    "sim_time_coord": str(st.session_state.get("sim_time_coord", "time")),
                    "sim_depth_coord": str(st.session_state.get("sim_depth_coord", "")),
                    "sim_mesh_adapter": str(st.session_state.get("sim_mesh_adapter", "none")),
                    "sim_particle_count_override": int(particle_count_override),
                    "sim_random_seed": int(random_seed),
                    "sim_dt_minutes": int(dt_minutes),
                    "sim_output_hours": int(output_hours),
                    "sim_release_mode": str(release_mode),
                    "sim_repeat_release_hours": int(repeat_release_hours),
                    "sim_sample_velocity": bool(sample_velocity),
                }
                save_run_history_entry(
                    st.session_state,
                    {
                        "label": f"{history_timestamp} | {particle_mode} | {history_days}d | {particle_backend}",
                        "summary": (
                            f"mode={particle_mode}, days={history_days}, backend={particle_backend}, "
                            f"u={st.session_state.get('sim_u_var', 'uo')}, v={st.session_state.get('sim_v_var', 'vo')}, "
                            f"lon={st.session_state.get('sim_lon_coord', 'longitude')}, lat={st.session_state.get('sim_lat_coord', 'latitude')}, "
                            f"time={st.session_state.get('sim_time_coord', 'time')}, depth={st.session_state.get('sim_depth_coord', '') or 'none'}, "
                            f"mesh_adapter={st.session_state.get('sim_mesh_adapter', 'none')}, "
                            f"count_override={int(particle_count_override)}, seed={int(random_seed)}, "
                            f"dt={int(dt_minutes)} min, output={int(output_hours)} h, release={release_mode}, "
                            f"artifacts={len(single_result.artifacts or [])}, "
                            f"started={str(run_started_ts)[:19]}, ended={str(run_ended_ts)[:19]}, elapsed={elapsed:.1f}s"
                        ),
                        "snapshot_path": snapshot_path,
                        "config": history_config,
                    }
                )
                record_runtime_stat(
                    st.session_state,
                    runtime_signature,
                    elapsed_seconds=float(elapsed),
                    started_at=run_started_ts,
                    ended_at=run_ended_ts,
                    status="success",
                )
                if snapshot_warning:
                    st.warning(snapshot_warning)
            except Exception as e:
                st.error(f"Simulation failed: {e}")
                with st.expander("Suggested Fixes", expanded=True):
                    for hint in get_actionable_error_guidance(str(e)):
                        st.write(f"- {hint}")
                status.update(label="Simulation Failed", state="error")

if valid_data and (len(st.session_state.get("run_history", [])) > 0 or not st.session_state.get("ux_first_run_mode", True)):
    st.divider()
    st.header("Run Management")
    render_run_history_and_comparison(
        st.session_state,
        max_days,
        restore_run_history_config,
        get_zarr_metadata,
        get_zarr_qc_summary,
        get_zarr_step_summary,
    )

# -----------------------------
# VISUALIZATION
# -----------------------------
st.divider()
st.header("Results Visualization")
if os.path.exists(ZARR_PATH):
    try:
        zarr_mtime = os.path.getmtime(ZARR_PATH)
        zarr_meta = get_zarr_metadata(ZARR_PATH, zarr_mtime)
        n_steps = zarr_meta["n_steps"]

        if n_steps > 1:
            st.header("3. Visualization Controls")

            if "viz_step" not in st.session_state or st.session_state.viz_step > n_steps - 1:
                st.session_state.viz_step = n_steps - 1
            st.session_state.setdefault(
                "viz_view_option",
                "Full Dataset Domain (Zoom Out)",
            )
            st.session_state.setdefault("viz_map_detail", "Balanced (50m)")
            st.session_state.setdefault("viz_show_station_labels", False)
            st.session_state.setdefault("viz_point_stride", 1)
            st.session_state.setdefault("viz_preset", "Custom")
            st.session_state.setdefault("viz_active_only", False)
            st.session_state.setdefault("viz_trajectory_cap", 0)
            st.session_state.setdefault("viz_traj_window_steps", 0)
            st.session_state.setdefault("viz_show_velocity_overlay", True if zarr_meta["has_sampled_speed"] else False)
            st.session_state.setdefault("viz_show_advanced_controls", False)
            st.session_state.setdefault("viz_confirm_high_memory_render", False)

            with st.form("visualization_controls"):
                st.selectbox(
                    "Visualization Preset",
                    ["Custom", "Fast Explore", "Publication Quality", "Station Focus"],
                    key="viz_preset",
                    help="Applies a curated set of map controls.",
                )
                view_option = st.radio(
                    "Map View Scope",
                    ["Focus on Particles (Zoom In)", "Full Dataset Domain (Zoom Out)"],
                    horizontal=True,
                    key="viz_view_option",
                )
                step = st.slider(
                    "Time Step (Hours since start)",
                    min_value=0,
                    max_value=n_steps - 1,
                    step=1,
                    key="viz_step",
                )
                st.checkbox(
                    "Show Advanced Visualization Controls",
                    key="viz_show_advanced_controls",
                    help="Reveal performance and rendering-tuning options.",
                )
                if st.session_state.get("viz_show_advanced_controls", False):
                    map_detail = st.select_slider(
                        "Map Detail",
                        options=["Fast (110m)", "Balanced (50m)", "Detailed (10m)"],
                        key="viz_map_detail",
                    )
                    point_stride = st.select_slider(
                        "Trajectory Point Thinning",
                        options=[1, 2, 3, 5, 10],
                        value=st.session_state.viz_point_stride,
                        help="Draw every Nth point to speed up map rendering. 1 keeps all points.",
                        key="viz_point_stride",
                    )
                    adv_col1, adv_col2, adv_col3 = st.columns(3)
                    with adv_col1:
                        active_only = st.checkbox(
                            "Active-Only Paths",
                            key="viz_active_only",
                            help="Draw only trajectories that are active at selected step.",
                        )
                    with adv_col2:
                        trajectory_cap = st.number_input(
                            "Trajectory Cap (0=all)",
                            min_value=0,
                            max_value=int(max(0, zarr_meta["trajectory_count"])),
                            step=50,
                            key="viz_trajectory_cap",
                        )
                    with adv_col3:
                        traj_window_steps = st.slider(
                            "Path Window (steps)",
                            min_value=0,
                            max_value=int(n_steps - 1),
                            key="viz_traj_window_steps",
                            help="0 draws full path up to selected step. N draws only last N steps.",
                        )
                    show_station_labels = st.checkbox(
                        "Show station labels",
                        help="Station text labels are expensive to render when many points are shown.",
                        key="viz_show_station_labels",
                    )
                    if zarr_meta["has_sampled_speed"]:
                        show_velocity_overlay = st.checkbox(
                            "Show Velocity Overlay",
                            value=True,
                            help="Color trajectories by speed (m/s). Requires velocity sampling enabled in simulation.",
                            key="viz_show_velocity_overlay",
                        )
                    else:
                        st.info("⚠ Velocity sampling not available. Re-run simulation with 'Sample Velocity' enabled.")
                else:
                    st.caption("Advanced visualization controls are hidden. Enable the toggle above to tune rendering details.")
                selected_station = "None"
                if stations_df is not None and not stations_df.empty:
                    selected_station = st.selectbox(
                        "Inspect Station",
                        options=["None"] + sorted(stations_df["StationName"].astype(str).unique().tolist()),
                        help="Highlights the selected station and shows its coordinates.",
                        key="viz_station_inspect",
                    )
                st.form_submit_button("Apply View", type="primary")

            view_option = st.session_state.viz_view_option
            step = st.session_state.viz_step
            map_detail = st.session_state.viz_map_detail
            point_stride = st.session_state.viz_point_stride
            active_only = st.session_state.viz_active_only
            trajectory_cap = int(st.session_state.viz_trajectory_cap)
            traj_window_steps = int(st.session_state.viz_traj_window_steps)
            show_station_labels = st.session_state.viz_show_station_labels
            show_velocity_overlay = st.session_state.get("viz_show_velocity_overlay", False)
            selected_station = st.session_state.get("viz_station_inspect", "None")

            preset_choice = st.session_state.get("viz_preset", "Custom")
            if preset_choice != "Custom":
                preset_state = apply_visualization_preset(
                    preset_choice,
                    {
                        "view_option": view_option,
                        "map_detail": map_detail,
                        "point_stride": point_stride,
                        "show_station_labels": show_station_labels,
                    }
                )
                view_option = preset_state["view_option"]
                map_detail = preset_state["map_detail"]
                point_stride = preset_state["point_stride"]
                show_station_labels = preset_state["show_station_labels"]

            if stations_df is not None and selected_station != "None":
                selected_rows = stations_df[stations_df["StationName"].astype(str) == selected_station]
                if not selected_rows.empty:
                    first_row = selected_rows.iloc[0]
                    caption_text = format_station_caption(selected_station, first_row)
                    st.caption(caption_text)

            viz_memory_risk = estimate_visualization_memory_risk(
                trajectory_count=zarr_meta["trajectory_count"],
                step=step,
                has_sampled_speed=zarr_meta["has_sampled_speed"],
            )
            proceed_with_render = render_visualization_memory_check(viz_memory_risk)
            if not proceed_with_render:
                st.stop()

            render_status = st.status("Rendering map...", expanded=True)
            render_progress = st.progress(0, text="Preparing trajectory arrays...")
            step_data = get_zarr_step_data(ZARR_PATH, zarr_mtime, step)
            qc_summary = get_zarr_qc_summary(ZARR_PATH, zarr_mtime, step)

            alive_mask = np.isfinite(step_data["final_lon"]) & np.isfinite(
                step_data["final_lat"]
            )
            render_progress.progress(15, text="Computing summary statistics...")
            alive_count = int(np.sum(alive_mask))
            total_particles = zarr_meta["trajectory_count"]
            alive_ratio = (
                (alive_count / total_particles) * 100 if total_particles > 0 else 0.0
            )

            st.subheader("QC Summary")
            qc1, qc2, qc3, qc4 = st.columns(4)
            with qc1:
                st.metric("Initially Released", qc_summary["initial_count"])
            with qc2:
                st.metric("Inactive/Lost at Step", qc_summary["current_lost"])
            with qc3:
                st.metric("Lost Ratio at Step", f"{qc_summary['current_lost_ratio']:.1f}%")
            with qc4:
                st.metric("Final Active at End", qc_summary["final_active"])

            qc5, qc6, qc7, qc8 = st.columns(4)
            with qc5:
                st.metric("Final Lost at End", qc_summary["final_lost"])
            with qc6:
                st.metric("Final Lost Ratio", f"{qc_summary['final_lost_ratio']:.1f}%")
            with qc7:
                st.metric("Current Survival", f"{alive_ratio:.1f}%")
            with qc8:
                st.metric("Current Inactive", total_particles - alive_count)

            analytics = None
            if stations_df is not None and not stations_df.empty:
                st.subheader("Station Analytics")
                station_radius_km = st.slider(
                    "Station Proximity Radius (km)",
                    min_value=1,
                    max_value=100,
                    value=10,
                    key="viz_station_radius_km",
                    help="Counts a trajectory as an entry when it is within this distance of a station.",
                )
                station_cols = ["StationName", "Lon", "Lat"]
                if "Group" in stations_df.columns:
                    station_cols.append("Group")
                stations_json = stations_df[station_cols].to_json(orient="records")
                analytics = get_station_analytics(
                    ZARR_PATH,
                    zarr_mtime,
                    stations_json,
                    int(step),
                    float(station_radius_km),
                )
                if analytics is not None:
                    if analytics.get("engine") == "cKDTree":
                        st.caption("Station analytics engine: cKDTree (optimized)")
                    else:
                        st.caption("Station analytics engine: Haversine fallback (SciPy not available)")
                    st.markdown("**Entries and First Arrivals**")
                    st.dataframe(analytics["station_metrics"], width="stretch")
                    st.markdown("**Station Connectivity Matrix (First -> Last touched)**")
                    st.dataframe(analytics["connectivity_matrix"], width="stretch")

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Trajectories", total_particles)
            with col2:
                st.metric("Active at Selected Step", alive_count)
            with col3:
                st.metric("Active Ratio", f"{alive_ratio:.1f}%")

            if zarr_meta["has_sampled_speed"] and step_data["speed_step"] is not None:
                speed_values = step_data["speed_step"]
                valid_speed = speed_values[np.isfinite(speed_values)]
                if valid_speed.size > 0:
                    col4, col5, col6 = st.columns(3)
                    with col4:
                        st.metric("Mean Speed", f"{valid_speed.mean():.4f}")
                    with col5:
                        st.metric("Max Speed", f"{valid_speed.max():.4f}")
                    with col6:
                        st.metric("Speed Samples", int(valid_speed.size))

            col_t1, col_t2, col_t3 = st.columns(3)
            with col_t1:
                try:
                    t_val = pd.Timestamp(step_data["current_time"])
                    current_time = str(t_val)[:19] if not pd.isna(t_val) else "N/A"
                except Exception:
                    current_time = "N/A"
                st.metric("Current Timestamp", current_time)
            with col_t2:
                st.metric("Elapsed", f"{step} h")
            with col_t3:
                st.metric("Remaining", f"{n_steps - 1 - step} h")

            qc_export = {
                "step": int(step),
                "current_time": current_time,
                "total_trajectories": int(total_particles),
                "active_at_selected_step": int(alive_count),
                "active_ratio_percent": round(float(alive_ratio), 4),
                **{
                    key: round(float(value), 4) if isinstance(value, float) else int(value)
                    for key, value in qc_summary.items()
                },
            }

            fig = plt.figure(figsize=(14, 9))
            ax = plt.axes(projection=ccrs.PlateCarree())
            render_progress.progress(30, text="Building base map layers...")
            _scale = {
                "Fast (110m)": "110m",
                "Balanced (50m)": "50m",
                "Detailed (10m)": "10m",
            }[map_detail]
            ax.add_feature(cfeature.COASTLINE.with_scale(_scale), linewidth=1)
            ax.add_feature(
                cfeature.LAND.with_scale(_scale), facecolor="#f0f0f0", edgecolor="black"
            )
            ax.add_feature(cfeature.STATES.with_scale(_scale), linestyle=":", alpha=0.5)
            gl = ax.gridlines(draw_labels=True, linewidth=0.5, color="gray", alpha=0.5, linestyle="--")
            gl.top_labels = False
            gl.right_labels = False
            ax.set_title(
                f"Particle Trajectories — t={step}h / {n_steps - 1}h",
                fontsize=12,
                pad=10,
            )

            # -----------------------------
            # EXTENT CALCULATION (ZOOM LOGIC)
            # -----------------------------
            render_progress.progress(45, text="Calculating map extent...")
            if view_option == "Focus on Particles (Zoom In)":
                particle_extent = get_zarr_particle_extent(ZARR_PATH, zarr_mtime)
                if all(np.isfinite(v) for v in particle_extent):
                    ax.set_extent(
                        list(particle_extent),
                        crs=ccrs.PlateCarree(),
                    )
            else:
                # Zoom Out: Use the original NetCDF domain boundaries
                if tmp_path and os.path.exists(tmp_path):
                    domain_extent = get_netcdf_domain_extent(
                        tmp_path,
                        os.path.getmtime(tmp_path),
                        st.session_state.get("sim_lon_coord", "longitude"),
                        st.session_state.get("sim_lat_coord", "latitude"),
                    )
                    ax.set_extent(list(domain_extent), crs=ccrs.PlateCarree())
            # -----------------------------
            # PLOTTING TRAJECTORIES
            # -----------------------------
            render_progress.progress(55, text="Rendering trajectories...")
            segments = []
            traj_lon = step_data["traj_lon"]
            traj_lat = step_data["traj_lat"]
            total_trajectories = total_particles
            candidate_indices = np.arange(total_trajectories, dtype=int)
            if active_only:
                candidate_indices = candidate_indices[alive_mask]
            if trajectory_cap > 0:
                candidate_indices = candidate_indices[:trajectory_cap]
            plotted_target = int(len(candidate_indices))
            st.caption(
                f"Rendering {plotted_target} of {total_trajectories} trajectories "
                f"(active_only={active_only}, cap={trajectory_cap if trajectory_cap > 0 else 'all'}, "
                f"window_steps={traj_window_steps if traj_window_steps > 0 else 'full'})."
            )

            progress_stride = max(1, plotted_target // 20) if plotted_target > 0 else 1
            for j, i in enumerate(candidate_indices):
                lon_vals = traj_lon[i]
                lat_vals = traj_lat[i]
                mask = np.isfinite(lon_vals) & np.isfinite(lat_vals)
                if np.sum(mask) < 2:
                    if j % progress_stride == 0 or j == plotted_target - 1:
                        pct = 55 + int(20 * (j + 1) / max(1, plotted_target))
                        render_progress.progress(min(pct, 75), text=f"Rendering trajectories... {j + 1}/{plotted_target}")
                    continue

                clean_lon = lon_vals[mask]
                clean_lat = lat_vals[mask]
                if traj_window_steps > 0 and clean_lon.size > (traj_window_steps + 1):
                    clean_lon = clean_lon[-(traj_window_steps + 1):]
                    clean_lat = clean_lat[-(traj_window_steps + 1):]
                if point_stride > 1:
                    clean_lon = clean_lon[::point_stride]
                    clean_lat = clean_lat[::point_stride]
                    if clean_lon[-1] != lon_vals[mask][-1] or clean_lat[-1] != lat_vals[mask][-1]:
                        clean_lon = np.append(clean_lon, lon_vals[mask][-1])
                        clean_lat = np.append(clean_lat, lat_vals[mask][-1])
                if clean_lon.size < 2:
                    continue
                segments.append(np.column_stack((clean_lon, clean_lat)))
                if j % progress_stride == 0 or j == plotted_target - 1:
                    pct = 55 + int(20 * (j + 1) / max(1, plotted_target))
                    render_progress.progress(min(pct, 75), text=f"Rendering trajectories... {j + 1}/{plotted_target}")

            _VIZ_CMAP = "plasma"

            # Pre-compute shared speed range when overlay is active so both
            # trajectories and final-position dots share an identical scale.
            _shared_vmin = None
            _shared_vmax = None
            if show_velocity_overlay and zarr_meta["has_sampled_speed"] and step_data["speed_traj"] is not None:
                _all_speeds = []
                speed_traj = step_data["speed_traj"]
                for _ci in candidate_indices:
                    _sv = speed_traj[_ci]
                    _all_speeds.extend(_sv[np.isfinite(_sv)])
                if step_data["speed_step"] is not None:
                    _ss = step_data["speed_step"]
                    _all_speeds.extend(_ss[np.isfinite(_ss)])
                if _all_speeds:
                    _arr = np.array(_all_speeds)
                    _shared_vmin, _shared_vmax = float(np.nanpercentile(_arr, 5)), float(np.nanpercentile(_arr, 95))
                    if _shared_vmin == _shared_vmax:
                        _shared_vmax = _shared_vmin + 1e-6

            if segments:
                if show_velocity_overlay and zarr_meta["has_sampled_speed"] and step_data["speed_traj"] is not None and _shared_vmin is not None:
                    render_progress.progress(60, text="Coloring trajectories by speed...")
                    cmap = matplotlib.colormaps[_VIZ_CMAP]
                    segment_colors = []
                    for i, seg in enumerate(segments):
                        idx = candidate_indices[i]
                        seg_speeds = speed_traj[idx][:-1] if speed_traj[idx].size > 0 else np.array([])
                        if seg_speeds.size > 0 and np.any(np.isfinite(seg_speeds)):
                            norm_speeds = np.clip((seg_speeds - _shared_vmin) / (_shared_vmax - _shared_vmin), 0, 1)
                            colors = [cmap(float(s)) if np.isfinite(s) else (0, 0, 0, 0.1) for s in norm_speeds]
                            segment_colors.append(colors)
                        else:
                            segment_colors.append([(0.3, 0.3, 0.3, 0.2)] * max(1, seg.shape[0] - 1))

                    lc = LineCollection(segments, linewidths=0.8, transform=ccrs.PlateCarree())
                    lc.set_segments(segments)
                    lc.set_colors([c for colors in segment_colors for c in colors])
                    ax.add_collection(lc)
                else:
                    lc = LineCollection(
                        segments,
                        colors="steelblue",
                        alpha=0.35,
                        linewidths=0.8,
                        transform=ccrs.PlateCarree(),
                    )
                    ax.add_collection(lc)

            # Final positions — colored by speed if available
            render_progress.progress(82, text="Plotting final particle positions...")
            _final_lons = step_data["final_lon"]
            _final_lats = step_data["final_lat"]
            _alive = np.isfinite(_final_lons) & np.isfinite(_final_lats)
            if np.any(_alive):
                if zarr_meta["has_sampled_speed"] and step_data["speed_step"] is not None:
                    _spd = step_data["speed_step"][_alive]
                    _valid_spd = np.isfinite(_spd)
                    if np.any(_valid_spd):
                        # Use shared scale when overlay is on, independent scale otherwise
                        _sc_vmin = _shared_vmin if _shared_vmin is not None else float(np.nanpercentile(_spd[_valid_spd], 5))
                        _sc_vmax = _shared_vmax if _shared_vmax is not None else float(np.nanpercentile(_spd[_valid_spd], 95))
                        _sc = ax.scatter(
                            _final_lons[_alive],
                            _final_lats[_alive],
                            c=np.where(_valid_spd, _spd, np.nan),
                            cmap=_VIZ_CMAP,
                            s=18,
                            transform=ccrs.PlateCarree(),
                            zorder=5,
                            vmin=_sc_vmin,
                            vmax=_sc_vmax,
                        )
                        # Only draw a colorbar here when overlay is off;
                        # when overlay is on, the shared colorbar is added below.
                        if not (show_velocity_overlay and _shared_vmin is not None):
                            plt.colorbar(_sc, ax=ax, label="Speed (m/s)", fraction=0.02, pad=0.04)
                    else:
                        ax.scatter(
                            _final_lons[_alive], _final_lats[_alive],
                            color="red", s=10, transform=ccrs.PlateCarree(), zorder=5,
                        )
                else:
                    ax.scatter(
                        _final_lons[_alive], _final_lats[_alive],
                        color="red", s=10, transform=ccrs.PlateCarree(), zorder=5,
                    )

            # Single shared colorbar when velocity overlay is active
            if show_velocity_overlay and _shared_vmin is not None:
                _sm = matplotlib.cm.ScalarMappable(
                    cmap=_VIZ_CMAP,
                    norm=matplotlib.colors.Normalize(vmin=_shared_vmin, vmax=_shared_vmax),
                )
                _sm.set_array([])
                plt.colorbar(_sm, ax=ax, label="Speed (m/s)", fraction=0.02, pad=0.04)

            # -----------------------------
            # PLOT STATIONS (ADDITION)
            # -----------------------------
            render_progress.progress(90, text="Adding station overlays...")
            if stations_df is not None:
                has_group = "Group" in stations_df.columns
                marker_cycle = ["o", "^", "s", "D", "P", "X", "v", "<", ">", "*"]
                color_cycle = [
                    "deepskyblue",
                    "magenta",
                    "green",
                    "orange",
                    "gold",
                    "crimson",
                    "teal",
                    "slateblue",
                    "brown",
                    "black",
                ]
                group_styles = {}
                for _, row in stations_df.iterrows():
                    if has_group:
                        group_name = str(row["Group"]).strip() or "Ungrouped"
                        if group_name not in group_styles:
                            idx = len(group_styles)
                            group_styles[group_name] = (
                                marker_cycle[idx % len(marker_cycle)],
                                color_cycle[idx % len(color_cycle)],
                            )
                        m_style, m_color = group_styles[group_name]
                        m_label = group_name
                    else:
                        m_style, m_color, m_label = "o", "deepskyblue", "Station"

                    ax.scatter(
                        row["Lon"],
                        row["Lat"],
                        color=m_color,
                        marker=m_style,
                        s=130 if str(row["StationName"]) == selected_station else 80,
                        edgecolors="white",
                        linewidths=2 if str(row["StationName"]) == selected_station else 0.8,
                        transform=ccrs.PlateCarree(),
                        zorder=12 if str(row["StationName"]) == selected_station else 10,
                        label=m_label,
                    )
                    if show_station_labels:
                        ax.text(
                            row["Lon"] + 0.005,
                            row["Lat"] + 0.005,
                            str(row["StationName"]).strip(),
                            transform=ccrs.PlateCarree(),
                            fontsize=8,
                            fontweight="bold",
                            bbox=dict(
                                facecolor="white", alpha=0.5, edgecolor="none", pad=1
                            ),
                        )
                    if str(row["StationName"]) == selected_station:
                        ax.text(
                            row["Lon"] + 0.007,
                            row["Lat"] + 0.007,
                            f"{row['StationName']}",
                            transform=ccrs.PlateCarree(),
                            fontsize=9,
                            fontweight="bold",
                            color="black",
                            bbox=dict(facecolor="yellow", alpha=0.5, edgecolor="black", pad=1),
                            zorder=20,
                        )

                handles, labels = ax.get_legend_handles_labels()
                by_label = dict(zip(labels, handles))
                if by_label:
                    ax.legend(by_label.values(), by_label.keys(), loc="lower right")

            st.pyplot(fig, width="stretch")
            render_progress.progress(100, text="Map render completed.")
            render_status.update(
                label="Map is ready",
                state="complete",
                expanded=False,
            )

            # -----------------------------
            # MAP DOWNLOAD
            # -----------------------------
            _scope_tag = "zoom" if "Zoom In" in view_option else "full"
            _mode_tag = particle_mode if valid_data else "unknown"
            _days_tag = f"{days}d" if valid_data else "nd"
            _step_tag = f"step{step}h"
            _map_filename = (
                f"lpt_{_mode_tag}_{_days_tag}_{_scope_tag}_{_step_tag}.png"
            )
            _buf = io.BytesIO()
            fig.savefig(_buf, format="png", dpi=150, bbox_inches="tight")
            _buf.seek(0)

            # Trajectory data download (CSV)
            csv_content = None
            traj_geojson = None
            station_geojson = None
            try:
                traj_records = build_trajectory_csv_records(traj_lon, traj_lat, step_data)
                if traj_records:
                    csv_content = pd.DataFrame(traj_records).to_csv(index=False)

                traj_geojson = build_trajectory_geojson(
                    traj_lon,
                    traj_lat,
                    candidate_indices,
                    traj_window_steps=traj_window_steps,
                    point_stride=point_stride,
                )

                if analytics is not None:
                    station_geojson = build_station_metrics_geojson(
                        stations_df,
                        analytics.get("station_metrics"),
                    )
            except Exception as _e:
                st.warning(f"CSV export unavailable: {_e}")

            bundle_params = {
                "particle_mode": particle_mode,
                "days": days,
                "step": step,
                "u_var": st.session_state.get("sim_u_var", "uo"),
                "v_var": st.session_state.get("sim_v_var", "vo"),
                "lon_coord": st.session_state.get("sim_lon_coord", "longitude"),
                "lat_coord": st.session_state.get("sim_lat_coord", "latitude"),
                "time_coord": st.session_state.get("sim_time_coord", "time"),
                "depth_coord": st.session_state.get("sim_depth_coord", ""),
                "mesh_adapter": st.session_state.get("sim_mesh_adapter", "none"),
                "view_option": view_option,
                "map_detail": map_detail,
                "point_stride": point_stride,
                "show_station_labels": show_station_labels,
                "selected_station": selected_station,
                "backend": particle_backend,
                "dt_minutes": dt_minutes,
                "output_hours": output_hours,
                "release_mode": release_mode,
                "repeat_release_hours": repeat_release_hours if release_mode == "repeated" else None,
                "sample_velocity": sample_velocity,
            }
            bundle_name = f"lpt_bundle_{_mode_tag}_{_days_tag}_{_step_tag}.zip"
            bundle_buffer = io.BytesIO()
            with zipfile.ZipFile(bundle_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(_map_filename, _buf.getvalue())
                if csv_content is not None:
                    zf.writestr(
                        f"lpt_trajectories_{_mode_tag}_{_days_tag}_{_step_tag}.csv",
                        csv_content,
                    )
                if traj_geojson is not None:
                    zf.writestr(
                        f"lpt_trajectories_{_mode_tag}_{_days_tag}_{_step_tag}.geojson",
                        json.dumps(traj_geojson, indent=2),
                    )
                if station_geojson is not None:
                    zf.writestr(
                        f"lpt_station_metrics_{_mode_tag}_{_days_tag}_{_step_tag}.geojson",
                        json.dumps(station_geojson, indent=2),
                    )
                zf.writestr("qc_summary.json", json.dumps(qc_export, indent=2))
                zf.writestr("run_params.json", json.dumps(bundle_params, indent=2))
            bundle_buffer.seek(0)

            # Export action bar
            # Keep future buttons in this grouped layout for consistency.
            st.markdown("### Export Actions")
            exp_col1, exp_col2, exp_col3, exp_col4, exp_col5, exp_col6 = st.columns(6)
            with exp_col1:
                st.download_button(
                    label="🖼 PNG Map",
                    data=_buf,
                    file_name=_map_filename,
                    mime="image/png",
                    width='stretch',
                )
            with exp_col2:
                st.download_button(
                    label="📈 QC JSON",
                    data=json.dumps(qc_export, indent=2),
                    file_name=f"lpt_qc_summary_step{step}h.json",
                    mime="application/json",
                    width='stretch',
                )
            with exp_col3:
                st.download_button(
                    label="🧭 Trajectory CSV",
                    data=csv_content if csv_content is not None else "",
                    file_name=f"lpt_trajectories_{_mode_tag}_{_days_tag}_{_step_tag}.csv",
                    mime="text/csv",
                    disabled=csv_content is None,
                    width='stretch',
                )
            with exp_col4:
                st.download_button(
                    label="📦 Export Bundle",
                    data=bundle_buffer.getvalue(),
                    file_name=bundle_name,
                    mime="application/zip",
                    width='stretch',
                )
            with exp_col5:
                st.download_button(
                    label="🗺 Trajectory GeoJSON",
                    data=json.dumps(traj_geojson, indent=2) if traj_geojson is not None else "",
                    file_name=f"lpt_trajectories_{_mode_tag}_{_days_tag}_{_step_tag}.geojson",
                    mime="application/geo+json",
                    disabled=traj_geojson is None,
                    width='stretch',
                )
            with exp_col6:
                st.download_button(
                    label="📍 Station GeoJSON",
                    data=json.dumps(station_geojson, indent=2) if station_geojson is not None else "",
                    file_name=f"lpt_station_metrics_{_mode_tag}_{_days_tag}_{_step_tag}.geojson",
                    mime="application/geo+json",
                    disabled=station_geojson is None,
                    width='stretch',
                )
            plt.close(fig)
        else:
            st.warning("Only initial state exists. Simulation steps were not recorded.")

    except Exception as e:
        st.error(f"Display error: {e}")
else:
    if uploaded_file is None:
        st.info("Upload a file and run simulation to see results.")
    elif not valid_data:
        st.info("Ensure valid NetCDF is uploaded to begin.")
