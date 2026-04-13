"""Visualization control helpers for map rendering and preset management."""

import numpy as np
import pandas as pd


def apply_visualization_preset(preset_choice, current_state):
    """Apply visualization preset settings to current view state."""
    view_option = current_state.get("view_option", "Full Dataset Domain (Zoom Out)")
    map_detail = current_state.get("map_detail", "Balanced (50m)")
    point_stride = current_state.get("point_stride", 1)
    show_station_labels = current_state.get("show_station_labels", False)

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

    return {
        "view_option": view_option,
        "map_detail": map_detail,
        "point_stride": point_stride,
        "show_station_labels": show_station_labels,
    }


def format_station_caption(station_name, station_row):
    """Format caption text for selected station inspection."""
    grp = station_row.get("Group", "N/A") if "Group" in station_row else "N/A"
    return (
        f"Selected Station: {station_name} | "
        f"Lat: {station_row['Lat']:.5f} | "
        f"Lon: {station_row['Lon']:.5f} | "
        f"Group: {grp}"
    )


def build_trajectory_csv_records(traj_lon, traj_lat, step_data):
    """Build trajectory CSV records from step data trajectories."""
    traj_records = []
    total_particles = len(traj_lon)
    speed_traj = step_data.get("speed_traj")
    
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
    
    return traj_records

