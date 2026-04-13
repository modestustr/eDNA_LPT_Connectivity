import io

import numpy as np
import pandas as pd
import streamlit as st
import xarray as xr

try:
    from scipy.spatial import cKDTree
except Exception:
    cKDTree = None


def _haversine_km(lon1, lat1, lon2, lat2):
    """Vectorised great-circle distance in kilometres."""
    r = 6371.0
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
    """Map surface arc radius (km) to unit-sphere chord length."""
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
    """Compute station proximity analytics and connectivity matrix."""
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
        try:
            ds.close()
        except Exception:
            pass