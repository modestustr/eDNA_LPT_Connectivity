# eDNA LPT Connectivity Dashboard

This application runs and visualizes Lagrangian Particle Tracking (LPT) experiments from hydrodynamic NetCDF files and compares the results with eDNA sampling stations.

The interface is designed so a user can:

1. Upload a current-field dataset.
2. Map velocity variables and coordinates if the dataset uses non-standard names.
3. Run a particle simulation.
4. Inspect trajectories, speed, QC metrics, and station connectivity.
5. Export figures, CSV files, and JSON summaries.
6. Compare multiple runs and execute parameter batches.

## 1. What This App Does

The app uses OceanParcels to advect passive particles through a velocity field.

Scientifically, this means:

- Particles move with the hydrodynamic currents.
- Each particle represents a passive tracer or potential transport pathway.
- The resulting trajectories are used as a physical connectivity proxy between sampling locations.

Core method references:

- Delandmeter, P. and van Sebille, E. (2019). The Parcels v2.0 Lagrangian framework. Geoscientific Model Development, 12, 3571-3584. doi:10.5194/gmd-12-3571-2019
- van Sebille, E. et al. (2018). Lagrangian ocean analysis: Fundamentals and practices. Ocean Modelling, 121, 49-75. doi:10.1016/j.ocemod.2017.11.008
- Cowen, R.K. et al. (2006). Scaling of connectivity in marine populations. Science, 311(5760), 522-527. doi:10.1126/science.1122039

## 2. Quick Start

Follow these steps in order.

### Step 1. Upload a NetCDF File

Use the `Upload hydrodynamic NetCDF (.nc)` control in the `Data Management` section.

After upload, open `View Uploaded NetCDF File Details`.

This panel shows:

- detected variables
- detected dimensions
- time coverage
- a compatibility checklist

### Step 2. Confirm or Map Dataset Fields

If your dataset already uses the standard names below, the app configures itself automatically:

- U velocity: `uo`
- V velocity: `vo`
- longitude coordinate: `longitude`
- latitude coordinate: `latitude`

If these names are missing, the app asks you to map them manually.

You must provide:

1. `Eastward Velocity Variable (U)`
2. `Northward Velocity Variable (V)`
3. `Longitude Coordinate`
4. `Latitude Coordinate`
5. `Time Coordinate`
6. `Depth Coordinate` when the velocity fields contain a vertical axis

Important rules:

- U and V must be different variables.
- Longitude and latitude must be different coordinates.
- Time must align with the selected velocity fields.
- Depth should be selected when the velocity fields are 4D.
- All selected names must exist in the uploaded dataset.

### Step 3. Review the Compatibility Checklist

Before running, check the `Compatibility Checklist` panel.

This tells you whether the dataset is ready and what still needs attention.

It also shows non-blocking `Spatial Sanity Warnings` (for example suspicious lon/lat ranges or non-monotonic 1D axes).

### Step 4. Choose Simulation Parameters

In `Simulation Parameters`, choose:

- particle mode
- backend
- mesh adapter
- duration
- particle count override
- random seed
- advection time step
- output interval
- release strategy
- velocity sampling on or off

### Step 5. Inspect the Cost Estimate

Open `Estimated Simulation Cost`.

This panel shows:

- number of particles
- time step
- steps per particle
- saved frames
- approximate workload

Use it before long runs.

### Step 6. Review the Preflight Readiness Panel

Open `Preflight Readiness` before clicking run.

This panel shows the exact configuration that will be used for the next simulation.

### Step 7. Run the Simulation

Click `Run Simulation`.

The app will:

- execute the OceanParcels run
- save output to a Zarr store
- copy a snapshot into the current session's `runs/<session_id>/snapshots/` folder when disk space allows
- add the run to history

## 3. Dataset Requirements

### Required Content

Your NetCDF dataset should contain:

- an eastward velocity variable
- a northward velocity variable
- longitude coordinate
- latitude coordinate
- time coordinate named `time`

Depth is optional in the current workflow. If depth exists, the first surface level is used.

### Coordinate System

The app assumes geographic coordinates in decimal degrees, consistent with WGS 84 style longitude and latitude arrays.

### Wet Mask Logic

Particles are only initialized over water cells.

The water mask is inferred from valid values in the selected U variable at the first time step.

This prevents particles from being spawned on land.

## 4. Simulation Controls Explained

### Particle Modes

`uniform`

- deterministic placement
- useful for debugging grid behavior

`random`

- random release over valid wet cells
- good default for exploratory runs

`hybrid`

- mixed release strategy
- useful when you want broader background coverage with concentration

`valid`

- samples from valid grid nodes directly
- useful for grid-aligned releases

### Backend

`scipy`

- safest default
- recommended unless you specifically need JIT

`jit`

- can be faster
- requires a working C compiler

### Mesh Adapter

`none`

- default path for standard rectilinear/curvilinear datasets

`flattened_grid_1d`

- adapts datasets where lon/lat are provided as 1D node coordinates and U/V are stored on the same node dimension
- reshapes flattened node fields into a regular `(lat, lon)` grid before simulation

Quick suitability checklist for `flattened_grid_1d`:

| Check | Expected |
|---|---|
| Lon/lat coordinate rank | Both are 1D |
| Lon/lat node dimension | Same dimension name (for example `node`) |
| U/V include node dimension | Yes |
| Unique lon-lat pairs | No duplicates |
| Flattened grid completeness | `n_unique_lon * n_unique_lat == n_nodes` |

If any check fails, keep `mesh_adapter=none` (or use a future adapter designed for that mesh family).

### Sample Velocity Along Trajectories

When enabled, the app stores:

- sampled eastward velocity
- sampled northward velocity
- speed magnitude

This should generally stay enabled because it powers:

- velocity overlay on the map
- speed QC metrics
- speed fields in CSV export
- better comparison across runs

## 5. Visualization Workflow

After a successful run, use `Visualization Controls`.

You can adjust:

- time step
- map extent
- map detail
- trajectory thinning
- active-only paths
- trajectory cap
- path window
- station labels
- velocity overlay

### Velocity Overlay

If velocity sampling was enabled during simulation, `Show Velocity Overlay` colors trajectories and final particle positions by speed.

The color scale is shared across both layers so the legend is consistent.

## 6. QC Summary

The QC panel reports:

- initially released particles
- inactive or lost particles at the selected step
- loss ratios
- final active and final lost counts
- current survival ratio

In this app, a particle is treated as lost when it exits the model domain and is deleted by the recovery kernel.

This is expected behavior, not necessarily a numerical error.

## 7. Station Analytics

If you upload a station CSV in the sidebar, the app can compute:

- entries within a station radius
- entries at the selected step
- first-arrival timing statistics
- a first-to-last station connectivity matrix

Implementation note:

- Proximity queries use `scipy.spatial.cKDTree` when SciPy is available for faster large-run analytics.
- If SciPy is unavailable, the app automatically falls back to the Haversine-based method.

### Station CSV Format

You can download an example station template directly from the app sidebar using `Download Example gps.csv`.

Required columns, using any common alias form:

- station name
- longitude
- latitude

Optional:

- group or category column

Examples of accepted column names include:

- `StationName`, `station`, `name`
- `lon`, `longitude`, `x`
- `lat`, `latitude`, `y`
- `group`, `category`, `type`, `region`

## 8. Run History and Comparison

Every successful run is stored in session history.

You can:

- restore a previous run configuration
- compare two snapshot-ready runs
- inspect delta metrics at a selected time step

Comparison mode is useful for testing changes in:

- seed
- timestep
- backend
- release mode
- particle count

## 9. Batch Execution Mode

Batch mode lets you run multiple parameter sets sequentially.

Each JSON object may override only the values you want to change.

Supported fields:

- `name`
- `use_full`
- `days`
- `mode`
- `u_var`
- `v_var`
- `lon_coord`
- `lat_coord`
- `time_coord`
- `depth_coord`
- `mesh_adapter`
- `particle_count`
- `seed`
- `backend`
- `dt_minutes`
- `output_hours`
- `release_mode`
- `repeat_release_hours`
- `sample_velocity`

Example:

```json
[
  {
    "name": "Baseline",
    "days": 2,
    "mode": "random"
  },
  {
    "name": "Smaller dt",
    "days": 2,
    "mode": "random",
    "dt_minutes": 5
  }
]
```

The batch summary table reports:

- success or failure
- runtime
- trajectory count
- saved steps
- warning text
- suggested fix for failed runs

Before execution, the app also generates a `Batch Preflight Report`.
Runs that fail semantic compatibility checks are marked invalid and skipped, while valid runs continue.

## 10. Export Options

In `Export Actions`, you can download:

- PNG map
- QC JSON
- trajectory CSV
- trajectory GeoJSON
- station metrics GeoJSON
- export bundle ZIP

The export bundle includes:

- rendered map image
- trajectory CSV, when available
- trajectory GeoJSON, when available
- station metrics GeoJSON, when station analytics is available
- `qc_summary.json`
- `run_params.json`

## 11. Troubleshooting

### Problem: The app says U/V variables are missing

Fix:

- open `View Uploaded NetCDF File Details`
- manually map the correct velocity variables

### Problem: Longitude/latitude are missing

Fix:

- map the correct coordinate names in the same panel

### Problem: The run starts but results look geographically suspicious

Fix:

- review `Spatial Sanity Warnings` in the Compatibility Checklist
- verify lon/lat mapping and expected coordinate ranges
- verify that 1D lon/lat axes are monotonic when required by interpolation assumptions

### Problem: The run is unexpectedly slow

Check:

- `Use full dataset duration`
- very small `dt_minutes`
- high particle count
- velocity sampling
- very frequent output interval

### Problem: JIT fails

Fix:

- switch backend to `scipy`

### Problem: Snapshot copy is skipped

Cause:

- low disk space

Fix:

- clean old outputs in `runs/<session_id>/snapshots/`
- free disk space

### Problem: Velocity overlay is unavailable

Cause:

- the simulation was run without `Sample Velocity Along Trajectories`

Fix:

- rerun with velocity sampling enabled

## 12. Output Files and Folders

Important folders created by the app:

- `runs/<session_id>/upload_cache/` — cached uploaded NetCDF files for the current session
- `runs/<session_id>/outputs/` — unique per-run simulation outputs (`*.zarr`)
- `runs/<session_id>/snapshots/` — snapshot copies used by run history and comparison mode

Lifecycle note:

- stale session folders are cleaned automatically using a time-based retention policy.

## 13. Recommended Default Workflow

For most users, this is the safest workflow:

1. Upload NetCDF.
2. Confirm or map U, V, lon, lat.
3. Keep backend as `scipy`.
4. Start with `random` mode.
5. Keep `Sample Velocity Along Trajectories` enabled.
6. Use `dt_minutes = 10` and `output_hours = 1` or `3`.
7. Run a short test first.
8. Inspect QC and visualization.
9. Only then scale up duration or particle count.

## 14. Future Extension Notes

The current app already supports flexible mapping for U, V, longitude, and latitude.

If a new dataset family uses non-standard time or depth names, the next natural extension is adding `time` and `depth` mapping with the same UI pattern.