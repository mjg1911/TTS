# Shared Chatterbox worker design

The user-provided design authorizes a single worker program selecting Nano or Turbo at startup, with engine switching allowed to restart it and all existing behavior preserved. Work stays in the current branch.

## Layout and interfaces

A new `chatterbox_payload` contains `worker/ChatterboxWorker.exe` and its dependency tree once, `models/nano/` and/or `models/turbo/`, and one integrity manifest. The manifest has `manifest_version: 2`, `runtime: Chatterbox`, the common `source_revision`, `models` keyed by `nano`/`turbo` with `model_revision` and `model_repo`, and `files` containing the exact hashed payload inventory. Required model hashes remain pinned. Models are optional individually; at least one is required.

`piper.chatterbox_assets.inspect_chatterbox_installation(root, engine)` accepts `nano`/`turbo`, verifies the entire payload and selected model pins, and returns root, worker_executable, model_dir, manifest_sha256. Existing engine inspectors accept this format as well as their legacy format.

`piper.chatterbox_worker.main` launches with `--engine nano|turbo --root PATH --model-dir PATH`. The model path must match the verified selected model directory. It delegates to the existing engine serving/runtime logic so CPU/CUDA selection, custom references, Turbo delivery modes, framing, errors and cancellation retain their behavior. Clients use the common executable/module for shared installations and retain legacy launch compatibility.

The tray prefers the bundled shared payload, then the per-user shared payload, then legacy per-engine locations. A typed missing-model error permits trying the next installation; integrity errors propagate to existing backend fallback handling. Build and installer workflows collect one shared payload and enforce requested engine availability. Legacy payload inputs may remain supported but must not accidentally restore two worker copies in the new build workflow.

## Verification

Tests cover model and runtime integrity, absent engines, shared executable identity, launch engine/model arguments, worker routing, Nano CPU/CUDA/custom references, Turbo CUDA and delivery modes, switching cleanup and Piper fallback. Run the Windows tray suite. Real CUDA inference and a frozen build are conditional on local model and build dependencies.
