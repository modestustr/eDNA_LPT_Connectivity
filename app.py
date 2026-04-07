import streamlit as st
import xarray as xr
import matplotlib
import matplotlib.pyplot as plt
import cartopy
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import os
import tempfile
import parcels
import numpy as np
import pandas as pd

from core_lpt import run_simulation


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

st.sidebar.header("Scientific References")
st.sidebar.markdown(
    """
**Data Sources:**
- **Hydrodynamic Forcing:** Copernicus Marine Service (GLORYS Global Ocean Physics Reanalysis).
- **Spatial Coverage:** Texas-Louisiana Shelf.

**Methodology & Frameworks:**
- **OceanParcels:** A flexible set of Python classes and methods designed to create customizable particle tracking simulations.
- **Numerical Evidence:** Stochastic displacement based on $K_h = 1.0 m^2/s$ to account for unresolved turbulent scales.
"""
)
# -----------------------------
# SIDEBAR: SAMPLING STATIONS LOADER
# -----------------------------
st.sidebar.divider()
st.sidebar.header("Sampling Stations (eDNA)")
gps_file = st.sidebar.file_uploader("Upload gps.csv", type=["csv"])
stations_df = None
if gps_file is not None:
    try:
        stations_df = pd.read_csv(gps_file)
        st.sidebar.success(f"Loaded {len(stations_df)} stations.")
    except Exception as e:
        st.sidebar.error(f"Error loading CSV: {e}")

# -----------------------------
# MAIN PAGE: HEADER & OVERVIEW
# -----------------------------
st.title("Lagrangian Particle Tracking (LPT) Connectivity Dashboard")
st.subheader("May 2021 Hydrodynamic Event Analysis")

st.markdown(
    """
### Project Overview
This application visualizes the transport of passive particles during the specific **storm pulses of May 2021**. 
By using high-resolution hindcast data from the **Copernicus GLORYS** reanalysis model, we analyze 
potential connectivity between different benthic regions on the Texas Shelf.

**Key Research Objectives:**
- Evaluate particle transport pathways between 9 Fathom Rocks and 7.5 Fathom Bank.
- Quantify the physical mechanisms (current reversals) driving biological dispersal.
- Provide physical evidence for eDNA taxonomic diversity observed in samples.
"""
)

st.divider()

# -----------------------------
# MAIN PAGE: DATA MANAGEMENT
# -----------------------------
st.header("1. Data Management")
uploaded_file = st.file_uploader("Upload Copernicus .nc file", type=["nc"])

ZARR_PATH = "output.zarr"
tmp_path = None
days = 2
valid_data = False  # Flag to control simulation execution
particle_backend = "scipy"
particle_count_override = 0
random_seed = 0
dt_minutes = 10
output_hours = 1

# -----------------------------
# FILE HANDLING, VALIDATION & METADATA
# -----------------------------
if uploaded_file is not None:
    temp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(temp_dir, uploaded_file.name)
    with open(tmp_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

if uploaded_file and tmp_path:
    # Open dataset to validate contents
    ds_temp = xr.open_dataset(tmp_path)

    # Check for required velocity variables
    has_uo = "uo" in ds_temp.data_vars
    has_vo = "vo" in ds_temp.data_vars
    valid_data = has_uo and has_vo

    with st.expander("View Uploaded NetCDF File Details", expanded=True):
        st.markdown("**Detected Variables:**")
        st.code(", ".join(list(ds_temp.data_vars.keys())))

        if not valid_data:
            st.error(
                "Critical Error: Expected velocity variables ('uo' and 'vo') are missing. "
                "This file is not compatible with Lagrangian Particle Tracking."
            )
        else:
            st.success(
                "Velocity fields ('uo', 'vo') detected. Ready for simulation."
            )

        st.markdown("**Detected Dimensions:**")
        st.code(str(dict(ds_temp.sizes)))

        if "time" in ds_temp.coords:
            start_time = str(ds_temp.time.values[0])[:19]
            end_time = str(ds_temp.time.values[-1])[:19]
            st.markdown("**Time Coverage:**")
            st.info(f"{start_time} to {end_time}")

    if valid_data:
        st.header("2. Simulation Parameters")
        max_days = max(1, len(ds_temp.time) - 1) if hasattr(ds_temp, "sizes") else 2
        use_full = st.checkbox("Use full dataset duration", value=True)
        days = (
            max_days
            if use_full
            else st.slider(
                "Simulation Duration (days)", 1, int(max_days), min(2, int(max_days))
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
        "Particle Mode", ["uniform", "random", "hybrid", "valid"]
    )
    # Display mode-specific information
    st.warning(
        "USER NOTICE: This simulation requires 'uo' and 'vo' velocity fields. "
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
            "**Particle Count (N=200):** Ensures particles start exactly on Copernicus data nodes."
        )

    st.markdown("---")
    st.markdown(
        "### Numerical Rationale\n"
        "Particle counts are constrained by **Web-UI Rendering Limits** to ensure interactive frame rates."
    )

    with st.expander("Advanced Simulation Settings", expanded=False):
        particle_backend = st.selectbox(
            "Backend",
            ["scipy", "jit"],
            help="scipy is generally more compatible; jit can be faster depending on the environment.",
        )
        particle_count_override = st.number_input(
            "Particle Count Override (0 = mode default)",
            min_value=0,
            value=0,
            step=10,
        )
        random_seed = st.number_input(
            "Random Seed (0 = random)",
            min_value=0,
            value=0,
            step=1,
        )
        dt_minutes = st.slider(
            "Advection Time Step (minutes)", min_value=1, max_value=60, value=10
        )
        output_hours = st.slider(
            "Output Interval (hours)", min_value=1, max_value=24, value=1
        )

    run_button = st.button("Run Simulation", type="primary")

    # -----------------------------
    # EXECUTION
    # -----------------------------
    if run_button and tmp_path is not None:
        # Using st.status to mimic the terminal logging behavior
        with st.status(
            "Running Lagrangian Particle Tracking...", expanded=True
        ) as status:
            my_bar = st.progress(0, text="Initializing simulation...")
            try:
                ZARR_PATH = run_simulation(
                    tmp_path,
                    ZARR_PATH,
                    days=days,
                    mode=particle_mode,
                    progress_bar=my_bar,
                    particle_count=(
                        int(particle_count_override)
                        if int(particle_count_override) > 0
                        else None
                    ),
                    seed=(int(random_seed) if int(random_seed) > 0 else None),
                    backend=particle_backend,
                    dt_minutes=int(dt_minutes),
                    output_hours=int(output_hours),
                )

                status.update(
                    label="Success! Simulation Finished",
                    state="complete",
                    expanded=False,
                )

                st.success(
                    "Simulation finished. You can now adjust visualization controls below."
                )
            except Exception as e:
                st.error(f"Simulation failed: {e}")
                status.update(label="Simulation Failed", state="error")
# -----------------------------
# VISUALIZATION
# -----------------------------
st.divider()
st.header("Results Visualization")
if os.path.exists(ZARR_PATH):
    try:
        ds = xr.open_zarr(ZARR_PATH)
        n_steps = ds.lon.shape[1]

        if n_steps > 1:
            st.header("3. Visualization Controls")

            view_option = st.radio(
                "Map View Scope",
                ["Focus on Particles (Zoom In)", "Full Dataset Domain (Zoom Out)"],
                horizontal=True,
            )
            step = st.slider(
                "Time Step (Hours since start)",
                min_value=0,
                max_value=n_steps - 1,
                value=n_steps - 1,
                step=1,
            )

            # col1, col2, col3 = st.columns(3)
            # with col1:
            #     current_time = (
            #         str(ds.time[0, step].values)[:19] if "time" in ds else "N/A"
            #     )
            #     st.metric("Current Timestamp", current_time)
            # with col2:
            #     n_particles = ds.lon.shape[0]
            #     st.metric("Total Particles Tracked", n_particles)
            # with col3:
            #     st.metric("Transport Duration", f"{step} Hours")

            fig = plt.figure(figsize=(14, 9))
            ax = plt.axes(projection=ccrs.PlateCarree())
            ax.add_feature(cfeature.COASTLINE.with_scale("10m"), linewidth=1)
            ax.add_feature(
                cfeature.LAND.with_scale("10m"), facecolor="#f0f0f0", edgecolor="black"
            )
            ax.add_feature(cfeature.STATES.with_scale("10m"), linestyle=":", alpha=0.5)

            # -----------------------------
            # EXTENT CALCULATION (ZOOM LOGIC)
            # -----------------------------
            if view_option == "Focus on Particles (Zoom In)":
                # Current logic: tight crop on active particles
                flat_lon = ds.lon.values.flatten()
                flat_lat = ds.lat.values.flatten()
                valid_lon = flat_lon[np.isfinite(flat_lon)]
                valid_lat = flat_lat[np.isfinite(flat_lat)]
                if len(valid_lon) > 0:
                    ax.set_extent(
                        [
                            valid_lon.min(),
                            valid_lon.max(),
                            valid_lat.min(),
                            valid_lat.max(),
                        ],
                        crs=ccrs.PlateCarree(),
                    )
            else:
                # Zoom Out: Use the original NetCDF domain boundaries
                if tmp_path and os.path.exists(tmp_path):
                    with xr.open_dataset(tmp_path) as ds_orig:
                        ax.set_extent(
                            [
                                float(ds_orig.longitude.min()),
                                float(ds_orig.longitude.max()),
                                float(ds_orig.latitude.min()),
                                float(ds_orig.latitude.max()),
                            ],
                            crs=ccrs.PlateCarree(),
                        )
            # -----------------------------
            # PLOTTING TRAJECTORIES
            # -----------------------------
            for i in range(ds.sizes["trajectory"]):
                lon_vals = ds.lon[i, : step + 1].values
                lat_vals = ds.lat[i, : step + 1].values

                # FIX: Stricter finite check to suppress Shapely/Pyproj warnings
                mask = np.isfinite(lon_vals) & np.isfinite(lat_vals)
                if not np.any(mask):
                    continue

                clean_lon = lon_vals[mask]
                clean_lat = lat_vals[mask]

                if len(clean_lon) < 2:
                    continue

                ax.plot(
                    clean_lon,
                    clean_lat,
                    color="blue",
                    alpha=0.3,
                    transform=ccrs.PlateCarree(),
                    linewidth=1,
                )
                ax.scatter(
                    clean_lon[-1],
                    clean_lat[-1],
                    color="red",
                    s=10,
                    transform=ccrs.PlateCarree(),
                    zorder=5,
                )

            # -----------------------------
            # PLOT STATIONS (ADDITION)
            # -----------------------------
            if stations_df is not None:
                for _, row in stations_df.iterrows():
                    zone_type = str(row["BayOrGulf"]).strip().lower()
                    m_style = "o" if zone_type == "bay" else "^"
                    m_color = "green" if zone_type == "bay" else "magenta"
                    m_label = "Bay (Inner)" if zone_type == "bay" else "Gulf (Outer)"

                    ax.scatter(
                        row["Lon"],
                        row["Lat"],
                        color=m_color,
                        marker=m_style,
                        s=80,
                        edgecolors="white",
                        transform=ccrs.PlateCarree(),
                        zorder=10,
                        label=m_label,
                    )
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

                handles, labels = ax.get_legend_handles_labels()
                by_label = dict(zip(labels, handles))
                if by_label:
                    ax.legend(by_label.values(), by_label.keys(), loc="lower right")

            st.pyplot(fig, width="stretch")
        else:
            st.warning("Only initial state exists. Simulation steps were not recorded.")
        ds.close()

    except Exception as e:
        st.error(f"Display error: {e}")
else:
    if uploaded_file is None:
        st.info("Upload a file and run simulation to see results.")
    elif not valid_data:
        st.info("Ensure valid NetCDF is uploaded to begin.")
