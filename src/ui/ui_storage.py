import hashlib
import os
import shutil

import streamlit as st

from src.ui.ui_session import cleanup_stale_runtime_sessions, init_session_id


APP_ROOT = os.path.dirname(os.path.abspath(__file__))
RUNS_ROOT = os.path.join(APP_ROOT, "runs")


def _human_bytes(n_bytes):
    """Convert a raw byte count to a human-readable string."""
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(max(0, n_bytes))
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024


def _get_path_size_bytes(path):
    """Return total size in bytes of file or directory tree."""
    if not os.path.exists(path):
        return 0
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _, files in os.walk(path):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                total += os.path.getsize(fpath)
            except OSError:
                continue
    return total


def _get_free_space_bytes(path):
    """Return free disk space in bytes for volume containing path."""
    target = path if os.path.isdir(path) else os.path.dirname(path) or "."
    return shutil.disk_usage(target).free


def get_or_cache_uploaded_file(uploaded_file, session_state, ensure_runtime_paths):
    """Persist uploaded file in session cache and return local path."""
    runtime = ensure_runtime_paths()
    cache_dir = runtime["upload_cache_dir"]
    os.makedirs(cache_dir, exist_ok=True)

    signature = f"{uploaded_file.name}:{uploaded_file.size}"
    cached_path = session_state.get("upload_cached_path")
    cached_sig = session_state.get("upload_signature")
    if cached_path and cached_sig == signature and os.path.exists(cached_path):
        return cached_path, None

    required = int(uploaded_file.size)
    free = _get_free_space_bytes(cache_dir)
    safety_margin = 200 * 1024 * 1024
    if free < (required + safety_margin):
        return None, (
            "Insufficient disk space to cache uploaded file. "
            f"Required at least {_human_bytes(required + safety_margin)}, free {_human_bytes(free)}."
        )

    ext = os.path.splitext(uploaded_file.name)[1] or ".nc"
    sig_hash = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]
    target_path = os.path.join(cache_dir, f"upload_{sig_hash}{ext}")
    tmp_write_path = target_path + ".tmp"
    try:
        with open(tmp_write_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        os.replace(tmp_write_path, target_path)
    finally:
        if os.path.exists(tmp_write_path):
            try:
                os.remove(tmp_write_path)
            except OSError:
                pass

    old_path = session_state.get("upload_cached_path")
    if old_path and old_path != target_path and os.path.exists(old_path):
        try:
            os.remove(old_path)
        except OSError:
            pass

    session_state["upload_cached_path"] = target_path
    session_state["upload_signature"] = signature
    return target_path, None


def snapshot_run_output(output_path, run_id, ensure_runtime_paths):
    """Copy run output to per-session snapshot folder for later comparison."""
    runtime = ensure_runtime_paths()
    snapshots_root = runtime["snapshots_dir"]
    os.makedirs(snapshots_root, exist_ok=True)
    safe_id = str(run_id).replace(":", "-").replace(" ", "_")
    snapshot_path = os.path.join(snapshots_root, f"{safe_id}.zarr")
    required = _get_path_size_bytes(output_path)
    free = _get_free_space_bytes(snapshots_root)
    if free < (required + 100 * 1024 * 1024):
        return None, (
            "Skipped snapshot copy due to low disk space. "
            f"Need {_human_bytes(required + 100 * 1024 * 1024)}, free {_human_bytes(free)}."
        )
    if os.path.exists(snapshot_path):
        shutil.rmtree(snapshot_path, ignore_errors=True)
    shutil.copytree(output_path, snapshot_path)
    return snapshot_path, None


def ensure_runtime_paths():
    """Create and return session-scoped runtime directories.

    Isolating uploads, outputs, and snapshots per Streamlit session prevents
    path collisions when multiple tabs/users run simulations concurrently.
    """
    session_id = init_session_id()

    if "runtime_cleanup_done" not in st.session_state:
        removed = cleanup_stale_runtime_sessions(RUNS_ROOT, session_id)
        st.session_state["runtime_cleanup_done"] = True
        st.session_state["runtime_cleanup_removed"] = int(removed)

    session_root = os.path.join(RUNS_ROOT, session_id)
    upload_cache_dir = os.path.join(session_root, "upload_cache")
    outputs_dir = os.path.join(session_root, "outputs")
    snapshots_dir = os.path.join(session_root, "snapshots")

    for path in [RUNS_ROOT, session_root, upload_cache_dir, outputs_dir, snapshots_dir]:
        os.makedirs(path, exist_ok=True)

    return {
        "session_root": session_root,
        "upload_cache_dir": upload_cache_dir,
        "outputs_dir": outputs_dir,
        "snapshots_dir": snapshots_dir,
    }