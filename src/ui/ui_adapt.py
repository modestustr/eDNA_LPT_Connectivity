"""Dataset mesh adaptation and transformation helpers."""

import hashlib
import json
import os
import uuid

import numpy as np
import pandas as pd
import xarray as xr

from src.ui.ui_storage import ensure_runtime_paths


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
