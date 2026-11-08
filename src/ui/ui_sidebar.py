"""Sidebar rendering and initialization helpers."""

import pandas as pd
import streamlit as st


def render_library_versions():
    """Render library version information in sidebar."""
    import xarray as xr
    import matplotlib
    import cartopy
    import parcels
    
    st.sidebar.header("Library Versions")
    st.sidebar.text(f"Streamlit: {st.__version__}")
    st.sidebar.text(f"Xarray: {xr.__version__}")
    st.sidebar.text(f"Matplotlib: {matplotlib.__version__}")
    st.sidebar.text(f"Cartopy: {cartopy.__version__}")
    st.sidebar.text(f"OceanParcels: {parcels.__version__}")


def render_scientific_context():
    """Render scientific context and methods documentation in sidebar."""
    st.sidebar.divider()
    st.sidebar.header("Scientific Context")
    st.sidebar.markdown(
        """
**What This App Assumes:**
- Input is a gridded hydrodynamic NetCDF dataset with velocity fields and spatial/time axes.
- Region, domain, and forcing source are determined by the uploaded dataset.

**Methods Used Here:**
- **OceanParcels:** trajectory integration framework used to advect particles through velocity fields.
- **AdvectionRK4:** fourth-order Runge-Kutta particle advection scheme.
- **Haversine Distance:** used for particle-to-station proximity analysis.

**Interpretation Note:**
- Connectivity results are physical transport indicators derived from the selected flow field and user-defined release settings.
"""
    )


def render_stations_uploader(parse_stations_csv_func):
    """
    Render sampling stations uploader and parser in sidebar.
    
    Returns:
        stations_df or None
    """
    st.sidebar.divider()
    st.sidebar.header("Sampling Stations (eDNA)")
    st.sidebar.caption(
        "Upload a station CSV or download the example template below and adapt it to your own stations."
    )
    
    # Download example template
    st.sidebar.download_button(
        label="Download Example gps.csv",
        data="StationName,Lon,Lat,Group\nStation_A,-94.1000,28.9000,Region_1\nStation_B,-94.0500,28.9500,Region_1\nStation_C,-93.9800,29.0200,Region_2\n",
        file_name="gps_example.csv",
        mime="text/csv",
        width="stretch",
    )
    
    gps_file = st.sidebar.file_uploader("Upload station CSV", type=["csv"])
    stations_df = None
    
    if gps_file is not None:
        try:
            stations_raw = pd.read_csv(gps_file)
            stations_df, stations_error = parse_stations_csv_func(stations_raw)
            
            if stations_error:
                st.sidebar.error(stations_error)
            else:
                st.sidebar.success(f"Loaded {len(stations_df)} stations.")
                if "Group" not in stations_df.columns:
                    st.sidebar.info(
                        "Optional grouping column not found. Plotting stations with a single style."
                    )
                else:
                    st.sidebar.info(
                        "Grouping enabled from optional group/category/type column."
                    )
                with st.sidebar.expander("Preview normalized station data", expanded=False):
                    st.dataframe(stations_df.head(10), width="stretch")
        except Exception as e:
            st.sidebar.error(f"Error loading CSV: {e}")
    
    return stations_df


def render_sidebar_complete(parse_stations_csv_func):
    """
    Render complete sidebar with all sections.
    
    Returns:
        stations_df or None
    """
    render_library_versions()
    render_scientific_context()
    stations_df = render_stations_uploader(parse_stations_csv_func)
    
    return stations_df
