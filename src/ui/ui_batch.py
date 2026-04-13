import json

import pandas as pd


def get_simulation_presets(max_days):
    """Return curated single-run simulation presets."""
    mdays = max(1, int(max_days))
    return {
        "Quick Smoke": {
            "sim_use_full": False,
            "sim_days": min(2, mdays),
            "sim_particle_mode": "random",
            "sim_particle_backend": "scipy",
            "sim_mesh_adapter": "none",
            "sim_particle_count_override": 0,
            "sim_random_seed": 42,
            "sim_dt_minutes": 10,
            "sim_output_hours": 3,
            "sim_release_mode": "instant",
            "sim_repeat_release_hours": 6,
            "sim_sample_velocity": True,
        },
        "Balanced Analysis": {
            "sim_use_full": False,
            "sim_days": min(5, mdays),
            "sim_particle_mode": "random",
            "sim_particle_backend": "scipy",
            "sim_mesh_adapter": "none",
            "sim_particle_count_override": 0,
            "sim_random_seed": 42,
            "sim_dt_minutes": 10,
            "sim_output_hours": 1,
            "sim_release_mode": "instant",
            "sim_repeat_release_hours": 6,
            "sim_sample_velocity": True,
        },
        "Station Focus": {
            "sim_use_full": False,
            "sim_days": min(3, mdays),
            "sim_particle_mode": "hybrid",
            "sim_particle_backend": "scipy",
            "sim_mesh_adapter": "none",
            "sim_particle_count_override": 0,
            "sim_random_seed": 42,
            "sim_dt_minutes": 10,
            "sim_output_hours": 1,
            "sim_release_mode": "instant",
            "sim_repeat_release_hours": 6,
            "sim_sample_velocity": True,
        },
        "Long Drift (Heavy)": {
            "sim_use_full": False,
            "sim_days": min(max(7, min(14, mdays)), mdays),
            "sim_particle_mode": "random",
            "sim_particle_backend": "scipy",
            "sim_mesh_adapter": "none",
            "sim_particle_count_override": 500,
            "sim_random_seed": 42,
            "sim_dt_minutes": 10,
            "sim_output_hours": 1,
            "sim_release_mode": "repeated",
            "sim_repeat_release_hours": 6,
            "sim_sample_velocity": True,
        },
    }


def apply_simulation_preset(session_state, preset_name, max_days):
    """Apply a named simulation preset into session state."""
    presets = get_simulation_presets(max_days)
    if preset_name not in presets:
        return False, f"Unknown preset '{preset_name}'."

    for key, value in presets[preset_name].items():
        session_state[key] = value

    session_state["sim_days"] = max(1, min(int(session_state.get("sim_days", 1)), int(max_days)))
    return True, f"Applied preset: {preset_name}."


def _to_bool(value):
    """Robustly coerce common types to bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        txt = value.strip().lower()
        if txt in {"1", "true", "yes", "y", "on"}:
            return True
        if txt in {"0", "false", "no", "n", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    raise ValueError(f"Cannot convert value to bool: {value}")


def _default_batch_form_rows(days, particle_mode, random_seed):
    """Return starter rows for the form-based batch mini-builder."""
    return [
        {
            "name": "Baseline",
            "use_full": False,
            "days": int(days),
            "mode": str(particle_mode),
            "mesh_adapter": "none",
            "particle_count": 0,
            "seed": int(random_seed),
            "backend": "scipy",
            "dt_minutes": 10,
            "output_hours": 3,
            "release_mode": "instant",
            "repeat_release_hours": 6,
            "sample_velocity": True,
            "u_var": "",
            "v_var": "",
            "lon_coord": "",
            "lat_coord": "",
            "time_coord": "",
            "depth_coord": "",
        },
        {
            "name": "Sensitivity-dt5",
            "use_full": False,
            "days": int(days),
            "mode": str(particle_mode),
            "mesh_adapter": "none",
            "particle_count": 0,
            "seed": int(random_seed),
            "backend": "scipy",
            "dt_minutes": 5,
            "output_hours": 3,
            "release_mode": "instant",
            "repeat_release_hours": 6,
            "sample_velocity": True,
            "u_var": "",
            "v_var": "",
            "lon_coord": "",
            "lat_coord": "",
            "time_coord": "",
            "depth_coord": "",
        },
    ]


def _build_batch_payload_from_rows(rows):
    """Convert form rows into a compact JSON-serializable payload list."""
    payload = []
    if rows is None:
        return payload

    if isinstance(rows, pd.DataFrame):
        records = rows.to_dict(orient="records")
    else:
        records = list(rows)

    for idx, row in enumerate(records, start=1):
        if not isinstance(row, dict):
            continue

        name = str(row.get("name", "") or "").strip()
        if not name:
            name = f"Batch Run {idx}"

        item = {"name": name}
        has_non_name_value = False

        for key in [
            "use_full",
            "days",
            "mode",
            "u_var",
            "v_var",
            "lon_coord",
            "lat_coord",
            "time_coord",
            "depth_coord",
            "mesh_adapter",
            "particle_count",
            "seed",
            "backend",
            "dt_minutes",
            "output_hours",
            "release_mode",
            "repeat_release_hours",
            "sample_velocity",
        ]:
            if key not in row:
                continue
            value = row.get(key)
            if value is None:
                continue
            if isinstance(value, float) and pd.isna(value):
                continue
            if isinstance(value, str):
                value = value.strip()
                if value == "":
                    continue

            item[key] = value
            has_non_name_value = True

        if has_non_name_value or name:
            payload.append(item)

    return payload


def parse_batch_config_payload(payload, base_config, max_days):
    """Validate already-parsed batch payload (list of run objects)."""
    if not isinstance(payload, list) or len(payload) == 0:
        return [], ["Batch config must be a non-empty list of run objects."]

    normalized = []
    errors = []
    allowed_modes = {"uniform", "random", "hybrid", "valid"}
    allowed_backends = {"scipy", "jit"}
    allowed_release = {"instant", "repeated"}
    allowed_mesh_adapters = {"none", "flattened_grid_1d"}

    for idx, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            errors.append(f"Run #{idx}: each item must be an object.")
            continue

        cfg = dict(base_config)
        cfg.update(item)
        run_name = str(cfg.get("name") or f"Batch Run {idx}").strip() or f"Batch Run {idx}"

        try:
            use_full = _to_bool(cfg.get("use_full", False))
            days = int(max_days) if use_full else int(cfg.get("days", base_config["days"]))
            days = max(1, min(days, int(max_days)))

            mode = str(cfg.get("mode", base_config["mode"])).strip().lower()
            if mode not in allowed_modes:
                raise ValueError(f"invalid mode '{mode}'")

            u_var = str(cfg.get("u_var", base_config.get("u_var", "uo"))).strip()
            v_var = str(cfg.get("v_var", base_config.get("v_var", "vo"))).strip()
            if not u_var or not v_var:
                raise ValueError("u_var and v_var must both be provided")
            if u_var == v_var:
                raise ValueError("u_var and v_var must be different")

            lon_coord = str(cfg.get("lon_coord", base_config.get("lon_coord", "longitude"))).strip()
            lat_coord = str(cfg.get("lat_coord", base_config.get("lat_coord", "latitude"))).strip()
            if not lon_coord or not lat_coord:
                raise ValueError("lon_coord and lat_coord must both be provided")
            if lon_coord == lat_coord:
                raise ValueError("lon_coord and lat_coord must be different")

            time_coord = str(cfg.get("time_coord", base_config.get("time_coord", "time"))).strip()
            if not time_coord:
                raise ValueError("time_coord must be provided")

            depth_coord = str(cfg.get("depth_coord", base_config.get("depth_coord", ""))).strip()

            mesh_adapter = str(cfg.get("mesh_adapter", base_config.get("mesh_adapter", "none"))).strip().lower()
            if mesh_adapter not in allowed_mesh_adapters:
                raise ValueError(f"invalid mesh_adapter '{mesh_adapter}'")

            backend = str(cfg.get("backend", base_config["backend"])).strip().lower()
            if backend not in allowed_backends:
                raise ValueError(f"invalid backend '{backend}'")

            particle_count = int(cfg.get("particle_count", base_config["particle_count"]))
            if particle_count < 0:
                raise ValueError("particle_count must be >= 0")

            seed = int(cfg.get("seed", base_config["seed"]))
            if seed < 0:
                raise ValueError("seed must be >= 0")

            dt_v = int(cfg.get("dt_minutes", base_config["dt_minutes"]))
            if dt_v < 1 or dt_v > 60:
                raise ValueError("dt_minutes must be in [1, 60]")

            out_v = int(cfg.get("output_hours", base_config["output_hours"]))
            if out_v < 1 or out_v > 24:
                raise ValueError("output_hours must be in [1, 24]")

            release_mode = str(cfg.get("release_mode", base_config["release_mode"])).strip().lower()
            if release_mode not in allowed_release:
                raise ValueError(f"invalid release_mode '{release_mode}'")

            repeat_v = int(cfg.get("repeat_release_hours", base_config["repeat_release_hours"]))
            if repeat_v < 1 or repeat_v > 24:
                raise ValueError("repeat_release_hours must be in [1, 24]")

            sample_velocity = _to_bool(cfg.get("sample_velocity", base_config["sample_velocity"]))
        except Exception as e:
            errors.append(f"Run #{idx} ({run_name}): {e}")
            continue

        normalized.append(
            {
                "name": run_name,
                "days": days,
                "mode": mode,
                "u_var": u_var,
                "v_var": v_var,
                "lon_coord": lon_coord,
                "lat_coord": lat_coord,
                "time_coord": time_coord,
                "depth_coord": depth_coord,
                "mesh_adapter": mesh_adapter,
                "particle_count": particle_count,
                "seed": seed,
                "backend": backend,
                "dt_minutes": dt_v,
                "output_hours": out_v,
                "release_mode": release_mode,
                "repeat_release_hours": repeat_v,
                "sample_velocity": sample_velocity,
            }
        )

    return normalized, errors


def parse_batch_config_json(raw_text, base_config, max_days):
    """Parse and validate a JSON list of batch run configurations."""
    text = str(raw_text or "").strip()
    if not text:
        return [], ["Batch config is empty. Add a JSON list of run objects."]

    try:
        payload = json.loads(text)
    except Exception as e:
        return [], [f"Invalid JSON: {e}"]

    return parse_batch_config_payload(payload, base_config, max_days)