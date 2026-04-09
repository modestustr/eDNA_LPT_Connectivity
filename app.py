import streamlit as st
import xarray as xr
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.colors
import matplotlib.cm
from matplotlib.collections import LineCollection
import cartopy
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import os
import parcels
import numpy as np
import pandas as pd
import inspect
import io
import json
import zipfile
import shutil
import time
import uuid
import hashlib
import core_lpt

try:
    from scipy.spatial import cKDTree
except Exception:
    cKDTree = None

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
RUNS_ROOT = os.path.join(APP_ROOT, "runs")
SESSION_RETENTION_HOURS = 72


def cleanup_stale_runtime_sessions(current_session_id, max_age_hours=SESSION_RETENTION_HOURS):
    """Remove stale session runtime folders to avoid unbounded disk growth."""
    if not os.path.isdir(RUNS_ROOT):
        return 0
    now_ts = time.time()
    removed = 0
    for name in os.listdir(RUNS_ROOT):
        path = os.path.join(RUNS_ROOT, name)
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


def ensure_runtime_paths():
    """Create and return session-scoped runtime directories.

    Isolating uploads, outputs, and snapshots per Streamlit session prevents
    path collisions when multiple tabs/users run simulations concurrently.
    """
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = uuid.uuid4().hex[:8]

    if "runtime_cleanup_done" not in st.session_state:
        removed = cleanup_stale_runtime_sessions(st.session_state["session_id"])
        st.session_state["runtime_cleanup_done"] = True
        st.session_state["runtime_cleanup_removed"] = int(removed)

    session_root = os.path.join(RUNS_ROOT, st.session_state["session_id"])
    upload_cache_dir = os.path.join(session_root, "upload_cache")
    outputs_dir = os.path.join(session_root, "outputs")
    snapshots_dir = os.path.join(session_root, "snapshots")

    for path in [RUNS_ROOT, session_root, upload_cache_dir, outputs_dir, snapshots_dir]:
        os.makedirs(path, exist_ok=True)

    return {
        "session_root": session_root,
        "upload_cache_dir": upload_cache_dir,
        "outputs_dir": outputs_dir,
        "snapshots_dir": snapshots_dir,
    }


def build_run_output_path(run_prefix="run"):
    """Return a unique session-scoped Zarr output path for a simulation run."""
    runtime = ensure_runtime_paths()
    run_token = f"{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S_%f')}_{uuid.uuid4().hex[:6]}"
    safe_prefix = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(run_prefix))
    return os.path.join(runtime["outputs_dir"], f"{safe_prefix}_{run_token}.zarr")


def _flattened_grid_transform(data_array, node_dim, y_idx, x_idx, ny, nx, lat_dim_name, lon_dim_name):
    """Remap a (.., node_dim) field onto (.., lat, lon) using precomputed indices."""
    prefix_dims = [d for d in data_array.dims if d != node_dim]
    transposed = data_array.transpose(*prefix_dims, node_dim)
    arr = transposed.values
    node_len = arr.shape[-1]
    flat = arr.reshape((-1, node_len))
    out = np.full((flat.shape[0], ny, nx), np.nan, dtype=np.float32)
    out[:, y_idx, x_idx] = flat.astype(np.float32)
    out_shape = tuple(arr.shape[:-1]) + (ny, nx)
    out = out.reshape(out_shape)
    out_dims = tuple(prefix_dims + [lat_dim_name, lon_dim_name])
    return out, out_dims, prefix_dims


def adapt_dataset_flattened_grid_1d(file_path, run_cfg):
    """Adapt 1D flattened mesh data (time,node) into regular (time,lat,lon) grid.

    Supported family: datasets where lon/lat are 1D node coordinates and U/V
    are provided on the same node dimension, representing a flattened regular
    grid. Raises ValueError for incompatible mesh layouts.
    """
    runtime = ensure_runtime_paths()
    adapters_dir = os.path.join(runtime["session_root"], "adapters")
    os.makedirs(adapters_dir, exist_ok=True)

    u_var = str(run_cfg.get("u_var", "")).strip()
    v_var = str(run_cfg.get("v_var", "")).strip()
    lon_coord = str(run_cfg.get("lon_coord", "")).strip()
    lat_coord = str(run_cfg.get("lat_coord", "")).strip()

    if not all([u_var, v_var, lon_coord, lat_coord]):
        raise ValueError("flattened_grid_1d adapter requires u_var, v_var, lon_coord, and lat_coord.")

    cache_key = json.dumps(
        {
            "file": os.path.abspath(file_path),
            "u": u_var,
            "v": v_var,
            "lon": lon_coord,
            "lat": lat_coord,
            "time": str(run_cfg.get("time_coord", "")),
            "depth": str(run_cfg.get("depth_coord", "")),
            "adapter": "flattened_grid_1d",
        },
        sort_keys=True,
    )
    cache_hash = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()[:14]
    adapted_path = os.path.join(adapters_dir, f"adapt_flat_{cache_hash}.nc")
    if os.path.exists(adapted_path):
        prepared_cfg = dict(run_cfg)
        prepared_cfg["lon_coord"] = "adapted_lon"
        prepared_cfg["lat_coord"] = "adapted_lat"
        return adapted_path, prepared_cfg, "flattened_grid_1d"

    ds = xr.open_dataset(file_path)
    try:
        if u_var not in ds.data_vars or v_var not in ds.data_vars:
            raise ValueError("Selected U/V variables do not exist for mesh adaptation.")
        if lon_coord not in ds.variables or lat_coord not in ds.variables:
            raise ValueError("Selected lon/lat coordinates do not exist for mesh adaptation.")
        if ds[lon_coord].ndim != 1 or ds[lat_coord].ndim != 1:
            raise ValueError("flattened_grid_1d adapter expects 1D lon/lat node coordinates.")

        node_dim = ds[lon_coord].dims[0]
        if ds[lat_coord].dims[0] != node_dim:
            raise ValueError("Lon/lat coordinates must share the same node dimension for flattened_grid_1d adapter.")
        if node_dim not in ds[u_var].dims or node_dim not in ds[v_var].dims:
            raise ValueError("Selected U/V fields are not defined on the detected node dimension.")

        lon_vals = np.asarray(ds[lon_coord].values)
        lat_vals = np.asarray(ds[lat_coord].values)
        valid_nodes = np.isfinite(lon_vals) & np.isfinite(lat_vals)
        if not np.any(valid_nodes):
            raise ValueError("No finite lon/lat nodes found for flattened_grid_1d adapter.")

        lon_nodes = lon_vals[valid_nodes]
        lat_nodes = lat_vals[valid_nodes]
        unique_lon = np.unique(lon_nodes)
        unique_lat = np.unique(lat_nodes)
        if unique_lon.size * unique_lat.size != lon_nodes.size:
            raise ValueError(
                "Node coordinates do not form a full flattened regular grid. "
                "Use adapter='none' or provide a different mesh adapter."
            )

        x_idx = np.searchsorted(unique_lon, lon_nodes)
        y_idx = np.searchsorted(unique_lat, lat_nodes)
        pair_count = np.unique(np.stack([y_idx, x_idx], axis=1), axis=0).shape[0]
        if pair_count != lon_nodes.size:
            raise ValueError("Duplicate node coordinate pairs detected; flattened_grid_1d adapter cannot reshape safely.")

        ny = int(unique_lat.size)
        nx = int(unique_lon.size)
        lat_dim_name = "adapted_lat"
        lon_dim_name = "adapted_lon"

        u_valid = ds[u_var].isel({node_dim: np.where(valid_nodes)[0]})
        v_valid = ds[v_var].isel({node_dim: np.where(valid_nodes)[0]})
        u_out, u_dims, prefix_dims = _flattened_grid_transform(u_valid, node_dim, y_idx, x_idx, ny, nx, lat_dim_name, lon_dim_name)
        v_out, v_dims, _ = _flattened_grid_transform(v_valid, node_dim, y_idx, x_idx, ny, nx, lat_dim_name, lon_dim_name)

        coords = {
            lon_dim_name: (lon_dim_name, unique_lon.astype(np.float64)),
            lat_dim_name: (lat_dim_name, unique_lat.astype(np.float64)),
        }
        for dim in prefix_dims:
            if dim in ds.coords:
                coords[dim] = ds.coords[dim]

        ds_out = xr.Dataset(
            {
                u_var: xr.DataArray(u_out, dims=u_dims),
                v_var: xr.DataArray(v_out, dims=v_dims),
            },
            coords=coords,
        )
        ds_out.to_netcdf(adapted_path)
        ds_out.close()
    finally:
        ds.close()

    prepared_cfg = dict(run_cfg)
    prepared_cfg["lon_coord"] = "adapted_lon"
    prepared_cfg["lat_coord"] = "adapted_lat"
    return adapted_path, prepared_cfg, "flattened_grid_1d"


def prepare_dataset_for_run(file_path, run_cfg):
    """Return (prepared_path, prepared_cfg, adapter_note) for a run config."""
    adapter = str(run_cfg.get("mesh_adapter", "none") or "none").strip().lower()
    if adapter in {"", "none"}:
        return file_path, dict(run_cfg), "none"
    if adapter == "flattened_grid_1d":
        return adapt_dataset_flattened_grid_1d(file_path, run_cfg)
    raise ValueError(f"Unsupported mesh_adapter '{adapter}'.")

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


def _safe_close_dataset(ds):
    """Safely close an xarray Dataset, suppressing AttributeError if the object
    does not expose a callable 'close' method (e.g., already GC-collected).

    Using explicit close is recommended when loading from Zarr stores to
    release file handles and prevent memory leaks in long-running Streamlit
    sessions.
    """
    close_method = getattr(ds, "close", None)
    if callable(close_method):
        close_method()


@st.cache_data(show_spinner=False)
def load_markdown_file(file_path):
    """Load a Markdown file for in-app Help / How To rendering.

    The README is rendered directly inside the Streamlit UI so the app remains
    self-documenting.  Cached because the file content is static during normal
    use and should not be re-read on every rerun.
    """
    resolved_path = file_path
    if not os.path.isabs(resolved_path):
        resolved_path = os.path.join(APP_ROOT, resolved_path)
    try:
        with open(resolved_path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        return f"## Help Unavailable\n\nCould not load `{resolved_path}`.\n\nReason: {e}"


def parse_markdown_sections(markdown_text):
    """Split Markdown into a preface block and top-level sections by `##` headings.

    This is used to render long help documents as a compact set of Streamlit
    expanders so the UI remains readable on smaller screens.
    """
    lines = str(markdown_text or "").splitlines()
    preface_lines = []
    sections = []
    current_title = None
    current_lines = []

    for line in lines:
        if line.startswith("## "):
            if current_title is not None:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line[3:].strip()
            current_lines = []
        else:
            if current_title is None:
                preface_lines.append(line)
            else:
                current_lines.append(line)

    if current_title is not None:
        sections.append((current_title, "\n".join(current_lines).strip()))

    return "\n".join(preface_lines).strip(), sections


def render_markdown_as_expanders(markdown_text, expand_first=True, expand_all_override=None):
    """Render a Markdown document as a compact intro block plus expanders.

    If expand_all_override is set, it controls global expansion behavior for
    all sections in that document:
        True  -> expand all
        False -> collapse all
        None  -> use expand_first behavior
    """
    preface, sections = parse_markdown_sections(markdown_text)
    if preface:
        st.markdown(preface)
    render_sections_as_expanders(sections, expand_first=expand_first, expand_all_override=expand_all_override)


def render_sections_as_expanders(sections, expand_first=True, expand_all_override=None):
    """Render already parsed markdown sections as expanders."""
    if not sections:
        return
    for idx, (title, body) in enumerate(sections):
        if expand_all_override is True:
            expanded = True
        elif expand_all_override is False:
            expanded = False
        else:
            expanded = bool(expand_first and idx == 0)
        with st.expander(title, expanded=expanded):
            if body:
                st.markdown(body)


def _name_exists_in_dataset(ds, name):
    return bool(name) and (name in ds.variables or name in ds.dims)


def _infer_extra_velocity_dims(ds, u_var, lon_coord, lat_coord, time_coord):
    if u_var not in ds.variables:
        return []
    u_dims = list(ds[u_var].dims)
    known_dims = set()
    for axis_name in [lon_coord, lat_coord, time_coord]:
        if axis_name in ds.variables:
            known_dims.update(ds[axis_name].dims)
            if axis_name in ds.dims:
                known_dims.add(axis_name)
        elif axis_name in ds.dims:
            known_dims.add(axis_name)
    return [dim for dim in u_dims if dim not in known_dims]


def validate_dataset_structure(ds, u_var, v_var, lon_coord, lat_coord, time_coord, depth_coord):
    """Validate that selected variables/axes are structurally compatible.

    This goes beyond name existence and checks whether the selected fields can
    plausibly form an OceanParcels FieldSet.
    """
    issues = []
    if u_var not in ds.variables or v_var not in ds.variables:
        return ["Selected U/V variables do not exist in the dataset."]

    u_dims = tuple(ds[u_var].dims)
    v_dims = tuple(ds[v_var].dims)
    if u_dims != v_dims:
        issues.append(f"U and V dimensions differ: U{u_dims} vs V{v_dims}.")

    if not _name_exists_in_dataset(ds, time_coord):
        issues.append(f"Time coordinate '{time_coord or 'not selected'}' does not exist.")
    else:
        time_dims = tuple(ds[time_coord].dims) if time_coord in ds.variables else (time_coord,)
        if time_coord not in u_dims and not set(time_dims).issubset(set(u_dims)):
            issues.append(f"Time coordinate '{time_coord}' is not aligned with U/V dimensions {u_dims}.")

    for axis_name, axis_label in [(lon_coord, "Longitude"), (lat_coord, "Latitude")]:
        if not _name_exists_in_dataset(ds, axis_name):
            issues.append(f"{axis_label} axis '{axis_name or 'not selected'}' does not exist.")
            continue
        axis_dims = tuple(ds[axis_name].dims) if axis_name in ds.variables else (axis_name,)
        if axis_name in ds.variables and ds[axis_name].ndim == 0:
            issues.append(f"{axis_label} axis '{axis_name}' is scalar; expected 1D or 2D coordinates.")
        elif not set(axis_dims).issubset(set(u_dims)) and axis_name not in u_dims:
            issues.append(f"{axis_label} axis '{axis_name}' dims {axis_dims} are not compatible with U/V dims {u_dims}.")

    extra_dims = _infer_extra_velocity_dims(ds, u_var, lon_coord, lat_coord, time_coord)
    if depth_coord:
        if not _name_exists_in_dataset(ds, depth_coord):
            issues.append(f"Depth coordinate '{depth_coord}' does not exist.")
        else:
            depth_dims = tuple(ds[depth_coord].dims) if depth_coord in ds.variables else (depth_coord,)
            if not set(depth_dims).issubset(set(u_dims)) and depth_coord not in u_dims:
                issues.append(f"Depth coordinate '{depth_coord}' dims {depth_dims} are not compatible with U/V dims {u_dims}.")
    elif len(extra_dims) > 0:
        issues.append(
            f"Velocity fields contain additional dimension(s) {tuple(extra_dims)}. "
            "Choose a depth coordinate if one of these represents the vertical axis."
        )

    return issues


def build_dataset_readiness_report(ds, u_var, v_var, lon_coord, lat_coord, time_coord, depth_coord):
    """Build a compact compatibility checklist for the currently uploaded dataset.

    This is part of UX hardening: rather than only saying a file is invalid,
    the app shows exactly which required elements are present or missing and
    what the user needs to map or fix.
    """
    checks = []
    issues = []

    def add_check(label, ok, detail):
        checks.append(
            {
                "Check": label,
                "Status": "OK" if ok else "Needs Attention",
                "Detail": detail,
            }
        )
        if not ok:
            issues.append(f"{label}: {detail}")

    add_check("U variable", u_var in ds.data_vars, f"Selected: {u_var or 'not selected'}")
    add_check("V variable", v_var in ds.data_vars, f"Selected: {v_var or 'not selected'}")
    add_check("Longitude axis", _name_exists_in_dataset(ds, lon_coord), f"Selected: {lon_coord or 'not selected'}")
    add_check("Latitude axis", _name_exists_in_dataset(ds, lat_coord), f"Selected: {lat_coord or 'not selected'}")
    add_check("Time axis", _name_exists_in_dataset(ds, time_coord), f"Selected: {time_coord or 'not selected'}")
    add_check("Depth axis", True if not depth_coord else _name_exists_in_dataset(ds, depth_coord), f"Selected: {depth_coord or 'not required / not selected'}")
    add_check("Distinct velocity fields", bool(u_var and v_var and u_var != v_var), "U and V must point to different variables")
    add_check("Distinct spatial axes", bool(lon_coord and lat_coord and lon_coord != lat_coord), "Longitude and latitude must point to different axes")

    structure_issues = validate_dataset_structure(ds, u_var, v_var, lon_coord, lat_coord, time_coord, depth_coord)
    add_check("Structural compatibility", len(structure_issues) == 0, structure_issues[0] if structure_issues else "Selected variables and axes are structurally compatible")
    issues.extend(structure_issues)

    return pd.DataFrame(checks), issues


def build_spatial_sanity_warnings(ds, lon_coord, lat_coord):
    """Generate non-blocking warnings for suspicious spatial coordinates."""
    warnings = []

    def _axis_values(name):
        if not _name_exists_in_dataset(ds, name):
            return None
        if name in ds.variables:
            vals = ds[name].values
        else:
            vals = np.asarray(ds[name])
        vals = np.asarray(vals)
        return vals[np.isfinite(vals)] if vals.size > 0 else np.array([])

    lon_vals = _axis_values(lon_coord)
    lat_vals = _axis_values(lat_coord)

    if lon_vals is None or lon_vals.size == 0:
        warnings.append("Longitude axis has no finite values to validate.")
    else:
        lon_min = float(np.nanmin(lon_vals))
        lon_max = float(np.nanmax(lon_vals))
        if lon_min < -360.0 or lon_max > 360.0:
            warnings.append(f"Longitude range looks suspicious: [{lon_min:.3f}, {lon_max:.3f}] (expected roughly within [-360, 360]).")
        if (lon_max - lon_min) < 0.01:
            warnings.append("Longitude span is extremely small; verify coordinate mapping.")

    if lat_vals is None or lat_vals.size == 0:
        warnings.append("Latitude axis has no finite values to validate.")
    else:
        lat_min = float(np.nanmin(lat_vals))
        lat_max = float(np.nanmax(lat_vals))
        if lat_min < -90.0 or lat_max > 90.0:
            warnings.append(f"Latitude range looks suspicious: [{lat_min:.3f}, {lat_max:.3f}] (expected roughly within [-90, 90]).")
        if (lat_max - lat_min) < 0.01:
            warnings.append("Latitude span is extremely small; verify coordinate mapping.")

    if lon_coord in ds.variables and ds[lon_coord].ndim == 1 and lon_vals is not None and lon_vals.size > 2:
        d = np.diff(ds[lon_coord].values)
        d = d[np.isfinite(d)]
        if d.size > 0 and not (np.all(d >= 0) or np.all(d <= 0)):
            warnings.append("Longitude coordinate is not monotonic (1D axis); interpolation assumptions may be violated.")

    if lat_coord in ds.variables and ds[lat_coord].ndim == 1 and lat_vals is not None and lat_vals.size > 2:
        d = np.diff(ds[lat_coord].values)
        d = d[np.isfinite(d)]
        if d.size > 0 and not (np.all(d >= 0) or np.all(d <= 0)):
            warnings.append("Latitude coordinate is not monotonic (1D axis); interpolation assumptions may be violated.")

    return warnings


def get_actionable_error_guidance(error_text):
    """Translate raw exception text into concrete, user-facing troubleshooting steps."""
    message = str(error_text or "")
    message_l = message.lower()
    guidance = []

    if "velocity variables not found" in message_l:
        guidance.append("Open 'View Uploaded NetCDF File Details' and map the correct U and V variables.")
    if "coordinate names not found" in message_l:
        guidance.append("Open 'View Uploaded NetCDF File Details' and map the correct longitude and latitude coordinates.")
    if "time coordinate" in message_l or ("time" in message_l and "coord" in message_l):
        guidance.append("Open 'View Uploaded NetCDF File Details' and map the correct time coordinate.")
    if "depth coordinate" in message_l or ("vertical axis" in message_l):
        guidance.append("If the velocity fields are 4D, choose the correct depth coordinate in the mapping panel.")
    if "dimensions differ" in message_l or "structurally compatible" in message_l or "not compatible with u/v dims" in message_l:
        guidance.append("The selected fields may exist but not share a compatible grid structure. Re-check U/V and axis mappings.")
    if "jit" in message_l and ("compiler" in message_l or "failed" in message_l):
        guidance.append("Switch backend to 'scipy' if JIT compilation is unavailable on this machine.")
    if "no valid water points" in message_l:
        guidance.append("The selected U variable or lon/lat coordinates may not align with the wet mask. Re-check variable and coordinate mapping.")
    if "insufficient disk space" in message_l or "no space left" in message_l:
        guidance.append("Free disk space or remove old run snapshots under runs/<session_id>/snapshots before running again.")
    if not guidance:
        guidance.append("Review the mapped variables, coordinates, timestep, backend, and uploaded dataset structure, then rerun.")

    return guidance


@st.cache_data(show_spinner=False)
def get_zarr_metadata(zarr_path, zarr_mtime):
    """Read lightweight structural metadata from a Zarr trajectory store.

    Cached by (zarr_path, zarr_mtime) so the disk is not re-read on every
    Streamlit rerun unless the output file has been modified.

    Returns a dict with:
        n_steps            – number of saved output time frames.
        trajectory_count   – total number of particles (trajectories).
        has_sampled_speed  – True if velocity sampling was active during the run.
        has_time           – True if a time coordinate was written to the store.
    """
    ds = xr.open_zarr(zarr_path)
    try:
        return {
            "n_steps": int(ds["lon"].shape[1]),
            "trajectory_count": int(ds.sizes.get("trajectory", 0)),
            "has_sampled_speed": "sampled_speed" in ds,
            "has_time": "time" in ds,
        }
    finally:
        _safe_close_dataset(ds)


@st.cache_data(show_spinner=False)
def get_zarr_particle_extent(zarr_path, zarr_mtime):
    """Compute the geographic bounding box (lon_min, lon_max, lat_min, lat_max)
    spanned by all finite particle positions across the entire trajectory store.

    Used by the 'Focus on Particles (Zoom In)' map view to tightly frame the
    active ocean region rather than the full NetCDF domain.
    NaN values (out-of-bounds particles) are ignored via skipna=True.
    """
    ds = xr.open_zarr(zarr_path)
    try:
        lon_min = float(ds["lon"].min(skipna=True).values)
        lon_max = float(ds["lon"].max(skipna=True).values)
        lat_min = float(ds["lat"].min(skipna=True).values)
        lat_max = float(ds["lat"].max(skipna=True).values)
        return lon_min, lon_max, lat_min, lat_max
    finally:
        _safe_close_dataset(ds)


@st.cache_data(show_spinner=False)
def get_netcdf_domain_extent(netcdf_path, netcdf_mtime, lon_coord, lat_coord):
    """Return the full hydrodynamic model domain extent
    (lon_min, lon_max, lat_min, lat_max) from the source NetCDF file.

    Used by the 'Full Dataset Domain (Zoom Out)' map view to display the
    entire Copernicus GLORYS reanalysis grid, regardless of where particles
    currently reside.

    Data source: Copernicus Marine Service — GLORYS12V1 Global Ocean Physics
    Reanalysis (product id: GLOBAL_MULTIYEAR_PHY_001_030).
    """
    ds = xr.open_dataset(netcdf_path)
    try:
        return (
            float(ds[lon_coord].min().values),
            float(ds[lon_coord].max().values),
            float(ds[lat_coord].min().values),
            float(ds[lat_coord].max().values),
        )
    finally:
        _safe_close_dataset(ds)


@st.cache_data(show_spinner=False)
def get_zarr_step_data(zarr_path, zarr_mtime, step):
    """Load all trajectory data required to render the map at a given output step.

    Slices the Zarr store up to and including 'step' so trajectory paths can be
    drawn as polylines, and reads the single-frame position and speed at 'step'
    for the scatter overlay.

    Returns a dict with:
        traj_lon    – shape (n_traj, step+1) full lon path array.
        traj_lat    – shape (n_traj, step+1) full lat path array.
        final_lon   – shape (n_traj,)  lon positions at selected step.
        final_lat   – shape (n_traj,)  lat positions at selected step.
        speed_step  – shape (n_traj,)  sampled speed at step (None if absent).
        speed_traj  – shape (n_traj, step+1) speed path (None if absent).
        current_time – numpy datetime64 of the selected step (None if absent).

    Out-of-bounds particles are represented as NaN; downstream code uses
    np.isfinite() to filter them consistently.
    """
    ds = xr.open_zarr(zarr_path)
    try:
        traj_lon = ds["lon"][:, : step + 1].load().values
        traj_lat = ds["lat"][:, : step + 1].load().values
        final_lon = ds["lon"][:, step].load().values
        final_lat = ds["lat"][:, step].load().values
        speed_step = None
        speed_traj = None
        if "sampled_speed" in ds:
            speed_step = ds["sampled_speed"][:, step].load().values
            speed_traj = ds["sampled_speed"][:, : step + 1].load().values
        current_time = None
        if "time" in ds:
            current_time = ds["time"][0, step].values
        return {
            "traj_lon": traj_lon,
            "traj_lat": traj_lat,
            "final_lon": final_lon,
            "final_lat": final_lat,
            "speed_step": speed_step,
            "speed_traj": speed_traj,
            "current_time": current_time,
        }
    finally:
        _safe_close_dataset(ds)


@st.cache_data(show_spinner=False)
def get_zarr_qc_summary(zarr_path, zarr_mtime, step):
    """Compute particle Quality-Control (QC) statistics for a given output step.

    A particle is considered 'lost' when its lon/lat becomes NaN, which occurs
    when OceanParcels calls particle.delete() upon an ErrorOutOfBounds event
    (see core_lpt.DeleteParticle). This is physically expected: particles that
    advect beyond the hydrodynamic grid boundary are removed rather than
    reflected or interpolated.

    Returns a dict with:
        initial_count        – particles with valid positions at step 0.
        current_active       – particles still active at the selected step.
        current_lost         – particles lost by the selected step.
        current_lost_ratio   – lost / initial expressed as a percentage.
        final_active         – particles active at the very last step.
        final_lost           – particles lost by the final step.
        final_lost_ratio     – final lost / initial as a percentage.

    Ref: Delandmeter & van Sebille (2019), 'The Parcels v2.0 Lagrangian
    framework: new field interpolation schemes', Geosci. Model Dev., 12,
    3571–3584. doi:10.5194/gmd-12-3571-2019
    """
    ds = xr.open_zarr(zarr_path)
    try:
        initial_lon = ds["lon"][:, 0].load().values
        initial_lat = ds["lat"][:, 0].load().values
        current_lon = ds["lon"][:, step].load().values
        current_lat = ds["lat"][:, step].load().values
        final_lon = ds["lon"][:, -1].load().values
        final_lat = ds["lat"][:, -1].load().values

        initial_mask = np.isfinite(initial_lon) & np.isfinite(initial_lat)
        current_mask = np.isfinite(current_lon) & np.isfinite(current_lat)
        final_mask = np.isfinite(final_lon) & np.isfinite(final_lat)

        initial_count = int(np.sum(initial_mask))
        current_active = int(np.sum(current_mask))
        final_active = int(np.sum(final_mask))
        current_lost = max(0, initial_count - current_active)
        final_lost = max(0, initial_count - final_active)

        return {
            "initial_count": initial_count,
            "current_active": current_active,
            "current_lost": current_lost,
            "current_lost_ratio": (current_lost / initial_count) * 100 if initial_count else 0.0,
            "final_active": final_active,
            "final_lost": final_lost,
            "final_lost_ratio": (final_lost / initial_count) * 100 if initial_count else 0.0,
        }
    finally:
        _safe_close_dataset(ds)


def parse_stations_csv(stations_raw):
    """Normalize and validate a user-uploaded sampling station CSV.

    Performs case-insensitive column resolution so common naming variants
    (e.g. 'Longitude', 'lon', 'x') are accepted without user reformatting.

    Required columns (resolved by alias):
        StationName  – station label.
        Lon          – decimal-degree longitude (WGS 84 / EPSG:4326).
        Lat          – decimal-degree latitude  (WGS 84 / EPSG:4326).

    Optional columns:
        Group        – any categorical label (bay, region, type, zone …).
                       Used for differentiated marker styles on the map.

    Returns:
        (DataFrame, None)     on success — normalized df with canonical column names.
        (None, error_string)  on failure.

    Coordinate reference: WGS 84 datum (EPSG:4326), consistent with the
    Copernicus GLORYS reanalysis product coordinate system.
    """
    column_map = {str(c).strip().lower(): c for c in stations_raw.columns}

    def resolve_column(candidates):
        for c in candidates:
            if c in column_map:
                return column_map[c]
        return None

    lon_col = resolve_column(["lon", "longitude", "x"])
    lat_col = resolve_column(["lat", "latitude", "y"])
    name_col = resolve_column(["stationname", "station_name", "name", "station"])
    group_col = resolve_column(
        [
            "group",
            "stationgroup",
            "station_group",
            "category",
            "type",
            "zone",
            "region",
            "bayorgulf",
            "bay_or_gulf",
        ]
    )

    missing = []
    if lon_col is None:
        missing.append("lon")
    if lat_col is None:
        missing.append("lat")
    if name_col is None:
        missing.append("station name")
    if missing:
        return None, f"Missing required columns: {', '.join(missing)}"

    stations_df = pd.DataFrame(
        {
            "Lon": pd.to_numeric(stations_raw[lon_col], errors="coerce"),
            "Lat": pd.to_numeric(stations_raw[lat_col], errors="coerce"),
            "StationName": stations_raw[name_col].astype(str).str.strip(),
        }
    )
    if group_col is not None:
        stations_df["Group"] = stations_raw[group_col].astype(str).str.strip()

    stations_df = stations_df.replace([np.inf, -np.inf], np.nan)
    stations_df = stations_df.dropna(subset=["Lon", "Lat"])
    stations_df = stations_df[stations_df["StationName"] != ""]

    if stations_df.empty:
        return None, "No valid station rows found after cleaning (Lon/Lat/StationName)."

    if "Group" in stations_df.columns:
        stations_df.loc[stations_df["Group"] == "", "Group"] = "Ungrouped"

    return stations_df, None


# SIMULATION_STATE_DEFAULTS
# --------------------------
# Central registry of all Streamlit session-state keys owned by the simulation
# controls panel.  Calling ensure_simulation_state_defaults() at page load
# guarantees every key exists before any widget reads it, preventing
# KeyError / AttributeError on first run or after app restarts.
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
    "sim_batch_config_text": "",
    "batch_last_summary": [],
    "run_history": [],
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


def restore_run_history_config(config, max_days):
    """Write a previously saved run configuration back into session state.

    Clamps 'sim_days' to [1, max_days] so restoring an entry from a longer
    dataset does not produce an out-of-range slider value on the current file.

    Args:
        config   – dict of sim_* keys as saved by save_run_history_entry.
        max_days – upper bound derived from the currently loaded NetCDF file.
    """
    for key, value in config.items():
        if key == "sim_days":
            st.session_state[key] = max(1, min(int(value), int(max_days)))
        else:
            st.session_state[key] = value


def save_run_history_entry(entry):
    """Prepend a completed run entry to the session-state run history list.

    Keeps at most 10 entries (FIFO) to bound memory usage across repeated runs
    in a single Streamlit session.  Each entry is a dict containing:
        label         – human-readable run identifier shown in the history UI.
        summary       – one-line parameter string for quick inspection.
        snapshot_path – path to a Zarr copy of the run output (may be None).
        config        – dict of sim_* keys for restore_run_history_config.
    """
    history = st.session_state.get("run_history", [])
    history.insert(0, entry)
    st.session_state["run_history"] = history[:10]


def _human_bytes(n_bytes):
    """Convert a raw byte count to a human-readable string (e.g. '1.4 GB').
    Uses 1024-based binary prefixes (KiB-style scale but SI suffixes).
    """
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(max(0, n_bytes))
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024


def _get_path_size_bytes(path):
    """Return the total size in bytes of a file or directory tree.
    Returns 0 if the path does not exist.
    Silently skips files that cannot be stat-ed (e.g. permission errors).
    """
    if not os.path.exists(path):
        return 0
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _, files in os.walk(path):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                total += os.path.getsize(fpath)
            except OSError:
                continue
    return total


def _get_free_space_bytes(path):
    """Return the available free disk space (in bytes) on the volume containing
    'path'.  Falls back to the current directory if path is not a directory.
    Uses shutil.disk_usage which is cross-platform (POSIX + Windows).
    """
    target = path if os.path.isdir(path) else os.path.dirname(path) or "."
    return shutil.disk_usage(target).free


def get_or_cache_uploaded_file(uploaded_file):
    """Persist a Streamlit-uploaded NetCDF file to a local cache directory and
    return its path, avoiding redundant writes on reruns.

    Streamlit re-executes the entire script on every user interaction.  Without
    caching, a large NetCDF would be written to disk on every rerun.  This
    function compares a (name, size) signature against the stored signature;
    if they match and the file still exists, the cached path is returned
    immediately without any disk I/O.

    A pre-flight disk-space check (200 MB safety margin) prevents an OSError
    that would otherwise crash the app midway through the write.

    Returns:
        (str, None)   – path to the cached file on success.
        (None, str)   – (None, human-readable error message) on failure.
    """
    runtime = ensure_runtime_paths()
    cache_dir = runtime["upload_cache_dir"]
    os.makedirs(cache_dir, exist_ok=True)

    signature = f"{uploaded_file.name}:{uploaded_file.size}"
    cached_path = st.session_state.get("upload_cached_path")
    cached_sig = st.session_state.get("upload_signature")
    if cached_path and cached_sig == signature and os.path.exists(cached_path):
        return cached_path, None

    required = int(uploaded_file.size)
    free = _get_free_space_bytes(cache_dir)
    safety_margin = 200 * 1024 * 1024
    if free < (required + safety_margin):
        return None, (
            "Insufficient disk space to cache uploaded file. "
            f"Required at least {_human_bytes(required + safety_margin)}, free {_human_bytes(free)}."
        )

    ext = os.path.splitext(uploaded_file.name)[1] or ".nc"
    sig_hash = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]
    target_path = os.path.join(cache_dir, f"upload_{sig_hash}{ext}")
    tmp_write_path = target_path + ".tmp"
    try:
        with open(tmp_write_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        os.replace(tmp_write_path, target_path)
    finally:
        if os.path.exists(tmp_write_path):
            try:
                os.remove(tmp_write_path)
            except OSError:
                pass

    old_path = st.session_state.get("upload_cached_path")
    if old_path and old_path != target_path and os.path.exists(old_path):
        try:
            os.remove(old_path)
        except OSError:
            pass

    st.session_state["upload_cached_path"] = target_path
    st.session_state["upload_signature"] = signature
    return target_path, None


def snapshot_run_output(output_path, run_id):
    """Copy the current simulation Zarr output to a uniquely named snapshot
    directory under the session's snapshots folder, making it available for A/B comparison
    without being overwritten by the next simulation run.

    A pre-flight disk-space check (100 MB safety margin on top of the source
    size) is performed before copying.  If space is insufficient, the function
    returns (None, warning_message) rather than raising, so the main
    simulation result is not lost.

    Returns:
        (snapshot_path, None)    – on success.
        (None, warning_string)   – if the copy was skipped due to low disk space.
    """
    runtime = ensure_runtime_paths()
    snapshots_root = runtime["snapshots_dir"]
    os.makedirs(snapshots_root, exist_ok=True)
    safe_id = str(run_id).replace(":", "-").replace(" ", "_")
    snapshot_path = os.path.join(snapshots_root, f"{safe_id}.zarr")
    required = _get_path_size_bytes(output_path)
    free = _get_free_space_bytes(snapshots_root)
    if free < (required + 100 * 1024 * 1024):
        return None, (
            "Skipped snapshot copy due to low disk space. "
            f"Need {_human_bytes(required + 100 * 1024 * 1024)}, free {_human_bytes(free)}."
        )
    if os.path.exists(snapshot_path):
        shutil.rmtree(snapshot_path, ignore_errors=True)
    shutil.copytree(output_path, snapshot_path)
    return snapshot_path, None


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


def _to_bool(value):
    """Robustly coerce a value of unknown type to Python bool.

    Accepts: bool, int, float, and common string representations
    ('true'/'false', 'yes'/'no', '1'/'0', 'on'/'off').
    Raises ValueError for unrecognised inputs so batch config validation
    can surface a clear error to the user.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        txt = value.strip().lower()
        if txt in {"1", "true", "yes", "y", "on"}:
            return True
        if txt in {"0", "false", "no", "n", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    raise ValueError(f"Cannot convert value to bool: {value}")


def parse_batch_config_json(raw_text, base_config, max_days):
    """Parse and validate a JSON list of batch run configurations supplied by
    the user in the 'Batch Execution Mode' text area.

    Each item in the list is merged with base_config (the current UI values),
    so only the parameters the user wants to vary need to be specified.
    All fields are strictly validated for type and range before any simulation
    is dispatched, preventing silent runtime failures mid-batch.

    Args:
        raw_text    – raw string content of the JSON text area.
        base_config – dict of fallback values derived from the current UI state.
        max_days    – upper bound for 'days', derived from the loaded NetCDF file.

    Returns:
        (list[dict], list[str]) – (validated run configs, list of error strings).
        An empty run list with errors means nothing will be executed.
    """
    text = str(raw_text or "").strip()
    if not text:
        return [], ["Batch config is empty. Add a JSON list of run objects."]

    try:
        payload = json.loads(text)
    except Exception as e:
        return [], [f"Invalid JSON: {e}"]

    if not isinstance(payload, list) or len(payload) == 0:
        return [], ["Batch config must be a non-empty JSON list."]

    normalized = []
    errors = []
    allowed_modes = {"uniform", "random", "hybrid", "valid"}
    allowed_backends = {"scipy", "jit"}
    allowed_release = {"instant", "repeated"}
    allowed_mesh_adapters = {"none", "flattened_grid_1d"}

    for idx, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            errors.append(f"Run #{idx}: each item must be an object.")
            continue

        cfg = dict(base_config)
        cfg.update(item)
        run_name = str(cfg.get("name") or f"Batch Run {idx}").strip() or f"Batch Run {idx}"

        try:
            use_full = _to_bool(cfg.get("use_full", False))
            days = int(max_days) if use_full else int(cfg.get("days", base_config["days"]))
            days = max(1, min(days, int(max_days)))

            mode = str(cfg.get("mode", base_config["mode"])).strip().lower()
            if mode not in allowed_modes:
                raise ValueError(f"invalid mode '{mode}'")

            u_var = str(cfg.get("u_var", base_config.get("u_var", "uo"))).strip()
            v_var = str(cfg.get("v_var", base_config.get("v_var", "vo"))).strip()
            if not u_var or not v_var:
                raise ValueError("u_var and v_var must both be provided")
            if u_var == v_var:
                raise ValueError("u_var and v_var must be different")

            lon_coord = str(cfg.get("lon_coord", base_config.get("lon_coord", "longitude"))).strip()
            lat_coord = str(cfg.get("lat_coord", base_config.get("lat_coord", "latitude"))).strip()
            if not lon_coord or not lat_coord:
                raise ValueError("lon_coord and lat_coord must both be provided")
            if lon_coord == lat_coord:
                raise ValueError("lon_coord and lat_coord must be different")

            time_coord = str(cfg.get("time_coord", base_config.get("time_coord", "time"))).strip()
            if not time_coord:
                raise ValueError("time_coord must be provided")

            depth_coord = str(cfg.get("depth_coord", base_config.get("depth_coord", ""))).strip()

            mesh_adapter = str(cfg.get("mesh_adapter", base_config.get("mesh_adapter", "none"))).strip().lower()
            if mesh_adapter not in allowed_mesh_adapters:
                raise ValueError(f"invalid mesh_adapter '{mesh_adapter}'")

            backend = str(cfg.get("backend", base_config["backend"])).strip().lower()
            if backend not in allowed_backends:
                raise ValueError(f"invalid backend '{backend}'")

            particle_count = int(cfg.get("particle_count", base_config["particle_count"]))
            if particle_count < 0:
                raise ValueError("particle_count must be >= 0")

            seed = int(cfg.get("seed", base_config["seed"]))
            if seed < 0:
                raise ValueError("seed must be >= 0")

            dt_v = int(cfg.get("dt_minutes", base_config["dt_minutes"]))
            if dt_v < 1 or dt_v > 60:
                raise ValueError("dt_minutes must be in [1, 60]")

            out_v = int(cfg.get("output_hours", base_config["output_hours"]))
            if out_v < 1 or out_v > 24:
                raise ValueError("output_hours must be in [1, 24]")

            release_mode = str(cfg.get("release_mode", base_config["release_mode"])).strip().lower()
            if release_mode not in allowed_release:
                raise ValueError(f"invalid release_mode '{release_mode}'")

            repeat_v = int(cfg.get("repeat_release_hours", base_config["repeat_release_hours"]))
            if repeat_v < 1 or repeat_v > 24:
                raise ValueError("repeat_release_hours must be in [1, 24]")

            sample_velocity = _to_bool(cfg.get("sample_velocity", base_config["sample_velocity"]))
        except Exception as e:
            errors.append(f"Run #{idx} ({run_name}): {e}")
            continue

        normalized.append(
            {
                "name": run_name,
                "days": days,
                "mode": mode,
                "u_var": u_var,
                "v_var": v_var,
                "lon_coord": lon_coord,
                "lat_coord": lat_coord,
                "time_coord": time_coord,
                "depth_coord": depth_coord,
                "mesh_adapter": mesh_adapter,
                "particle_count": particle_count,
                "seed": seed,
                "backend": backend,
                "dt_minutes": dt_v,
                "output_hours": out_v,
                "release_mode": release_mode,
                "repeat_release_hours": repeat_v,
                "sample_velocity": sample_velocity,
            }
        )

    return normalized, errors


def _build_run_kwargs(file_path, output_path, progress_bar, run_cfg):
    """Assemble a keyword-argument dict for core_lpt.run_simulation from a
    validated batch run configuration dict.

    Only keys that exist in the run_simulation signature are included, making
    this function robust to future signature changes without requiring updates
    here.

    Args:
        file_path    – absolute path to the cached NetCDF input file.
        output_path  – Zarr output path (overwritten by each run).
        progress_bar – Streamlit progress bar object forwarded to the engine.
        run_cfg      – a single validated config dict from parse_batch_config_json.

    Returns:
        dict – filtered kwargs ready for **-unpacking into run_simulation.
    """
    kwargs = {
        "file_path": file_path,
        "output_path": output_path,
        "days": int(run_cfg["days"]),
        "mode": run_cfg["mode"],
        "progress_bar": progress_bar,
        "u_var": run_cfg.get("u_var", "uo"),
        "v_var": run_cfg.get("v_var", "vo"),
        "lon_coord": run_cfg.get("lon_coord", "longitude"),
        "lat_coord": run_cfg.get("lat_coord", "latitude"),
        "time_coord": run_cfg.get("time_coord", "time"),
        "depth_coord": run_cfg.get("depth_coord", ""),
        "particle_count": int(run_cfg["particle_count"]) if int(run_cfg["particle_count"]) > 0 else None,
        "seed": int(run_cfg["seed"]) if int(run_cfg["seed"]) > 0 else None,
        "backend": run_cfg["backend"],
        "dt_minutes": int(run_cfg["dt_minutes"]),
        "output_hours": int(run_cfg["output_hours"]),
        "repeat_release_hours": (
            int(run_cfg["repeat_release_hours"])
            if run_cfg["release_mode"] == "repeated"
            else None
        ),
        "sample_velocity": bool(run_cfg["sample_velocity"]),
    }
    valid_keys = inspect.signature(core_lpt.run_simulation).parameters
    return {k: v for k, v in kwargs.items() if k in valid_keys}


def validate_run_semantics(ds, run_cfg):
    """Run structural/dataset-semantic validation for a single run config."""
    issues = []
    u_var = str(run_cfg.get("u_var", "")).strip()
    v_var = str(run_cfg.get("v_var", "")).strip()
    lon_coord = str(run_cfg.get("lon_coord", "")).strip()
    lat_coord = str(run_cfg.get("lat_coord", "")).strip()
    time_coord = str(run_cfg.get("time_coord", "")).strip()
    depth_coord = str(run_cfg.get("depth_coord", "")).strip()

    if u_var not in ds.data_vars:
        issues.append(f"U variable '{u_var or 'not selected'}' not found in dataset.")
    if v_var not in ds.data_vars:
        issues.append(f"V variable '{v_var or 'not selected'}' not found in dataset.")
    if not _name_exists_in_dataset(ds, lon_coord):
        issues.append(f"Longitude axis '{lon_coord or 'not selected'}' not found.")
    if not _name_exists_in_dataset(ds, lat_coord):
        issues.append(f"Latitude axis '{lat_coord or 'not selected'}' not found.")
    if not _name_exists_in_dataset(ds, time_coord):
        issues.append(f"Time axis '{time_coord or 'not selected'}' not found.")
    if depth_coord and not _name_exists_in_dataset(ds, depth_coord):
        issues.append(f"Depth axis '{depth_coord}' not found.")

    if u_var in ds.data_vars and v_var in ds.data_vars:
        issues.extend(validate_dataset_structure(ds, u_var, v_var, lon_coord, lat_coord, time_coord, depth_coord))
        try:
            field = ds[u_var]
            if depth_coord and depth_coord in field.dims and time_coord in field.dims:
                field = field.isel({time_coord: 0, depth_coord: 0})
            elif time_coord in field.dims:
                field = field.isel({time_coord: 0})
            elif depth_coord and depth_coord in field.dims:
                field = field.isel({depth_coord: 0})
            wet_count = int(np.isfinite(field.values).sum())
            if wet_count == 0:
                issues.append("No wet cells found in selected U field for initial slice (land-mask check failed).")
        except Exception as e:
            issues.append(f"Land-mask check failed: {e}")

    return issues


@st.cache_data(show_spinner=False)
def get_zarr_step_summary(zarr_path, zarr_mtime, step):
    """Compute per-step particle activity and optional speed statistics.

    Used by the A/B Comparison Mode to populate the metric delta table without
    loading full trajectory arrays.  Results are cached by (path, mtime, step).

    Returns a dict with:
        active_count         – particles with finite positions at the step.
        total_trajectories   – total trajectory count in the store.
        active_ratio_percent – active_count / total * 100.
        speed_mean           – mean sampled speed at step (None if unavailable).
        speed_max            – max  sampled speed at step (None if unavailable).
    """
    ds = xr.open_zarr(zarr_path)
    try:
        lon = ds["lon"][:, step].load().values
        lat = ds["lat"][:, step].load().values
        alive_mask = np.isfinite(lon) & np.isfinite(lat)
        active_count = int(np.sum(alive_mask))
        total = int(ds.sizes.get("trajectory", 0))
        active_ratio = (active_count / total) * 100 if total > 0 else 0.0

        speed_mean = None
        speed_max = None
        if "sampled_speed" in ds:
            spd = ds["sampled_speed"][:, step].load().values
            valid_spd = spd[np.isfinite(spd)]
            if valid_spd.size > 0:
                speed_mean = float(np.mean(valid_spd))
                speed_max = float(np.max(valid_spd))

        return {
            "active_count": active_count,
            "total_trajectories": total,
            "active_ratio_percent": float(active_ratio),
            "speed_mean": speed_mean,
            "speed_max": speed_max,
        }
    finally:
        _safe_close_dataset(ds)


def _haversine_km(lon1, lat1, lon2, lat2):
    """Vectorised great-circle distance between two points (or arrays of points)
    on a sphere of mean Earth radius 6371 km.

    Implements the Haversine formula:
        a = sin²(Δφ/2) + cos(φ₁) · cos(φ₂) · sin²(Δλ/2)
        c = 2 · atan2(√a, √(1−a))
        d = R · c

    All inputs should be decimal degrees (WGS 84).
    Supports NumPy broadcasting, so lon1/lat1 can be arrays (particle
    positions) and lon2/lat2 can be scalars (station coordinates).

    Ref: Sinnott, R.W. (1984), 'Virtues of the Haversine', Sky and Telescope,
    68(2), p.159.
    """
    r = 6371.0  # Mean Earth radius in kilometres (IAU 2012)
    lon1r = np.radians(lon1)
    lat1r = np.radians(lat1)
    lon2r = np.radians(lon2)
    lat2r = np.radians(lat2)
    dlon = lon2r - lon1r
    dlat = lat2r - lat1r
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2.0) ** 2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return r * c


def _lonlat_to_unit_xyz(lon_deg, lat_deg):
    """Convert lon/lat arrays (deg) to unit-sphere Cartesian coordinates."""
    lon_rad = np.radians(lon_deg)
    lat_rad = np.radians(lat_deg)
    cos_lat = np.cos(lat_rad)
    return np.column_stack(
        (
            cos_lat * np.cos(lon_rad),
            cos_lat * np.sin(lon_rad),
            np.sin(lat_rad),
        )
    )


def _radius_km_to_chord(radius_km):
    """Map surface arc radius (km) to unit-sphere chord length for KD-tree queries."""
    earth_radius_km = 6371.0
    angular = max(0.0, float(radius_km)) / earth_radius_km
    return float(2.0 * np.sin(angular / 2.0))


def build_trajectory_geojson(traj_lon, traj_lat, candidate_indices, traj_window_steps=0, point_stride=1):
    """Build a GeoJSON FeatureCollection of trajectory LineStrings."""
    features = []
    for idx in candidate_indices:
        lon_vals = traj_lon[idx]
        lat_vals = traj_lat[idx]
        mask = np.isfinite(lon_vals) & np.isfinite(lat_vals)
        if np.sum(mask) < 2:
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
        coords = [[round(float(lo), 6), round(float(la), 6)] for lo, la in zip(clean_lon, clean_lat)]
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "trajectory_id": int(idx),
                    "point_count": int(len(coords)),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def build_station_metrics_geojson(stations_df, station_metrics_df):
    """Build a GeoJSON FeatureCollection of station points with metrics."""
    if stations_df is None or station_metrics_df is None or stations_df.empty or station_metrics_df.empty:
        return None

    metric_rows = {}
    for _, row in station_metrics_df.iterrows():
        metric_rows[str(row.get("Station", ""))] = row

    features = []
    for _, row in stations_df.iterrows():
        name = str(row.get("StationName", ""))
        if not name:
            continue
        if not np.isfinite(row.get("Lon", np.nan)) or not np.isfinite(row.get("Lat", np.nan)):
            continue
        props = {"Station": name}
        if "Group" in stations_df.columns:
            props["Group"] = str(row.get("Group", ""))
        mrow = metric_rows.get(name)
        if mrow is not None:
            for col in [
                "Entries Within Radius",
                "Entries At Selected Step",
                "First Arrival Step (Min)",
                "First Arrival Step (Median)",
                "First Arrival Step (Max)",
            ]:
                val = mrow.get(col)
                if pd.notna(val):
                    props[col] = float(val) if isinstance(val, (np.floating, float)) else int(val)
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(float(row["Lon"]), 6), round(float(row["Lat"]), 6)],
                },
                "properties": props,
            }
        )
    return {"type": "FeatureCollection", "features": features}


@st.cache_data(show_spinner=False)
def get_station_analytics(zarr_path, zarr_mtime, stations_json, step, radius_km):
    """Compute particle-to-station proximity analytics over all trajectory steps
    up to and including 'step'.

    For each output step, active particles are indexed in 3D unit-sphere space
    and station proximity is queried via cKDTree when SciPy is available.
    If SciPy is unavailable, the function falls back to the Haversine method.
    A particle is considered to have 'entered' a station's influence zone when
    its distance falls within radius_km.

    Outputs:
        station_metrics      – DataFrame with per-station entry counts and
                               first-arrival step statistics (min/median/max).
        connectivity_matrix  – n_stations × n_stations DataFrame where
                               matrix[i][j] = number of trajectories that
                               first touched station i and last touched station j.
                               Captures source→sink dispersal pathways.

    The connectivity matrix is analogous to a transition probability matrix
    used in Markov chain dispersal models:
    Ref: Cowen, R.K. et al. (2006), 'Scaling of connectivity in marine
    populations', Science, 311(5760), 522-527.
    doi:10.1126/science.1122039

    Args:
        zarr_path    – path to the Zarr trajectory store.
        zarr_mtime   – file modification time (cache key).
        stations_json – JSON string of station records (from DataFrame.to_json).
        step         – maximum output step to consider (inclusive).
        radius_km    – proximity threshold in kilometres.
    """
    stations = pd.read_json(io.StringIO(stations_json))
    if stations.empty:
        return None

    ds = xr.open_zarr(zarr_path)
    try:
        lon = ds["lon"][:, : step + 1].load().values
        lat = ds["lat"][:, : step + 1].load().values
        n_traj = lon.shape[0]
        n_steps = lon.shape[1]
        n_st = len(stations)

        first_touch = np.full((n_st, n_traj), -1, dtype=int)
        step_hits_selected = np.zeros(n_st, dtype=int)
        station_lons = stations["Lon"].astype(float).values
        station_lats = stations["Lat"].astype(float).values
        station_xyz = _lonlat_to_unit_xyz(station_lons, station_lats)
        chord_radius = _radius_km_to_chord(radius_km)
        use_kdtree = cKDTree is not None

        for t in range(n_steps):
            lons_t = lon[:, t]
            lats_t = lat[:, t]
            valid = np.isfinite(lons_t) & np.isfinite(lats_t)
            if not np.any(valid):
                continue

            valid_ids = np.where(valid)[0]
            valid_lons = lons_t[valid]
            valid_lats = lats_t[valid]

            if use_kdtree:
                particle_xyz = _lonlat_to_unit_xyz(valid_lons, valid_lats)
                tree = cKDTree(particle_xyz)
                neighbor_lists = tree.query_ball_point(station_xyz, r=chord_radius)
            else:
                neighbor_lists = []
                for s_lon, s_lat in zip(station_lons, station_lats):
                    d = _haversine_km(valid_lons, valid_lats, s_lon, s_lat)
                    neighbor_lists.append(np.where(d <= float(radius_km))[0].tolist())

            for s_idx, local_hits in enumerate(neighbor_lists):
                if not local_hits:
                    continue
                touched_ids = valid_ids[np.asarray(local_hits, dtype=int)]
                if t == int(step):
                    step_hits_selected[s_idx] = int(len(touched_ids))
                new_touch = first_touch[s_idx, touched_ids] == -1
                if np.any(new_touch):
                    first_touch[s_idx, touched_ids[new_touch]] = t

        at_step_counts = step_hits_selected.tolist()
        entries_counts = []
        first_arrival_median = []
        first_arrival_min = []
        first_arrival_max = []
        for s_idx in range(n_st):
            arrived_steps = first_touch[s_idx, first_touch[s_idx] >= 0]
            entries_counts.append(int(arrived_steps.size))

            if arrived_steps.size > 0:
                first_arrival_median.append(float(np.median(arrived_steps)))
                first_arrival_min.append(int(np.min(arrived_steps)))
                first_arrival_max.append(int(np.max(arrived_steps)))
            else:
                first_arrival_median.append(None)
                first_arrival_min.append(None)
                first_arrival_max.append(None)

        # Connectivity matrix: first touched station -> latest first-touch station
        matrix = np.zeros((n_st, n_st), dtype=int)
        for tr in range(n_traj):
            touched = np.where(first_touch[:, tr] >= 0)[0]
            if touched.size == 0:
                continue
            order = touched[np.argsort(first_touch[touched, tr])]
            src = int(order[0])
            dst = int(order[-1])
            matrix[src, dst] += 1

        station_metrics = pd.DataFrame(
            {
                "Station": stations["StationName"].astype(str),
                "Entries Within Radius": entries_counts,
                "Entries At Selected Step": at_step_counts,
                "First Arrival Step (Min)": first_arrival_min,
                "First Arrival Step (Median)": first_arrival_median,
                "First Arrival Step (Max)": first_arrival_max,
            }
        )

        matrix_df = pd.DataFrame(
            matrix,
            index=stations["StationName"].astype(str).tolist(),
            columns=stations["StationName"].astype(str).tolist(),
        )

        return {
            "station_metrics": station_metrics,
            "connectivity_matrix": matrix_df,
            "engine": "cKDTree" if use_kdtree else "haversine_fallback",
        }
    finally:
        _safe_close_dataset(ds)


# Page configuration
st.set_page_config(page_title="eDNA LPT Connectivity Analysis", layout="wide")

# -----------------------------
# SIDEBAR: METADATA & REFERENCES
# -----------------------------
st.sidebar.header("Library Versions")
st.sidebar.text(f"Streamlit: {st.__version__}")
st.sidebar.text(f"Xarray: {xr.__version__}")
st.sidebar.text(f"Matplotlib: {matplotlib.__version__}")
st.sidebar.text(f"Cartopy: {cartopy.__version__}")
st.sidebar.text(f"OceanParcels: {parcels.__version__}")

st.sidebar.divider()

st.sidebar.header("Scientific Context")
st.sidebar.markdown(
    """
**What This App Assumes:**
- Input is a gridded hydrodynamic NetCDF dataset with velocity fields and spatial/time axes.
- Region, domain, and forcing source are determined by the uploaded dataset.

**Methods Used Here:**
- **OceanParcels:** trajectory integration framework used to advect particles through velocity fields.
- **AdvectionRK4:** fourth-order Runge-Kutta particle advection scheme.
- **Haversine Distance:** used for particle-to-station proximity analysis.

**Interpretation Note:**
- Connectivity results are physical transport indicators derived from the selected flow field and user-defined release settings.
"""
)
# -----------------------------
# SIDEBAR: SAMPLING STATIONS LOADER
# -----------------------------
st.sidebar.divider()
st.sidebar.header("Sampling Stations (eDNA)")
st.sidebar.caption("Upload a station CSV or download the example template below and adapt it to your own stations.")
st.sidebar.download_button(
    label="Download Example gps.csv",
    data="StationName,Lon,Lat,Group\nStation_A,-94.1000,28.9000,Region_1\nStation_B,-94.0500,28.9500,Region_1\nStation_C,-93.9800,29.0200,Region_2\n",
    file_name="gps_example.csv",
    mime="text/csv",
    width="stretch",
)
gps_file = st.sidebar.file_uploader("Upload station CSV", type=["csv"])
stations_df = None
if gps_file is not None:
    try:
        stations_raw = pd.read_csv(gps_file)
        stations_df, stations_error = parse_stations_csv(stations_raw)
        if stations_error:
            st.sidebar.error(stations_error)
        else:
            st.sidebar.success(f"Loaded {len(stations_df)} stations.")
            if "Group" not in stations_df.columns:
                st.sidebar.info("Optional grouping column not found. Plotting stations with a single style.")
            else:
                st.sidebar.info("Grouping enabled from optional group/category/type column.")
            with st.sidebar.expander("Preview normalized station data", expanded=False):
                st.dataframe(stations_df.head(10), width="stretch")
    except Exception as e:
        st.sidebar.error(f"Error loading CSV: {e}")

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
    help_quick_tab, help_tech_tab = st.tabs(["Quick How To", "Technical Docs"])
    with help_quick_tab:
        quick_preface, quick_sections = parse_markdown_sections(load_markdown_file("HOW_TO.md"))
        if quick_preface:
            st.markdown(quick_preface)
        quick_ctrl_left, quick_ctrl_right = st.columns([5, 2])
        with quick_ctrl_right:
            quick_expand_all = st.toggle(
                "Expand / Collapse All",
                key="help_quick_expand_all_toggle",
                value=False,
                help="Turn on to expand all sections. Turn off to collapse all sections.",
            )
        render_sections_as_expanders(
            quick_sections,
            expand_first=True,
            expand_all_override=bool(quick_expand_all),
        )
    with help_tech_tab:
        tech_preface, tech_sections = parse_markdown_sections(load_markdown_file("README.md"))
        if tech_preface:
            st.markdown(tech_preface)
        tech_ctrl_left, tech_ctrl_right = st.columns([5, 2])
        with tech_ctrl_right:
            tech_expand_all = st.toggle(
                "Expand / Collapse All",
                key="help_tech_expand_all_toggle",
                value=False,
                help="Turn on to expand all sections. Turn off to collapse all sections.",
            )
        render_sections_as_expanders(
            tech_sections,
            expand_first=False,
            expand_all_override=bool(tech_expand_all),
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

# -----------------------------
# FILE HANDLING, VALIDATION & METADATA
# -----------------------------
if uploaded_file is not None:
    tmp_path, upload_error = get_or_cache_uploaded_file(uploaded_file)
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
        and _name_exists_in_dataset(ds_temp, selected_lon_coord)
        and _name_exists_in_dataset(ds_temp, selected_lat_coord)
        and _name_exists_in_dataset(ds_temp, selected_time_coord)
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
                and _name_exists_in_dataset(ds_temp, selected_lon_coord)
                and _name_exists_in_dataset(ds_temp, selected_lat_coord)
                and _name_exists_in_dataset(ds_temp, selected_time_coord)
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
        lon_name = st.session_state.get("sim_lon_coord", "") if _name_exists_in_dataset(ds_temp, st.session_state.get("sim_lon_coord", "")) else None
        lat_name = st.session_state.get("sim_lat_coord", "") if _name_exists_in_dataset(ds_temp, st.session_state.get("sim_lat_coord", "")) else None
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
        comparable_runs = [
            entry
            for entry in st.session_state.run_history
            if entry.get("snapshot_path") and os.path.exists(entry.get("snapshot_path"))
        ]
        st.markdown(f"### Run History ({history_count})")
        if history_count == 0:
            st.info("No saved runs yet. A run is added to history after a successful simulation.")
        else:
            latest = st.session_state.run_history[0]
            st.caption(f"Latest: {latest['label']}")
            st.caption(f"Comparison-ready runs: {len(comparable_runs)}")
            with st.expander("Open Run History and Restore", expanded=True):
                history_labels = [entry["label"] for entry in st.session_state.run_history]
                selected_history_label = st.selectbox(
                    "Previous Runs",
                    options=history_labels,
                    key="run_history_selected_label",
                )
                selected_history = next(
                    entry for entry in st.session_state.run_history if entry["label"] == selected_history_label
                )
                st.caption(selected_history["summary"])
                hist_col1, hist_col2 = st.columns(2)
                with hist_col1:
                    if st.button("Restore Selected Run", key="restore_run_history"):
                        restore_run_history_config(selected_history["config"], max_days)
                        st.success("Run configuration restored.")
                with hist_col2:
                    if st.button("Clear History", key="clear_run_history"):
                        st.session_state.run_history = []
                        st.success("Run history cleared.")

        if st.session_state.get("batch_last_summary"):
            with st.expander("Last Batch Summary", expanded=False):
                st.dataframe(pd.DataFrame(st.session_state["batch_last_summary"]), width="stretch")

        if len(comparable_runs) >= 2:
            with st.expander("Comparison Mode (A/B)", expanded=False):
                options = [f"{idx+1}. {entry['label']}" for idx, entry in enumerate(comparable_runs)]
                comp_col1, comp_col2 = st.columns(2)
                with comp_col1:
                    baseline_label = st.selectbox("Baseline Run", options=options, key="comp_baseline")
                with comp_col2:
                    candidate_label = st.selectbox("Candidate Run", options=options, index=1, key="comp_candidate")

                base_idx = int(baseline_label.split(".", 1)[0]) - 1
                cand_idx = int(candidate_label.split(".", 1)[0]) - 1
                base_entry = comparable_runs[base_idx]
                cand_entry = comparable_runs[cand_idx]

                base_path = base_entry.get("snapshot_path")
                cand_path = cand_entry.get("snapshot_path")
                base_meta = get_zarr_metadata(base_path, os.path.getmtime(base_path))
                cand_meta = get_zarr_metadata(cand_path, os.path.getmtime(cand_path))
                comp_max_step = max(0, min(base_meta["n_steps"], cand_meta["n_steps"]) - 1)
                comp_step = st.slider(
                    "Comparison Step",
                    min_value=0,
                    max_value=int(comp_max_step),
                    value=int(comp_max_step),
                    key="comp_step",
                )

                base_qc = get_zarr_qc_summary(base_path, os.path.getmtime(base_path), comp_step)
                cand_qc = get_zarr_qc_summary(cand_path, os.path.getmtime(cand_path), comp_step)
                base_step = get_zarr_step_summary(base_path, os.path.getmtime(base_path), comp_step)
                cand_step = get_zarr_step_summary(cand_path, os.path.getmtime(cand_path), comp_step)

                compare_df = pd.DataFrame(
                    [
                        {
                            "Metric": "Active Count",
                            "Baseline": base_step["active_count"],
                            "Candidate": cand_step["active_count"],
                            "Delta (C-B)": cand_step["active_count"] - base_step["active_count"],
                        },
                        {
                            "Metric": "Active Ratio (%)",
                            "Baseline": round(base_step["active_ratio_percent"], 3),
                            "Candidate": round(cand_step["active_ratio_percent"], 3),
                            "Delta (C-B)": round(cand_step["active_ratio_percent"] - base_step["active_ratio_percent"], 3),
                        },
                        {
                            "Metric": "Lost Ratio at Step (%)",
                            "Baseline": round(base_qc["current_lost_ratio"], 3),
                            "Candidate": round(cand_qc["current_lost_ratio"], 3),
                            "Delta (C-B)": round(cand_qc["current_lost_ratio"] - base_qc["current_lost_ratio"], 3),
                        },
                        {
                            "Metric": "Final Lost Ratio (%)",
                            "Baseline": round(base_qc["final_lost_ratio"], 3),
                            "Candidate": round(cand_qc["final_lost_ratio"], 3),
                            "Delta (C-B)": round(cand_qc["final_lost_ratio"] - base_qc["final_lost_ratio"], 3),
                        },
                        {
                            "Metric": "Mean Speed",
                            "Baseline": base_step["speed_mean"],
                            "Candidate": cand_step["speed_mean"],
                            "Delta (C-B)": (
                                None
                                if base_step["speed_mean"] is None or cand_step["speed_mean"] is None
                                else round(cand_step["speed_mean"] - base_step["speed_mean"], 6)
                            ),
                        },
                        {
                            "Metric": "Max Speed",
                            "Baseline": base_step["speed_max"],
                            "Candidate": cand_step["speed_max"],
                            "Delta (C-B)": (
                                None
                                if base_step["speed_max"] is None or cand_step["speed_max"] is None
                                else round(cand_step["speed_max"] - base_step["speed_max"], 6)
                            ),
                        },
                    ]
                )
                st.dataframe(compare_df, width="stretch")
        elif history_count >= 2:
            st.info("Comparison Mode needs at least two snapshot-ready runs. Run two new simulations to populate snapshots.")

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

    with st.expander("Batch Execution Mode", expanded=False):
        st.caption(
            "Provide a JSON list of run objects. Missing fields fall back to current UI values. "
            "Supported fields: name, use_full, days, mode, u_var, v_var, lon_coord, lat_coord, time_coord, depth_coord, "
            "mesh_adapter, particle_count, seed, backend, dt_minutes, output_hours, release_mode, repeat_release_hours, sample_velocity."
        )
        if not st.session_state.get("sim_batch_config_text"):
            st.session_state["sim_batch_config_text"] = json.dumps(
                [
                    {"name": "Baseline", "days": int(days), "mode": particle_mode, "seed": int(random_seed)},
                    {
                        "name": "Sensitivity-dt5",
                        "days": int(days),
                        "mode": particle_mode,
                        "seed": int(random_seed),
                        "dt_minutes": 5,
                    },
                ],
                indent=2,
            )
        st.text_area(
            "Batch JSON",
            key="sim_batch_config_text",
            height=180,
            help="Example: [{\"name\":\"A\",\"days\":2,\"mode\":\"random\"}, {\"name\":\"B\",\"dt_minutes\":5}]",
        )

    estimated_days = int(max_days) if use_full else int(days)
    estimated_particles = estimate_particle_count(particle_mode, particle_count_override)
    steps_per_day = max(1, int((24 * 60) / int(dt_minutes)))
    estimated_steps_per_particle = estimated_days * steps_per_day
    kernel_count = 3 if sample_velocity else 2
    estimated_operations = estimated_particles * estimated_steps_per_particle * kernel_count
    estimated_outputs = max(1, int((estimated_days * 24) / max(1, int(output_hours))))

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
        if use_full:
            st.warning("Use full dataset duration is enabled. This is the biggest reason default runs can become unexpectedly long.")
        if int(dt_minutes) <= 2:
            st.warning("Very small dt selected. A 1-2 minute timestep increases integration cost dramatically.")
        elif int(dt_minutes) <= 5:
            st.info("Small dt selected. Runtime rises quickly below 10 minutes.")

    with st.expander("Preflight Readiness", expanded=False):
        preflight_rows = [
            {"Item": "U variable", "Value": st.session_state.get("sim_u_var", "") or "not selected"},
            {"Item": "V variable", "Value": st.session_state.get("sim_v_var", "") or "not selected"},
            {"Item": "Longitude coordinate", "Value": st.session_state.get("sim_lon_coord", "") or "not selected"},
            {"Item": "Latitude coordinate", "Value": st.session_state.get("sim_lat_coord", "") or "not selected"},
            {"Item": "Time coordinate", "Value": st.session_state.get("sim_time_coord", "") or "not selected"},
            {"Item": "Depth coordinate", "Value": st.session_state.get("sim_depth_coord", "") or "not used"},
            {"Item": "Duration (days)", "Value": estimated_days},
            {"Item": "Particle estimate", "Value": estimated_particles},
            {"Item": "Backend", "Value": particle_backend},
            {"Item": "Mesh adapter", "Value": st.session_state.get("sim_mesh_adapter", "none")},
            {"Item": "dt (minutes)", "Value": int(dt_minutes)},
            {"Item": "Output interval (hours)", "Value": int(output_hours)},
            {"Item": "Velocity sampling", "Value": bool(sample_velocity)},
            {"Item": "Spatial sanity warnings", "Value": int(len(spatial_warnings))},
        ]
        preflight_df = pd.DataFrame(preflight_rows)
        preflight_df["Value"] = preflight_df["Value"].map(lambda v: "Yes" if v is True else ("No" if v is False else str(v)))
        st.dataframe(preflight_df, width="stretch", hide_index=True)
        st.caption("This is the exact configuration that will be used when you start the run.")

    run_col1, run_col2 = st.columns(2)
    with run_col1:
        run_button = st.button("Run Simulation", type="primary")
    with run_col2:
        run_batch_button = st.button("Run Batch", type="secondary")

    # -----------------------------
    # EXECUTION
    # -----------------------------
    if run_batch_button and tmp_path is not None:
        base_batch_config = {
            "days": int(max_days) if use_full else int(days),
            "mode": str(particle_mode),
            "u_var": str(st.session_state.get("sim_u_var", "uo")),
            "v_var": str(st.session_state.get("sim_v_var", "vo")),
            "lon_coord": str(st.session_state.get("sim_lon_coord", "longitude")),
            "lat_coord": str(st.session_state.get("sim_lat_coord", "latitude")),
            "time_coord": str(st.session_state.get("sim_time_coord", "time")),
            "depth_coord": str(st.session_state.get("sim_depth_coord", "")),
            "mesh_adapter": str(st.session_state.get("sim_mesh_adapter", "none")),
            "particle_count": int(particle_count_override),
            "seed": int(random_seed),
            "backend": str(particle_backend),
            "dt_minutes": int(dt_minutes),
            "output_hours": int(output_hours),
            "release_mode": str(release_mode),
            "repeat_release_hours": int(repeat_release_hours),
            "sample_velocity": bool(sample_velocity),
        }
        batch_runs, batch_errors = parse_batch_config_json(
            st.session_state.get("sim_batch_config_text", ""),
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
            with st.status("Running batch simulations...", expanded=True) as status:
                global_progress = st.progress(0, text="Starting batch...")
                for done_idx, (i, cfg, prepared_path, prepared_cfg, adapter_note) in enumerate(executable_batch, start=1):
                    run_bar = st.progress(0, text=f"Run {i}/{len(batch_runs)} | {cfg['name']}: initializing")
                    started_at = time.perf_counter()
                    try:
                        run_output_path = build_run_output_path(f"batch_{i}")
                        ZARR_PATH = core_lpt.run_simulation(**_build_run_kwargs(prepared_path, run_output_path, run_bar, prepared_cfg))
                        st.session_state["active_output_path"] = ZARR_PATH

                        elapsed = time.perf_counter() - started_at
                        run_id = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S_%f")
                        snapshot_path, snapshot_warning = snapshot_run_output(ZARR_PATH, f"batch_{run_id}_{i}")
                        zarr_mtime = os.path.getmtime(ZARR_PATH)
                        run_meta = get_zarr_metadata(ZARR_PATH, zarr_mtime)

                        save_run_history_entry(
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
                                "Days": int(cfg["days"]),
                                "Mode": cfg["mode"],
                                "dt_min": int(cfg["dt_minutes"]),
                                "Output_h": int(cfg["output_hours"]),
                                "Mesh Adapter": adapter_note,
                                "Trajectories": int(run_meta["trajectory_count"]),
                                "Saved_Steps": int(run_meta["n_steps"]),
                                "Duration_s": round(float(elapsed), 2),
                                "Warning": snapshot_warning or "",
                                "Suggested Fix": "",
                            }
                        )
                        success_count += 1
                    except Exception as e:
                        elapsed = time.perf_counter() - started_at
                        summary_rows.append(
                            {
                                "Run": i,
                                "Name": cfg["name"],
                                "Status": "failed",
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
        with st.status(
            "Running Lagrangian Particle Tracking...", expanded=True
        ) as status:
            my_bar = st.progress(0, text="Initializing simulation...")
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
                ZARR_PATH = core_lpt.run_simulation(
                    **{
                        k: v
                        for k, v in {
                            "file_path": prepared_single_path,
                            "output_path": run_output_path,
                            "days": days,
                            "mode": particle_mode,
                            "progress_bar": my_bar,
                            "u_var": prepared_single_cfg.get("u_var", st.session_state.get("sim_u_var", "uo")),
                            "v_var": prepared_single_cfg.get("v_var", st.session_state.get("sim_v_var", "vo")),
                            "lon_coord": prepared_single_cfg.get("lon_coord", st.session_state.get("sim_lon_coord", "longitude")),
                            "lat_coord": prepared_single_cfg.get("lat_coord", st.session_state.get("sim_lat_coord", "latitude")),
                            "time_coord": prepared_single_cfg.get("time_coord", st.session_state.get("sim_time_coord", "time")),
                            "depth_coord": prepared_single_cfg.get("depth_coord", st.session_state.get("sim_depth_coord", "")),
                            "particle_count": (
                                int(particle_count_override)
                                if int(particle_count_override) > 0
                                else None
                            ),
                            "seed": (
                                int(random_seed) if int(random_seed) > 0 else None
                            ),
                            "backend": particle_backend,
                            "dt_minutes": int(dt_minutes),
                            "output_hours": int(output_hours),
                            "repeat_release_hours": (
                                int(repeat_release_hours)
                                if release_mode == "repeated"
                                else None
                            ),
                            "sample_velocity": sample_velocity,
                        }.items()
                        if k in inspect.signature(core_lpt.run_simulation).parameters
                    }
                )
                st.session_state["active_output_path"] = ZARR_PATH

                status.update(
                    label="Success! Simulation Finished",
                    state="complete",
                    expanded=False,
                )

                history_timestamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
                history_days = int(max_days) if use_full else int(days)
                run_id = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S_%f")
                snapshot_path, snapshot_warning = snapshot_run_output(ZARR_PATH, run_id)
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
                    {
                        "label": f"{history_timestamp} | {particle_mode} | {history_days}d | {particle_backend}",
                        "summary": (
                            f"mode={particle_mode}, days={history_days}, backend={particle_backend}, "
                            f"u={st.session_state.get('sim_u_var', 'uo')}, v={st.session_state.get('sim_v_var', 'vo')}, "
                            f"lon={st.session_state.get('sim_lon_coord', 'longitude')}, lat={st.session_state.get('sim_lat_coord', 'latitude')}, "
                            f"time={st.session_state.get('sim_time_coord', 'time')}, depth={st.session_state.get('sim_depth_coord', '') or 'none'}, "
                            f"mesh_adapter={st.session_state.get('sim_mesh_adapter', 'none')}, "
                            f"count_override={int(particle_count_override)}, seed={int(random_seed)}, "
                            f"dt={int(dt_minutes)} min, output={int(output_hours)} h, release={release_mode}"
                        ),
                        "snapshot_path": snapshot_path,
                        "config": history_config,
                    }
                )
                if snapshot_warning:
                    st.warning(snapshot_warning)

                st.success(
                    "Simulation finished. You can now adjust visualization controls below."
                )
            except Exception as e:
                st.error(f"Simulation failed: {e}")
                with st.expander("Suggested Fixes", expanded=True):
                    for hint in get_actionable_error_guidance(str(e)):
                        st.write(f"- {hint}")
                status.update(label="Simulation Failed", state="error")
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
            if preset_choice == "Fast Explore":
                view_option = "Full Dataset Domain (Zoom Out)"
                map_detail = "Fast (110m)"
                point_stride = 5
                show_station_labels = False
            elif preset_choice == "Publication Quality":
                view_option = "Full Dataset Domain (Zoom Out)"
                map_detail = "Detailed (10m)"
                point_stride = 1
                show_station_labels = True
            elif preset_choice == "Station Focus":
                view_option = "Focus on Particles (Zoom In)"
                map_detail = "Detailed (10m)"
                point_stride = 1
                show_station_labels = True

            if stations_df is not None and selected_station != "None":
                selected_rows = stations_df[stations_df["StationName"].astype(str) == selected_station]
                if not selected_rows.empty:
                    first_row = selected_rows.iloc[0]
                    grp = first_row["Group"] if "Group" in selected_rows.columns else "N/A"
                    st.caption(
                        f"Selected Station: {selected_station} | Lat: {first_row['Lat']:.5f} | Lon: {first_row['Lon']:.5f} | Group: {grp}"
                    )

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
                traj_records = []
                speed_traj = step_data["speed_traj"]
                for _i in range(total_particles):
                    _lons = traj_lon[_i]
                    _lats = traj_lat[_i]
                    for _t in range(len(_lons)):
                        if np.isfinite(_lons[_t]) and np.isfinite(_lats[_t]):
                            rec = {
                                "trajectory": _i,
                                "step": _t,
                                "lon": round(float(_lons[_t]), 6),
                                "lat": round(float(_lats[_t]), 6),
                            }
                            if speed_traj is not None:
                                _spd_v = float(speed_traj[_i, _t])
                                rec["speed_ms"] = round(_spd_v, 6) if np.isfinite(_spd_v) else None
                            traj_records.append(rec)
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
