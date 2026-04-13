import os

import pandas as pd
import streamlit as st


def render_run_history_and_comparison(
    session_state,
    max_days,
    restore_run_history_config,
    get_zarr_metadata,
    get_zarr_qc_summary,
    get_zarr_step_summary,
):
    """Render run history/restore and A/B comparison as a secondary workflow."""
    history_count = len(session_state.run_history)
    comparable_runs = [
        entry
        for entry in session_state.run_history
        if entry.get("snapshot_path") and os.path.exists(entry.get("snapshot_path"))
    ]

    st.markdown(f"### Run History ({history_count})")
    if history_count == 0:
        st.info("No saved runs yet. A run is added to history after a successful simulation.")
        return

    latest = session_state.run_history[0]
    st.caption(f"Latest: {latest['label']}")
    st.caption(f"Comparison-ready runs: {len(comparable_runs)}")

    with st.expander("Open Run History and Restore", expanded=False):
        history_labels = [entry["label"] for entry in session_state.run_history]
        selected_history_label = st.selectbox(
            "Previous Runs",
            options=history_labels,
            key="run_history_selected_label",
        )
        selected_history = next(
            entry for entry in session_state.run_history if entry["label"] == selected_history_label
        )
        st.caption(selected_history["summary"])
        hist_col1, hist_col2 = st.columns(2)
        with hist_col1:
            if st.button("Restore Selected Run", key="restore_run_history"):
                # Store config for restoration before rerun
                session_state["_pending_restore_config"] = selected_history["config"]
                session_state["_pending_restore_max_days"] = max_days
                st.rerun()
        with hist_col2:
            if st.button("Clear History", key="clear_run_history"):
                session_state.run_history = []
                st.success("Run history cleared.")

    if session_state.get("batch_last_summary"):
        with st.expander("Last Batch Summary", expanded=False):
            st.dataframe(pd.DataFrame(session_state["batch_last_summary"]), width="stretch")

    if len(comparable_runs) >= 2:
        with st.expander("Comparison Mode (A/B)", expanded=False):
            options = [f"{idx+1}. {entry['label']}" for idx, entry in enumerate(comparable_runs)]
            comp_col1, comp_col2 = st.columns(2)
            with comp_col1:
                baseline_label = st.selectbox("Baseline Run", options=options, key="comp_baseline")
            with comp_col2:
                candidate_label = st.selectbox("Candidate Run", options=options, index=1, key="comp_candidate")

            base_idx = int(baseline_label.split(".", 1)[0]) - 1
            cand_idx = int(candidate_label.split(".", 1)[0]) - 1
            base_entry = comparable_runs[base_idx]
            cand_entry = comparable_runs[cand_idx]

            base_path = base_entry.get("snapshot_path")
            cand_path = cand_entry.get("snapshot_path")
            base_meta = get_zarr_metadata(base_path, os.path.getmtime(base_path))
            cand_meta = get_zarr_metadata(cand_path, os.path.getmtime(cand_path))
            comp_max_step = max(0, min(base_meta["n_steps"], cand_meta["n_steps"]) - 1)
            comp_step = st.slider(
                "Comparison Step",
                min_value=0,
                max_value=int(comp_max_step),
                value=int(comp_max_step),
                key="comp_step",
            )

            base_qc = get_zarr_qc_summary(base_path, os.path.getmtime(base_path), comp_step)
            cand_qc = get_zarr_qc_summary(cand_path, os.path.getmtime(cand_path), comp_step)
            base_step = get_zarr_step_summary(base_path, os.path.getmtime(base_path), comp_step)
            cand_step = get_zarr_step_summary(cand_path, os.path.getmtime(cand_path), comp_step)

            compare_df = pd.DataFrame(
                [
                    {
                        "Metric": "Active Count",
                        "Baseline": base_step["active_count"],
                        "Candidate": cand_step["active_count"],
                        "Delta (C-B)": cand_step["active_count"] - base_step["active_count"],
                    },
                    {
                        "Metric": "Active Ratio (%)",
                        "Baseline": round(base_step["active_ratio_percent"], 3),
                        "Candidate": round(cand_step["active_ratio_percent"], 3),
                        "Delta (C-B)": round(cand_step["active_ratio_percent"] - base_step["active_ratio_percent"], 3),
                    },
                    {
                        "Metric": "Lost Ratio at Step (%)",
                        "Baseline": round(base_qc["current_lost_ratio"], 3),
                        "Candidate": round(cand_qc["current_lost_ratio"], 3),
                        "Delta (C-B)": round(cand_qc["current_lost_ratio"] - base_qc["current_lost_ratio"], 3),
                    },
                    {
                        "Metric": "Final Lost Ratio (%)",
                        "Baseline": round(base_qc["final_lost_ratio"], 3),
                        "Candidate": round(cand_qc["final_lost_ratio"], 3),
                        "Delta (C-B)": round(cand_qc["final_lost_ratio"] - base_qc["final_lost_ratio"], 3),
                    },
                    {
                        "Metric": "Mean Speed",
                        "Baseline": base_step["speed_mean"],
                        "Candidate": cand_step["speed_mean"],
                        "Delta (C-B)": (
                            None
                            if base_step["speed_mean"] is None or cand_step["speed_mean"] is None
                            else round(cand_step["speed_mean"] - base_step["speed_mean"], 6)
                        ),
                    },
                    {
                        "Metric": "Max Speed",
                        "Baseline": base_step["speed_max"],
                        "Candidate": cand_step["speed_max"],
                        "Delta (C-B)": (
                            None
                            if base_step["speed_max"] is None or cand_step["speed_max"] is None
                            else round(cand_step["speed_max"] - base_step["speed_max"], 6)
                        ),
                    },
                ]
            )
            st.dataframe(compare_df, width="stretch")
    elif history_count >= 2:
        st.info("Comparison Mode needs at least two snapshot-ready runs. Run two new simulations to populate snapshots.")