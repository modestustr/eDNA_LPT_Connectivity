import numpy as np
import pandas as pd


def name_exists_in_dataset(ds, name):
    return bool(name) and (name in ds.variables or name in ds.dims)


def infer_extra_velocity_dims(ds, u_var, lon_coord, lat_coord, time_coord):
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
    """Validate selected variables/axes for FieldSet compatibility."""
    issues = []
    if u_var not in ds.variables or v_var not in ds.variables:
        return ["Selected U/V variables do not exist in the dataset."]

    u_dims = tuple(ds[u_var].dims)
    v_dims = tuple(ds[v_var].dims)
    if u_dims != v_dims:
        issues.append(f"U and V dimensions differ: U{u_dims} vs V{v_dims}.")

    if not name_exists_in_dataset(ds, time_coord):
        issues.append(f"Time coordinate '{time_coord or 'not selected'}' does not exist.")
    else:
        time_dims = tuple(ds[time_coord].dims) if time_coord in ds.variables else (time_coord,)
        if time_coord not in u_dims and not set(time_dims).issubset(set(u_dims)):
            issues.append(f"Time coordinate '{time_coord}' is not aligned with U/V dimensions {u_dims}.")

    for axis_name, axis_label in [(lon_coord, "Longitude"), (lat_coord, "Latitude")]:
        if not name_exists_in_dataset(ds, axis_name):
            issues.append(f"{axis_label} axis '{axis_name or 'not selected'}' does not exist.")
            continue
        axis_dims = tuple(ds[axis_name].dims) if axis_name in ds.variables else (axis_name,)
        if axis_name in ds.variables and ds[axis_name].ndim == 0:
            issues.append(f"{axis_label} axis '{axis_name}' is scalar; expected 1D or 2D coordinates.")
        elif not set(axis_dims).issubset(set(u_dims)) and axis_name not in u_dims:
            issues.append(f"{axis_label} axis '{axis_name}' dims {axis_dims} are not compatible with U/V dims {u_dims}.")

    extra_dims = infer_extra_velocity_dims(ds, u_var, lon_coord, lat_coord, time_coord)
    if depth_coord:
        if not name_exists_in_dataset(ds, depth_coord):
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
    """Build compact checklist for mapped dataset variables/axes."""
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
    add_check("Longitude axis", name_exists_in_dataset(ds, lon_coord), f"Selected: {lon_coord or 'not selected'}")
    add_check("Latitude axis", name_exists_in_dataset(ds, lat_coord), f"Selected: {lat_coord or 'not selected'}")
    add_check("Time axis", name_exists_in_dataset(ds, time_coord), f"Selected: {time_coord or 'not selected'}")
    add_check("Depth axis", True if not depth_coord else name_exists_in_dataset(ds, depth_coord), f"Selected: {depth_coord or 'not required / not selected'}")
    add_check("Distinct velocity fields", bool(u_var and v_var and u_var != v_var), "U and V must point to different variables")
    add_check("Distinct spatial axes", bool(lon_coord and lat_coord and lon_coord != lat_coord), "Longitude and latitude must point to different axes")

    structure_issues = validate_dataset_structure(ds, u_var, v_var, lon_coord, lat_coord, time_coord, depth_coord)
    add_check("Structural compatibility", len(structure_issues) == 0, structure_issues[0] if structure_issues else "Selected variables and axes are structurally compatible")
    issues.extend(structure_issues)

    return pd.DataFrame(checks), issues


def build_spatial_sanity_warnings(ds, lon_coord, lat_coord):
    """Generate non-blocking warnings for suspicious coordinate ranges."""
    warnings = []

    def _axis_values(name):
        if not name_exists_in_dataset(ds, name):
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
    """Map raw exception text to concrete troubleshooting suggestions."""
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


def validate_run_semantics(ds, run_cfg):
    """Run structural and semantic checks for a single run config."""
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
    if not name_exists_in_dataset(ds, lon_coord):
        issues.append(f"Longitude axis '{lon_coord or 'not selected'}' not found.")
    if not name_exists_in_dataset(ds, lat_coord):
        issues.append(f"Latitude axis '{lat_coord or 'not selected'}' not found.")
    if not name_exists_in_dataset(ds, time_coord):
        issues.append(f"Time axis '{time_coord or 'not selected'}' not found.")
    if depth_coord and not name_exists_in_dataset(ds, depth_coord):
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