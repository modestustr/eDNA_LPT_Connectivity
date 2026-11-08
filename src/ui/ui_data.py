"""Data access and parsing helpers for zarr/netcdf stores and user uploads."""

import numpy as np
import pandas as pd
import streamlit as st
import xarray as xr


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

