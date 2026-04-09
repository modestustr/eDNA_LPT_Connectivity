# Quick How To

This guide is written for day-to-day use. It focuses on what to do, not on implementation details.

## Start Here

Use this order every time:

1. Upload a hydrodynamic NetCDF file.
2. Check the detected variables and dimensions.
3. Map U, V, longitude, latitude, and time if needed.
4. Set the simulation parameters.
5. Review `Estimated Simulation Cost` and `Preflight Readiness`.
6. Run the simulation.
7. Review QC, map output, and exports.

## Upload a Dataset

Go to `1. Data Management` and upload your `.nc` file.

After upload, open `View Uploaded NetCDF File Details`.

What to look for:

- detected variables
- detected dimensions
- time coverage
- compatibility checklist
- spatial sanity warnings

If the checklist shows problems, fix them before running.
If spatial warnings appear, verify lon/lat mapping and coordinate ranges before running long simulations.

## Map Dataset Fields

If the dataset uses standard names, the app will usually configure itself automatically.

If not, select the correct names for:

1. Eastward velocity `U`
2. Northward velocity `V`
3. Longitude
4. Latitude
5. Time
6. Depth, only when the velocity fields include a vertical axis

Rules:

- U and V must be different.
- Longitude and latitude must be different.
- Time must match the velocity fields.
- Depth is optional unless the dataset is 4D.

## Choose Safe Defaults

If you are unsure, start with:

- backend: `scipy`
- particle mode: `random`
- particle count override: `0`
- random seed: `42`
- advection time step: `10` minutes
- output interval: `1` or `3` hours
- release strategy: `instant`
- sample velocity: enabled
- mesh adapter: `none` (use `flattened_grid_1d` only for flattened 1D node grids)

These settings are a good starting point for most exploratory runs.

## Mesh Adapter Quick Check

Use `flattened_grid_1d` only when all of these are true:

1. lon and lat are both 1D arrays.
2. lon and lat use the same node dimension.
3. U and V are defined on that same node dimension.
4. lon-lat node pairs are unique.
5. The nodes form a complete flattened regular grid.

If one of these fails, keep `mesh_adapter=none`.

## Check Cost Before Running

Open `Estimated Simulation Cost`.

Pay attention to:

- particle count
- dt in minutes
- steps per particle
- saved frames

Runs become expensive mainly when:

- duration is long
- dt is very small
- particle count is high
- outputs are too frequent

## Use Preflight Readiness

Open `Preflight Readiness` before clicking run.

This section shows the exact configuration that will be used. If something looks wrong there, fix it before launching the simulation.

## Run the Simulation

Click `Run Simulation`.

If the run fails, open `Suggested Fixes` under the error message and follow the guidance there.

## Read the Results

After a successful run, review these in order:

1. QC Summary
2. Map output
3. Station Analytics, if you loaded a station CSV
4. Export Actions

## Use the Map Controls

In `Visualization Controls`, the most useful settings are:

- `Time Step`
- `Map View Scope`
- `Map Detail`
- `Trajectory Point Thinning`
- `Active-Only Paths`
- `Path Window`
- `Show Velocity Overlay`

If the map feels slow:

- use `Fast Explore`
- increase thinning
- limit trajectories
- reduce path window

## Load Station Data

Use the sidebar to upload a station CSV.

If you do not have one yet, use `Download Example gps.csv` and edit it with your own stations.

Minimum columns:

- station name
- longitude
- latitude

Optional:

- group/category column

## Export Results

Use `Export Actions` to download:

- PNG map
- QC JSON
- trajectory CSV
- trajectory GeoJSON
- station metrics GeoJSON
- full ZIP bundle

Choose the ZIP bundle when you want a complete run package.

## Compare Runs

Use `Run History` and `Comparison Mode (A/B)` when you want to compare parameter changes such as:

- dt
- seed
- backend
- release strategy
- particle count

## Run a Batch

Use `Batch Execution Mode` when you want to test multiple scenarios automatically.

Each batch item can override only the values you want to change.

After the batch finishes, inspect:

- Status
- Warning
- Suggested Fix

Tip: if some batch items use mesh-formatted files, set `mesh_adapter` per run item in the JSON.

## Common Problems

### The dataset does not run

Usually this means one of these is wrong:

- U/V mapping
- longitude/latitude mapping
- time mapping
- depth mapping for 4D velocity fields

### The run is too slow

Reduce one or more of these:

- duration
- particle count
- output frequency
- very small dt

### Velocity overlay is missing

Run again with `Sample Velocity Along Trajectories` enabled.

### Batch mode shows failed runs

Read the `Suggested Fix` column first. It is the fastest way to identify the wrong field mapping or incompatible setting.

### Disk usage grows over time

The app stores per-session outputs under `runs/<session_id>/...`.
Stale session folders are cleaned automatically by the retention policy, but you can still remove old folders manually when needed.