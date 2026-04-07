import xarray as xr
from parcels import FieldSet, ParticleSet, ScipyParticle, AdvectionRK4, StatusCode
from datetime import timedelta
import numpy as np
import os
import shutil

# Constants for particle generation
UNIFORM_N_PARTICLES = 10
RANDOM_N_PARTICLES = 200
HYBRID_N_GLOBAL = 100
HYBRID_N_HOT = 200
VALID_N_PARTICLES = 200
MARGIN_FACTOR = 2

# Simulation constants
OUTPUT_HOURS_DT = 1
SIMULATION_MINUTES_DT = 10

# -----------------------------
# USER INFO
# -----------------------------
print("\n===== USER NOTICE =====")
print("This simulation requires 'uo' and 'vo' velocity fields.")
print("If particles go out-of-bounds, this is expected physical behavior.")
print("Not an error in the code.")


# -----------------------------
# PARTICLE MODES & RECOVERY
# -----------------------------
def DeleteParticle(particle, fieldset, time):
    """
    Checks the particle state and deletes ONLY if it throws a boundary error.
    """
    if particle.state == StatusCode.ErrorOutOfBounds:
        particle.delete()
    elif particle.state == StatusCode.ErrorThroughSurface:
        particle.delete()


def _create_particles(ds, lon_min, lon_max, lat_min, lat_max, mode="uniform"):
    """
    Creates initial particle positions by reading the actual water mask directly
    from the NetCDF dataset to prevent spawning on land.
    """
    if "depth" in ds["uo"].dims:
        u_data = ds["uo"].isel(time=0, depth=0)
    else:
        u_data = ds["uo"].isel(time=0)

    # Read the actual water mask from the dataset
    water_mask = u_data.notnull().values
    lons = ds["longitude"].values
    lats = ds["latitude"].values

    if lons.ndim == 1:
        valid_lat_idx, valid_lon_idx = np.where(water_mask)
        valid_lons = lons[valid_lon_idx]
        valid_lats = lats[valid_lat_idx]
    else:
        valid_lat_idx, valid_lon_idx = np.where(water_mask)
        valid_lons = lons[valid_lat_idx, valid_lon_idx]
        valid_lats = lats[valid_lat_idx, valid_lon_idx]

    if len(valid_lons) == 0:
        print("WARNING: No valid water points found!")
        return np.array([lon_min]), np.array([lat_min])

    # Mode logic applied ONLY on valid water points
    if mode == "valid":
        idx = np.random.choice(
            len(valid_lons), min(len(valid_lons), VALID_N_PARTICLES), replace=False
        )
        return valid_lons[idx], valid_lats[idx]

    elif mode == "random":
        idx = np.random.choice(
            len(valid_lons), min(len(valid_lons), RANDOM_N_PARTICLES), replace=False
        )
        return valid_lons[idx], valid_lats[idx]

    elif mode == "hybrid":
        idx = np.random.choice(
            len(valid_lons),
            min(len(valid_lons), HYBRID_N_GLOBAL + HYBRID_N_HOT),
            replace=True,
        )
        return valid_lons[idx], valid_lats[idx]

    else:  # uniform
        n = min(len(valid_lons), UNIFORM_N_PARTICLES)
        indices = np.linspace(0, len(valid_lons) - 1, n, dtype=int)
        return valid_lons[indices], valid_lats[indices]


# -----------------------------
# MAIN EXECUTION
# -----------------------------
def run_simulation(file_path, output_path, days=2, mode="uniform", progress_bar=None):
    """
    Runs the Lagrangian Particle Tracking simulation.
    """
    ds = xr.open_dataset(file_path)

    if "uo" not in ds or "vo" not in ds:
        raise ValueError(
            f"Velocity variables not found! Available: {list(ds.data_vars.keys())}"
        )

    # Extract the physical surface depth to prevent initialization errors
    surface_depth = float(ds["depth"].values[0]) if "depth" in ds.dims else 0.0

    # -----------------------------
    # FIELDSET
    # -----------------------------
    dimensions = {"lon": "longitude", "lat": "latitude", "time": "time"}
    if "depth" in ds.sizes or "depth" in ds.coords:
        dimensions["depth"] = "depth"

    fieldset = FieldSet.from_netcdf(
        {"U": file_path, "V": file_path},
        {"U": "uo", "V": "vo"},
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
    lon, lat = _create_particles(ds, lon_min, lon_max, lat_min, lat_max, mode)

    # Assign correct surface depth to prevent immediate Out-Of-Bounds deletion
    depth_array = np.full(len(lon), surface_depth)

    pset = ParticleSet.from_list(
        fieldset=fieldset, pclass=ScipyParticle, lon=lon, lat=lat, depth=depth_array
    )

    # -----------------------------
    # OUTPUT
    # -----------------------------
    if os.path.exists(output_path):
        shutil.rmtree(output_path, ignore_errors=True)

    output_file = pset.ParticleFile(
        name=output_path, outputdt=timedelta(hours=OUTPUT_HOURS_DT)
    )

    # -----------------------------
    # EXECUTION KERNEL
    # -----------------------------
    execution_kernel = pset.Kernel(AdvectionRK4) + pset.Kernel(DeleteParticle)

    try:
        for d in range(days):
            pset.execute(
                execution_kernel,
                runtime=timedelta(days=1),  # Her seferinde 1 gün
                dt=timedelta(minutes=SIMULATION_MINUTES_DT),
                output_file=output_file,
            )
            # Eğer arayüzden bir progress_bar objesi gelmişse güncelle
            if progress_bar:
                progress_val = (d + 1) / days
                progress_bar.progress(progress_val, text=f"Simulation: Day {d+1} of {days} in progress...")
        if progress_bar:
            progress_bar.progress(1.0, text="Simulation completed!")

    except Exception as e:
        print(f"Execution Error: {e}")
        raise e

    ds.close()

    return output_path
