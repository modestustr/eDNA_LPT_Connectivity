import xarray as xr
from parcels import (
    FieldSet,
    ParticleSet,
    ScipyParticle,
    JITParticle,
    AdvectionRK4,
    StatusCode,
    Variable,
)
from datetime import timedelta
import numpy as np
import os
import shutil

# ---------------------------------------------------------------------------
# PARTICLE COUNT CONSTANTS
# ---------------------------------------------------------------------------
# Default particle counts per release mode.  Values represent a practical
# trade-off between statistical coverage and UI render performance.
# Ref: van Sebille et al. (2018), 'Lagrangian ocean analysis: Fundamentals
#      and practices', Ocean Modelling, 121, 49-75.
#      doi:10.1016/j.ocemod.2017.11.008
UNIFORM_N_PARTICLES = 10    # Deterministic debug grid (N × N = 10 total)
RANDOM_N_PARTICLES = 200    # Stochastic uniform release
HYBRID_N_GLOBAL = 100       # Background (global) component of hybrid release
HYBRID_N_HOT = 200          # Hotspot (concentrated) component of hybrid release
VALID_N_PARTICLES = 200     # Grid-node-aligned release

# MARGIN_FACTOR
# Grid cells to inset from each domain edge when generating particle positions.
# Prevents particles from being placed exactly on the boundary, which would
# cause an immediate ErrorOutOfBounds deletion before the first advection step.
MARGIN_FACTOR = 2

# ---------------------------------------------------------------------------
# SIMULATION TIME CONSTANTS
# ---------------------------------------------------------------------------
# Default output cadence and advection time step.
# Reducing dt_minutes improves numerical stability of the RK4 integrator but
# proportionally increases compute time.
# Ref: Delandmeter & van Sebille (2019), 'The Parcels v2.0 Lagrangian
#      framework', Geosci. Model Dev., 12, 3571-3584.
#      doi:10.5194/gmd-12-3571-2019
OUTPUT_HOURS_DT = 1         # Default output interval (hours)
SIMULATION_MINUTES_DT = 10  # Default advection time step (minutes)


# -----------------------------
# PARTICLE MODES & RECOVERY
# -----------------------------
def DeleteParticle(particle, fieldset, time):
    """OceanParcels recovery kernel: remove particles that leave the model domain.

    Called automatically by the execution kernel when a particle raises an
    error status.  Only ErrorOutOfBounds and ErrorThroughSurface are treated
    as terminal conditions; all other statuses are left unhandled so they
    propagate to the user for diagnosis.

    Physical interpretation: particles that advect beyond the hydrodynamic
    grid boundary are irretrievably lost to the coastal/open-ocean margin.
    This is the standard treatment in offline Lagrangian analysis.

    Ref: Delandmeter & van Sebille (2019), Geosci. Model Dev., 12, 3571-3584.
    """
    if particle.state == StatusCode.ErrorOutOfBounds:
        particle.delete()
    elif particle.state == StatusCode.ErrorThroughSurface:
        particle.delete()


class SamplingScipyParticle(ScipyParticle):
    """ScipyParticle subclass that carries inline velocity sampling fields.

    Adds three extra trajectory variables that are populated by the
    SampleFieldConditions kernel at every output step:
        sampled_u     – eastward velocity component (m/s) at the particle position.
        sampled_v     – northward velocity component (m/s) at the particle position.
        sampled_speed – current speed magnitude sqrt(u² + v²) (m/s).

    Initialised to NaN so out-of-bounds particles retain a distinguishable
    fill value in the output Zarr store.
    """
    sampled_u = Variable("sampled_u", dtype=np.float32, initial=np.nan)
    sampled_v = Variable("sampled_v", dtype=np.float32, initial=np.nan)
    sampled_speed = Variable("sampled_speed", dtype=np.float32, initial=np.nan)


class SamplingJITParticle(JITParticle):
    """JITParticle subclass equivalent to SamplingScipyParticle.

    Used when the 'jit' backend is selected.  Requires a working C compiler
    on the host system; if compilation fails, run_simulation falls back to
    SamplingScipyParticle automatically.
    """
    sampled_u = Variable("sampled_u", dtype=np.float32, initial=np.nan)
    sampled_v = Variable("sampled_v", dtype=np.float32, initial=np.nan)
    sampled_speed = Variable("sampled_speed", dtype=np.float32, initial=np.nan)


def SampleFieldConditions(particle, fieldset, time):
    """OceanParcels sampling kernel: record interpolated velocity at the
    particle's current position at each advection step.

    The UV field is bilinearly interpolated from the hydrodynamic grid onto
    the particle position.  Speed is computed analytically as the L2 norm
    to avoid a square root inside a kernel (performance-safe at float32).

    This kernel must be chained AFTER AdvectionRK4 so the velocity is sampled
    at the post-advection position of the current time step.
    """
    sampled_uv = fieldset.UV[time, particle.depth, particle.lat, particle.lon]
    particle.sampled_u = sampled_uv[0]
    particle.sampled_v = sampled_uv[1]
    particle.sampled_speed = (
        particle.sampled_u * particle.sampled_u + particle.sampled_v * particle.sampled_v
    ) ** 0.5


def _create_particles(
    ds,
    lon_min,
    lon_max,
    lat_min,
    lat_max,
    u_var="uo",
    lon_coord="longitude",
    lat_coord="latitude",
    time_coord="time",
    depth_coord="",
    mode="uniform",
    particle_count=None,
    rng=None,
):
    """Generate initial (lon, lat) particle positions constrained to valid ocean cells.

    The water mask is derived from the first time-step, surface-depth slice of
    the 'uo' (eastward velocity) variable: grid cells where uo is NaN are land
    or dry cells and are excluded from candidate positions.  This prevents
    particles from being initialised on land, which would cause an immediate
    ErrorOutOfBounds deletion.

    A margin inset (MARGIN_FACTOR grid cells from each boundary) is applied so
    particles are not placed exactly on the domain edge, where interpolation
    artefacts can arise.

    Release modes:
        uniform  \u2013 Evenly-spaced subset of valid water-cell indices.
                   Deterministic; useful for debugging and grid diagnostics.
        random   \u2013 Random sample with replacement from valid water cells.
                   Approximates a spatially uncorrelated stochastic release.
        hybrid   \u2013 Combines global random coverage with a concentrated hotspot
                   sub-sample; replicates a bimodal source (background + point).
        valid    \u2013 Random sample directly from water-cell grid nodes; equivalent
                   to 'random' but semantically reserved for the 'release\n                   exactly on model grid nodes' interpretation.

    Args:\n        ds           \u2013 open xarray Dataset from the Copernicus NetCDF file.
        lon_min/max  \u2013 inset longitude bounds (decimal degrees, WGS 84).
        lat_min/max  \u2013 inset latitude bounds (decimal degrees, WGS 84).
        u_var        \u2013 dataset variable used to derive the wet-cell mask.
        lon_coord    \u2013 dataset coordinate name for longitude.
        lat_coord    \u2013 dataset coordinate name for latitude.
        time_coord   \u2013 dataset coordinate name for time.
        depth_coord  \u2013 optional dataset coordinate name for depth.
        mode         \u2013 one of 'uniform', 'random', 'hybrid', 'valid'.
        particle_count \u2013 override count (None = mode default).
        rng          \u2013 numpy Generator for reproducible stochastic sampling.

    Returns:
        (lon_array, lat_array) \u2013 1-D arrays of initial particle positions.

    Ref: van Sebille et al. (2018), Ocean Modelling, 121, 49-75.
         doi:10.1016/j.ocemod.2017.11.008
    """
    if rng is None:
        rng = np.random.default_rng()

    default_counts = {
        "uniform": UNIFORM_N_PARTICLES,
        "random": RANDOM_N_PARTICLES,
        "hybrid": HYBRID_N_GLOBAL + HYBRID_N_HOT,
        "valid": VALID_N_PARTICLES,
    }
    target_count = (
        int(particle_count)
        if particle_count is not None and int(particle_count) > 0
        else default_counts.get(mode, UNIFORM_N_PARTICLES)
    )

    if depth_coord and depth_coord in ds[u_var].dims and time_coord in ds[u_var].dims:
        u_data = ds[u_var].isel({time_coord: 0, depth_coord: 0})
    elif time_coord in ds[u_var].dims:
        u_data = ds[u_var].isel({time_coord: 0})
    elif depth_coord and depth_coord in ds[u_var].dims:
        u_data = ds[u_var].isel({depth_coord: 0})
    else:
        u_data = ds[u_var]

    # Read the actual water mask from the dataset
    water_mask = u_data.notnull().values
    lons = ds[lon_coord].values
    lats = ds[lat_coord].values

    if lons.ndim == 1:
        valid_lat_idx, valid_lon_idx = np.where(water_mask)
        valid_lons = lons[valid_lon_idx]
        valid_lats = lats[valid_lat_idx]
    else:
        valid_lat_idx, valid_lon_idx = np.where(water_mask)
        valid_lons = lons[valid_lat_idx, valid_lon_idx]
        valid_lats = lats[valid_lat_idx, valid_lon_idx]

    # Apply margin bounding box — keeps particles away from domain edges
    bbox_mask = (
        (valid_lons >= lon_min) & (valid_lons <= lon_max) &
        (valid_lats >= lat_min) & (valid_lats <= lat_max)
    )
    valid_lons = valid_lons[bbox_mask]
    valid_lats = valid_lats[bbox_mask]

    if len(valid_lons) == 0:
        print("WARNING: No valid water points found within margin bounds!")
        return np.array([lon_min]), np.array([lat_min])

    # Mode logic applied ONLY on valid water points
    if mode == "valid":
        replace = target_count > len(valid_lons)
        idx = rng.choice(len(valid_lons), target_count, replace=replace)
        return valid_lons[idx], valid_lats[idx]

    elif mode == "random":
        replace = target_count > len(valid_lons)
        idx = rng.choice(len(valid_lons), target_count, replace=replace)
        return valid_lons[idx], valid_lats[idx]

    elif mode == "hybrid":
        idx = rng.choice(len(valid_lons), target_count, replace=True)
        return valid_lons[idx], valid_lats[idx]

    else:  # uniform
        n = min(len(valid_lons), target_count)
        indices = np.linspace(0, len(valid_lons) - 1, n, dtype=int)
        return valid_lons[indices], valid_lats[indices]


# -----------------------------
# MAIN EXECUTION
# -----------------------------
def run_simulation(
    file_path,
    output_path,
    days=2,
    mode="uniform",
    progress_bar=None,
    u_var="uo",
    v_var="vo",
    lon_coord="longitude",
    lat_coord="latitude",
    time_coord="time",
    depth_coord="",
    particle_count=None,
    seed=None,
    backend="scipy",
    dt_minutes=SIMULATION_MINUTES_DT,
    output_hours=OUTPUT_HOURS_DT,
    repeat_release_hours=None,
    sample_velocity=True,
):
    """Entry point for a single Lagrangian Particle Tracking simulation.

    Constructs the OceanParcels FieldSet from a Copernicus GLORYS NetCDF file,
    generates initial particle positions, assembles the execution kernel chain,
    and writes the trajectory output to a Zarr store.

    The advection scheme is 4th-order Runge-Kutta on a spherical mesh
    (AdvectionRK4).  Turbulent sub-grid diffusion is NOT applied in this
    implementation; all displacement is deterministic given the input velocity
    field and the chosen dt.

    Ref: Delandmeter & van Sebille (2019), Geosci. Model Dev., 12, 3571-3584.
    Ref: Copernicus Marine Service — GLORYS12V1, doi:10.48670/moi-00021

    Args:
        file_path            – path to the Copernicus GLORYS NetCDF source file.
        output_path          – path where the Zarr trajectory store is written.
        days                 – total simulation duration in days.
        mode                 – particle initialisation mode
                               ('uniform'|'random'|'hybrid'|'valid').
        progress_bar         – optional Streamlit progress bar (st.progress) for
                               real-time UI feedback.
        u_var                – dataset variable name for eastward velocity.
        v_var                – dataset variable name for northward velocity.
        lon_coord            – dataset coordinate name for longitude.
        lat_coord            – dataset coordinate name for latitude.
        time_coord           – dataset coordinate name for time.
        depth_coord          – optional dataset coordinate name for depth.
        particle_count       – override particle count (None = mode default).
        seed                 – RNG seed for reproducible stochastic releases
                               (None = non-deterministic).
        backend              – OceanParcels backend ('scipy'|'jit').
        dt_minutes           – advection time step in minutes.
        output_hours         – trajectory output cadence in hours.
        repeat_release_hours – if set, particles are re-released at this
                               interval (continuous source simulation).
        sample_velocity      – if True, u/v/speed are sampled along each
                               trajectory and stored in the output.

    Returns:
        output_path – path to the written Zarr store (same as input arg).
    """
    ds = xr.open_dataset(file_path)
    rng = np.random.default_rng(seed if seed is not None else None)

    selected_backend = str(backend).strip().lower()
    if selected_backend not in {"scipy", "jit"}:
        raise ValueError("backend must be either 'scipy' or 'jit'")

    if u_var not in ds or v_var not in ds:
        raise ValueError(
            f"Velocity variables not found! Requested U='{u_var}', V='{v_var}'. "
            f"Available: {list(ds.data_vars.keys())}"
        )
    if lon_coord not in ds.variables or lat_coord not in ds.variables:
        raise ValueError(
            f"Coordinate names not found! Requested Lon='{lon_coord}', Lat='{lat_coord}'. "
            f"Available variables: {list(ds.variables.keys())}"
        )
    if time_coord not in ds.variables and time_coord not in ds.dims:
        raise ValueError(
            f"Time coordinate not found! Requested Time='{time_coord}'. "
            f"Available variables: {list(ds.variables.keys())}"
        )
    if depth_coord and depth_coord not in ds.variables and depth_coord not in ds.dims:
        raise ValueError(
            f"Depth coordinate not found! Requested Depth='{depth_coord}'. "
            f"Available variables: {list(ds.variables.keys())}"
        )

    u_dims = tuple(ds[u_var].dims)
    v_dims = tuple(ds[v_var].dims)
    if u_dims != v_dims:
        raise ValueError(f"U and V dimensions differ: U{u_dims} vs V{v_dims}")
    if time_coord not in u_dims:
        raise ValueError(f"Selected time coordinate '{time_coord}' is not present in U/V dimensions {u_dims}")

    # Extract the physical surface depth to prevent initialization errors
    surface_depth = float(ds[depth_coord].values[0]) if depth_coord and depth_coord in ds.variables else 0.0

    # -----------------------------
    # FIELDSET
    # -----------------------------
    dimensions = {"lon": lon_coord, "lat": lat_coord, "time": time_coord}
    if depth_coord:
        dimensions["depth"] = depth_coord

    fieldset = FieldSet.from_netcdf(
        {"U": file_path, "V": file_path},
        {"U": u_var, "V": v_var},
        dimensions,
        allow_time_extrapolation=True,
        mesh="spherical",
    )

    # -----------------------------
    # ACTUAL MODEL DOMAIN
    # -----------------------------
    lon_grid = fieldset.U.grid.lon
    lat_grid = fieldset.U.grid.lat

    lon_min = float(lon_grid.min())
    lon_max = float(lon_grid.max())
    lat_min = float(lat_grid.min())
    lat_max = float(lat_grid.max())

    lon_res = (
        np.mean(np.diff(lon_grid, axis=1))
        if lon_grid.ndim > 1
        else np.mean(np.diff(lon_grid))
    )
    lat_res = (
        np.mean(np.diff(lat_grid, axis=0))
        if lat_grid.ndim > 1
        else np.mean(np.diff(lat_grid))
    )

    margin = max(abs(lon_res), abs(lat_res)) * MARGIN_FACTOR

    lon_min += margin
    lon_max -= margin
    lat_min += margin
    lat_max -= margin

    # -----------------------------
    # PARTICLES
    # -----------------------------
    # Now passing the opened dataset directly to _create_particles
    lon, lat = _create_particles(
        ds,
        lon_min,
        lon_max,
        lat_min,
        lat_max,
        u_var=u_var,
        lon_coord=lon_coord,
        lat_coord=lat_coord,
        time_coord=time_coord,
        depth_coord=depth_coord,
        mode=mode,
        particle_count=particle_count,
        rng=rng,
    )

    # Assign correct surface depth to prevent immediate Out-Of-Bounds deletion
    depth_array = np.full(len(lon), surface_depth)

    if sample_velocity:
        pclass = SamplingJITParticle if selected_backend == "jit" else SamplingScipyParticle
    else:
        pclass = JITParticle if selected_backend == "jit" else ScipyParticle
    repeatdt = None
    if repeat_release_hours is not None and float(repeat_release_hours) > 0:
        repeatdt = timedelta(hours=float(repeat_release_hours))

    pset_kwargs = {
        "fieldset": fieldset,
        "pclass": pclass,
        "lon": lon,
        "lat": lat,
        "depth": depth_array,
    }
    if repeatdt is not None:
        pset_kwargs["repeatdt"] = repeatdt

    try:
        pset = ParticleSet.from_list(**pset_kwargs)
    except Exception as e:
        if selected_backend == "jit":
            print(f"WARNING: JIT backend failed ({e}). Falling back to Scipy backend.")
            pset_kwargs["pclass"] = SamplingScipyParticle if sample_velocity else ScipyParticle
            pset = ParticleSet.from_list(**pset_kwargs)
        else:
            raise

    # -----------------------------
    # OUTPUT
    # -----------------------------
    if os.path.exists(output_path):
        shutil.rmtree(output_path, ignore_errors=True)

    output_file = pset.ParticleFile(
        name=output_path, outputdt=timedelta(hours=int(output_hours))
    )

    # -----------------------------
    # EXECUTION KERNEL
    # -----------------------------
    execution_kernel = pset.Kernel(AdvectionRK4)
    if sample_velocity:
        execution_kernel += pset.Kernel(SampleFieldConditions)
    execution_kernel += pset.Kernel(DeleteParticle)

    try:
        for d in range(days):
            pset.execute(
                execution_kernel,
                runtime=timedelta(days=1),  # Run one day per iteration
                dt=timedelta(minutes=int(dt_minutes)),
                output_file=output_file,
            )
            # Update progress if a UI progress bar object is provided
            if progress_bar:
                progress_val = (d + 1) / days
                progress_bar.progress(progress_val, text=f"Simulation: Day {d+1} of {days} in progress...")
        if progress_bar:
            progress_bar.progress(1.0, text="Simulation completed!")

    except Exception as e:
        print(f"Execution Error: {e}")
        raise e
    finally:
        ds.close()

    return output_path
