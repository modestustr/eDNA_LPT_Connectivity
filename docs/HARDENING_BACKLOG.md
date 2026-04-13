# Hardening Backlog

This file records why the application is not yet fully bulletproof and what to improve next.

## Current Status

The app is substantially more robust than the original version, but it is not yet guaranteed to work across every external NetCDF layout or every large simulation workload.

Progress update (2026-04-09):

- Completed: flexible mapping for U, V, longitude, latitude, time, and optional depth.
- Completed: structural compatibility validation before simulation.
- Completed: coordinate lookup broadened beyond strict coords-only assumptions.

## Known Gaps

### 1. Time Coordinate Is Still Hard-Coded (Completed)

Current behavior:

- The app supports mapping for `U`, `V`, `longitude`, and `latitude`.
- The simulation engine still assumes the time coordinate is named `time`.

Why this matters:

- Many ocean model outputs use names such as `ocean_time`, `time_counter`, or model-specific alternatives.
- These files may still fail even if U/V/lon/lat were mapped correctly.

Next step:

- Implemented.

### 2. Depth Naming Is Only Partially Flexible (Completed)

Current behavior:

- The engine checks for a `depth` dimension and uses the first depth level if present.
- Alternative names such as `lev`, `depthu`, or model-specific vertical coordinates are not mapped.

Why this matters:

- Surface extraction can fail or silently behave differently on non-standard datasets.

Next step:

- Implemented.

### 3. Validation Is Name-Level, Not Structure-Level (Completed)

Current behavior:

- The app verifies that selected variables and coordinates exist.
- It does not yet prove they are dimensionally compatible.

Why this matters:

- A user can select a real variable with the wrong dimensionality or the wrong grid.
- That can lead to late failures or scientifically invalid runs.

Next step:

- Implemented.

### 4. Coordinate Support Is Limited to Dataset Coordinates (Largely Completed)

Current behavior:

- The app expects lon/lat names to exist in `ds.coords`.

Why this matters:

- Some datasets store spatial axes in data variables rather than coordinate variables.
- Some mesh-based products need a different extraction path.

Next step:

- Implemented for variable/axis lookup in current workflow.
- Remaining edge case: fully unstructured/mesh-specific datasets may still require dedicated adapters.

### 5. Station Analytics Can Become Expensive (Completed)

Current behavior:

- Station analytics loops over stations, time steps, and trajectories.

Why this matters:

- Large particle counts or long simulations can slow rendering noticeably.

Next step:

- Implemented via cKDTree-based proximity queries with automatic Haversine fallback when SciPy is unavailable.

### 6. Batch Validation Does Not Yet Check Semantic Compatibility Against the Actual Dataset (Completed)

Current behavior:

- Batch JSON is validated for type and range.
- It is not fully validated against the uploaded dataset before each run starts.

Why this matters:

- A batch item may pass JSON validation but still request unavailable or incompatible fields.

Next step:

- Implemented.

### 7. Streamlit-State and Output Paths Are Session-Robust, Not Process-Robust (Completed)

Current behavior:

- Session state, upload cache, and run snapshots are handled carefully.
- The app still assumes a single-user local workflow.

Why this matters:

- Multi-user, parallel, or server-style deployments can expose race conditions around shared paths like `output.zarr` and `.upload_cache/current_upload.nc`.

Next step:

- Implemented for per-session upload cache, per-run output paths, and session-scoped snapshots.
- Implemented lifecycle cleanup policy for stale session folders (time-based retention).

## Recommended Hardening Order (Updated)

1. Extend mesh adapters beyond flattened-grid family (future enhancement).

## Industrial Roadmap (4 Weeks)

This roadmap preserves the post-hardened scale-up plan agreed after peer reviews.
The goal is to move from "robust local tool" to "industrial-ready multi-user service"
without breaking current behavior.

### Week 1 - Memory Audit and Guardrails

- Audit all `.load()`, `.values`, and `np.array()` usages.
- Classify each usage as safe-slice, caution, or refactor-required.
- Add an `estimated_memory_usage` pre-run warning for heavy visualization paths.
- Add clear user confirmation when expected in-memory arrays exceed threshold.

Acceptance criteria:
- A documented inventory exists for all materialization points.
- High-risk rendering paths show proactive memory warnings.
- No regression in current plotting and analytics workflows.

### Week 2 - SimConfig Refactor

- Introduce `SimRunConfig` dataclass for simulation settings.
- Refactor `run_simulation` to consume config object inputs.
- Keep a temporary compatibility wrapper for old call style.
- Confirm output equivalence against current baseline runs.

Acceptance criteria:
- Simulation API surface is smaller and easier to evolve.
- Existing run buttons and batch mode still work unchanged for users.

### Week 3 - Background Execution MVP

- Move heavy simulation execution off Streamlit's main path.
- Keep progress reporting visible in UI.
- Add per-run cancel capability at MVP level.

Acceptance criteria:
- UI remains responsive during long simulations.
- Run failures propagate cleanly back to status panels.

### Week 4 - Load and Concurrency Validation

- Execute parallel run scenarios (target: 5-10 concurrent runs).
- Validate `runs/` isolation and retention cleanup under load.
- Record memory profile, completion latency, and failure signatures.

Acceptance criteria:
- No cross-session file collisions under stress.
- Cleanup policy remains stable and predictable.
- Results are captured as a repeatable pre-release checklist.

## Industrial Tracking

- [x] I1. Week 1 memory audit complete
- [ ] I2. Week 2 SimRunConfig refactor complete
- [ ] I3. Week 3 background execution MVP complete
- [ ] I4. Week 4 load validation complete

## UX Audit Snapshot (2026-04-09)

This snapshot preserves user-experience findings so they are not lost during
industrial hardening work.

### Key Findings (User Perspective)

1. First-run cognitive load is high
- Mapping, advanced settings, batch JSON, cost panel, and preflight are all visible in a dense sequence.

2. Secondary workflows appear too early
- Run History and A/B Comparison are useful, but they interrupt first-run focus.

3. Batch mode is expert-friendly but error-prone for new users
- JSON-only authoring increases friction and typo risk.

4. Visualization controls are powerful but operationally heavy
- Many controls are available at once; presets help, but first-pass flow can be simplified.

5. Error guidance is strong post-failure
- Similar action-oriented guidance should be expanded to pre-run risk states.

### UX Action Waves (Recommended)

Wave A (quick wins, low risk):
- Add "First Run Mode" toggle to progressively reveal advanced/batch/comparison blocks.
- Move history/comparison lower in the flow (after first successful run context).
- Disable run when critical mappings are missing, with one-line reason.

Wave B (medium effort):
- Add a mini batch builder (form-based) that generates JSON in the background.
- Add memory risk tier in Estimated Simulation Cost (low/medium/high).

Wave C (later):
- Streamline visualization control density using progressive sections.
- Add user-facing task presets by intent (quick check, station analysis, publication export).

## UX Tracking

- [x] U1. First Run Mode + progressive disclosure
- [x] U2. Run gating with explicit disable reason
- [x] U3. Batch mini-builder (form -> JSON)
- [x] U4. Memory risk tier in cost panel
- [x] U5. Visualization control density reduction
- [x] U6. Simulation presets (single-run profiles)

## Execution Plan (P0/P1/P2)

This section converts remaining hardening work into actionable implementation phases.

### P0 (Do First)

Goal: prevent invalid runs and avoid path collisions in real usage.

1. Per-batch semantic precheck before each dispatch

- Scope:
	- Before calling `run_simulation` for each batch item, run the same structural validator used in single-run mode against the currently uploaded dataset and that specific batch config.
	- If invalid, do not dispatch that run; add status `skipped_invalid` with explicit reason and suggested fix.
- Acceptance criteria:
	- A batch item with incompatible `u_var/v_var/lon/lat/time/depth` never starts simulation.
	- Batch summary includes a clear reason and fix guidance per skipped run.
	- Valid batch items continue to run.

2. Per-session/per-run output and cache isolation

- Scope:
	- Replace shared paths (`output.zarr`, `.upload_cache/current_upload.*`) with unique session/run-scoped paths.
	- Keep a cleanup strategy so old run folders do not grow indefinitely.
- Acceptance criteria:
	- Two concurrent sessions cannot overwrite each other's active output/cache files.
	- Run history snapshots continue to work.
	- Existing export actions still work with new paths.

Estimated effort: medium.

### P1 (Do Next)

Goal: keep interface responsive and robust on larger workloads.

3. Station analytics performance optimization

- Scope:
	- Reduce nested-loop overhead in analytics.
	- Add practical guardrails for very large runs (for example optional sampling/cap and clear warnings).
- Acceptance criteria:
	- Analytics remains responsive on medium-large runs.
	- User receives explicit warning when full analytics would be expensive.
	- Result meaning remains unchanged for default mode.

4. Additional dataset sanity checks (spatial and value-level)

- Scope:
	- Add optional checks for suspicious coordinate ranges and axis monotonicity.
	- Add clearer warnings when values look likely non-geographic or inconsistent.
- Acceptance criteria:
	- Common coordinate mistakes trigger a warning before run.
	- Warnings are actionable and do not block valid datasets unnecessarily.

Status:

- Implemented.

Estimated effort: medium.

### P2 (Later / Advanced)

Goal: extend compatibility and interoperability.

5. Unstructured/mesh-specific adapters

- Scope:
	- Add adapter path(s) for datasets that do not fit the current regular-grid assumptions.
	- Keep current regular-grid path unchanged.
- Acceptance criteria:
	- At least one non-standard dataset family can be configured without code edits.
	- Adapter limitations are documented in README.

6. Additional export formats for GIS workflows

- Scope:
	- Add optional GeoJSON export for trajectories/stations summaries.
	- Keep CSV and ZIP behavior unchanged.
- Acceptance criteria:
	- Exported file is directly consumable in common GIS tools.
	- Existing exports continue to pass current workflows.

Estimated effort: medium-high.

Status:

- Implemented (initial adapter path): `mesh_adapter=flattened_grid_1d` for 1D flattened node grids that can be reshaped into regular lat/lon.
- Remaining enhancement: broaden adapter coverage for fully unstructured mesh families.

Status:

- Implemented (GeoJSON export for trajectories and station metrics summaries).

## Tracking Template

Use this lightweight checklist while implementing:

- [x] P0.1 Batch semantic precheck
- [x] P0.2 Session/run path isolation
- [x] P1.1 Station analytics optimization
- [x] P1.2 Spatial sanity checks
- [x] P2.1 Mesh adapters
- [x] P2.2 GIS export formats

## P3 (Production-Scale) — New Items from Second Peer Review (2026-04-09)

A second peer review identified three concerns not covered by P0-P2. These do not affect local single-user use but become critical in server/multi-user deployments.

### P3.1 Background Execution — Simulation Blocks UI Thread

Current behavior:
- `core_lpt.run_simulation()` is called directly in Streamlit's main execution thread.
- The UI freezes for the entire duration of the simulation.

Why this matters:
- Single user: interface appears unresponsive but eventually recovers.
- Multi-user server: one long simulation starves all other sessions.

Clarification on `.load()` calls:
- All 18 `.load()` calls are on time-step slices (`[:, step]`, `[:, :step+1]`), not full datasets.
- This is the correct Zarr pattern (lazy open -> targeted materialization).
- Risk surfaces only at very large particle counts; mitigation: add a visualization guard.

Next step options:
- Short-term: `concurrent.futures.ThreadPoolExecutor` + `st.spinner` — prevents UI freeze.
- Medium-term: `multiprocessing.Process` isolation.
- Long-term: Celery / RQ worker pool — correct architecture for multi-user deployment.

Acceptance criteria:
- UI remains interactive during simulation.
- Cancellation is possible without killing the server process.

Estimated effort: medium (ThreadPoolExecutor) to high (Celery).

### P3.2 `run_simulation` API — 19 Parameters Should Become a Config Object

Current behavior:
- `run_simulation` has 19 positional/keyword arguments.
- `app.py` uses `**_build_run_kwargs(...)` as a workaround.

Next step:
- Define `SimRunConfig` dataclass in `core_lpt.py`.
- Refactor to `run_simulation(config: SimRunConfig, output_path, progress_bar)`.
- Update `_build_run_kwargs` in `app.py` to return a `SimRunConfig` instance.

Acceptance criteria:
- `run_simulation` has <= 4 top-level parameters.
- All existing call sites produce identical output.

Estimated effort: low-medium.

### P3.3 Error Handling Convention Inconsistency

Current behavior:
- Simulation-path functions raise; some helpers return sentinel values — implicit mix.

Next step:
- Convention: simulation-path functions always raise; analytics/export helpers return `(result, warnings_list)`.
- Audit and align; add a one-line convention comment at top of each module.

Acceptance criteria:
- Every public function in `core_lpt.py` raises on fatal error.
- Every analytics/export helper in `app.py` returns `(result, warnings)`..

Estimated effort: low.

## P3 Tracking

- [ ] P3.1 Background execution (UI thread isolation)
- [ ] P3.2 SimRunConfig dataclass refactor
- [ ] P3.3 Error handling convention

---


## P3 (Production-Scale) — New Items from Second Peer Review (2026-04-09)

A second peer review identified three concerns not covered by P0-P2. These do not affect local
single-user use but become critical in server/multi-user deployments.

### P3.1 Background Execution — Simulation Blocks UI Thread

Current behavior:
- `core_lpt.run_simulation()` is called directly in Streamlit's main execution thread.
- The UI freezes for the entire duration of the simulation.

Why this matters:
- Single user: interface appears unresponsive but eventually recovers.
- Multi-user server: one long simulation starves all other sessions.

Clarification on `.load()` calls:
- All 18 `.load()` calls in the codebase are on time-step slices (`[:, step]`, `[:, :step+1]`),
  not full datasets. This is the correct Zarr pattern (lazy open -> targeted materialization).
- Risk surfaces only at very large particle counts (>50k) -- add visualization guard.

Next step options (increasing complexity):
- Short-term: `concurrent.futures.ThreadPoolExecutor` + `st.spinner` -- prevents UI freeze,
  keeps single-process model.
- Medium-term: `multiprocessing.Process` isolation -- no GIL contention, harder session state
  hand-off.
- Long-term: Celery / RQ worker pool -- correct architecture for multi-user server deployment.

Acceptance criteria:
- UI remains interactive during simulation (progress bar still updates).
- Cancellation is possible without killing the server process.

Estimated effort: medium (ThreadPoolExecutor) to high (Celery).

### P3.2 `run_simulation` API -- 19 Parameters Should Become a Config Object

Current behavior:
- `run_simulation` has 19 positional/keyword arguments.
- `app.py` uses `**_build_run_kwargs(...)` as a workaround.

Why this matters:
- Adding a new simulation parameter requires updating every call site.
- Type safety and IDE discoverability are poor.

Next step:
- Define `SimRunConfig` dataclass in `core_lpt.py`.
- Refactor to `run_simulation(config: SimRunConfig, output_path, progress_bar)`.
- Update `_build_run_kwargs` in `app.py` to return a `SimRunConfig` instance.

Acceptance criteria:
- `run_simulation` has <= 4 top-level parameters.
- All existing call sites produce identical output.

Estimated effort: low-medium.

### P3.3 Error Handling Convention Inconsistency

Current behavior:
- Simulation-path functions raise exceptions; some analytics/export helpers return sentinel values.
- The mix is implicit -- callers must know per-function which style applies.

Next step:
- Convention: simulation-path functions always raise; analytics/export helpers return
  `(result, warnings_list)`.
- Audit and align existing functions; add a one-line convention comment at the top of each module.

Acceptance criteria:
- Every public function in `core_lpt.py` raises on fatal error (no silent sentinel returns).
- Every analytics/export helper in `app.py` returns `(result, warnings)`.

Estimated effort: low.

## P3 Tracking

- [ ] P3.1 Background execution (UI thread isolation)
- [ ] P3.2 SimRunConfig dataclass refactor
- [ ] P3.3 Error handling convention

---


## Definition of "Bulletproof" for This Project

This project can be considered close to bulletproof when it can:

1. Accept multiple dataset naming conventions without code edits.
2. Reject incompatible datasets before simulation starts.
3. Explain every failure with a precise user-facing fix.
4. Avoid shared-path conflicts across repeated or parallel runs.
5. Stay responsive even with larger outputs and analytics workloads.